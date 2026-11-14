"""Authoritative championship simulator served over a Unix socket.

Runs in its own container. The hidden seed, live state and journal stay on this
container's private filesystem; only the socket is placed on the volume shared
with the agent container. There is no reset, rewind, preview or seed command.
"""

from __future__ import annotations

import copy
import json
import os
import socket
import socketserver
import sys
import threading
import time
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from f1pitwall import engine
from f1pitwall.championship_contract import (
    CHAMPIONSHIP_COMPLETE,
    COMPONENT_DECISION,
    RACE_STRATEGY,
    ChampionshipSession,
)
from f1pitwall import coefficients as coef
from f1pitwall.journal import (
    GENESIS_HASH,
    JOURNAL_VERSION,
    JournalError,
    decision_id,
    observation_hash,
    parse_journal,
    replay,
    seal_entry,
)

SERVER_VERSION = "p1-1"
SOCKET_PATH = Path(os.environ.get("F1SIM_SOCKET", "/run/f1sim/sim.sock"))
STATE_DIR = Path(os.environ.get("F1SIM_STATE_DIR", "/var/lib/f1sim"))
SEED_PATH = Path(os.environ.get("F1SIM_SEED_PATH", "/opt/f1sim/secret/seed.json"))
MAX_REQUEST_BYTES = 16 * 1024
CONNECTION_TIMEOUT_SEC = 5.0
MAX_LOGGED_REJECTIONS = 2000
COMMAND_FIELDS = {
    "ping": {"cmd"},
    "rules": {"cmd"},
    "observe": {"cmd"},
    "act": {"cmd", "decision_id", "action"},
}

PUBLIC_RULES = {
    "contract": "f1-championship sequential decisions, P0 mechanics",
    "phases": {
        COMPONENT_DECISION: "one USE/REPLACE choice per Apex driver/component before each race",
        RACE_STRATEGY: "three sequential PIT/STAY choices for Apex A and Apex B per race",
        CHAMPIONSHIP_COMPLETE: "no further actions",
    },
    "decision_id": ("every observation carries decision_id; act must echo it. A stale id is "
                    "rejected as a duplicate, a future id as out of order. Rejected requests do "
                    "not change state."),
    "race_rules": engine.RULES,
    "race_rules_track_a": {
        "grid": "qualifying order by pace = published base pace + team track offset + wear pace loss; then grid drops",
        "published_base_pace": engine.LEGACY_BASE_PACE,
        "traffic": "dirty-air loss replaces the legacy positional traffic term (see track_a_model.track_performance.overtaking)",
        "retirements": ("each car retires with its published dnf probability; draws are seeded and independent "
                        "of all actions; a retired car scores 0 and is classified last"),
        "points": "only finishers score; points by finishing position",
    },
    "track_a_model": coef.DEFAULT,
    "objective": "maximize Apex constructors' points over the whole championship",
    "no_reset": "the championship cannot be reset, rewound, previewed or replayed",
}


def _load_seed(path: Path) -> int:
    value = json.loads(path.read_text(encoding="utf-8"))
    seed = value.get("base_seed") if isinstance(value, dict) else None
    if isinstance(seed, bool) or not isinstance(seed, int):
        raise ValueError("invalid seed file")
    return seed


class Simulator:
    """Single authoritative session plus append-only journal; all methods hold one lock."""

    def __init__(self, state_dir: Path, base_seed: int) -> None:
        self._lock = threading.Lock()
        self._state_dir = state_dir
        self._journal_path = state_dir / "journal.jsonl"
        self._sealed_path = state_dir / "SEALED"
        self._stats_path = state_dir / "stats.json"
        state_dir.mkdir(parents=True, exist_ok=True)
        os.chmod(state_dir, 0o700)
        self._base_seed = base_seed
        self._stats = {"observe": 0, "rules": 0, "ping": 0, "act_accepted": 0,
                       "act_rejected": 0, "rejections_not_logged": 0, "protocol_errors": 0}
        self._restore()

    def _restore(self) -> None:
        """Rebuild state from the journal after a restart; never rolls back."""
        entries = []
        if self._journal_path.exists():
            entries = parse_journal(self._journal_path.read_text(encoding="utf-8"))
        result = replay(entries, self._base_seed)
        self._session = result["session"]
        self._accepted = result["accepted"]
        self._seq = len(entries)
        self._head = result["head_hash"]
        self._logged_rejections = result["rejected"]
        if self._stats_path.exists():
            self._stats.update(json.loads(self._stats_path.read_text(encoding="utf-8")))

    def _append(self, entry: Dict[str, Any]) -> None:
        sealed = seal_entry(entry, self._head)
        with self._journal_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(sealed, sort_keys=True, separators=(",", ":")) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        self._seq = sealed["seq"]
        self._head = sealed["entry_hash"]

    def _save_stats(self) -> None:
        tmp = self._stats_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self._stats, sort_keys=True), encoding="utf-8")
        os.replace(tmp, self._stats_path)

    def _public_observation(self) -> Dict[str, Any]:
        observation = self._session.observation()
        observation["decision_id"] = (None if self._session.decision_type == CHAMPIONSHIP_COMPLETE
                                      else decision_id(self._accepted))
        return observation

    def count_protocol_error(self) -> None:
        with self._lock:
            self._stats["protocol_errors"] += 1
            self._save_stats()

    def handle(self, request: Dict[str, Any]) -> Dict[str, Any]:
        with self._lock:
            cmd = request["cmd"]
            if cmd == "ping":
                self._stats["ping"] += 1
                return {"ok": True, "server_version": SERVER_VERSION}
            if cmd == "rules":
                self._stats["rules"] += 1
                self._save_stats()
                return {"ok": True, "rules": PUBLIC_RULES}
            if cmd == "observe":
                self._stats["observe"] += 1
                self._save_stats()
                return {"ok": True, "observation": self._public_observation()}
            return self._act(request)

    def _act(self, request: Dict[str, Any]) -> Dict[str, Any]:
        received = time.time()
        before_obs = self._session.observation()
        before_hash = observation_hash(before_obs)
        expected = decision_id(self._accepted)
        submitted_id = request["decision_id"]
        action = request["action"]
        error_code: Optional[str] = None
        message = ""

        if self._sealed_path.exists():
            error_code, message = "sealed", "evaluation has been sealed"
        elif self._session.decision_type == CHAMPIONSHIP_COMPLETE:
            error_code, message = "championship_complete", "championship is already complete"
        elif not isinstance(submitted_id, str):
            error_code, message = "bad_decision_id", "decision_id must be a string"
        elif submitted_id != expected:
            if _id_number(submitted_id) is not None and _id_number(submitted_id) < self._accepted + 1:
                error_code, message = "duplicate_decision", f"{submitted_id} was already decided"
            else:
                error_code, message = "out_of_order_decision", f"expected decision_id {expected}"

        if error_code is None:
            candidate = copy.deepcopy(self._session)
            try:
                candidate.submit(copy.deepcopy(action))
            except ValueError as exc:
                error_code, message = "invalid_action", str(exc)
            else:
                self._session = candidate
                self._accepted += 1

        entry = {
            "journal_version": JOURNAL_VERSION,
            "seq": self._seq + 1,
            "kind": "accepted" if error_code is None else "rejected",
            "decision_id": submitted_id if isinstance(submitted_id, str) else None,
            "decision_type": before_obs["decision_type"],
            "action": _json_safe(action),
            "error_code": error_code,
            "obs_before_sha256": before_hash,
            "obs_after_sha256": (observation_hash(self._session.observation())
                                 if error_code is None else None),
            "t_received": round(received, 6),
            "t_done": round(time.time(), 6),
        }
        if error_code is None:
            self._stats["act_accepted"] += 1
            self._append(entry)
            self._save_stats()
            return {"ok": True, "accepted": submitted_id,
                    "observation": self._public_observation()}

        self._stats["act_rejected"] += 1
        if self._logged_rejections < MAX_LOGGED_REJECTIONS:
            self._logged_rejections += 1
            self._append(entry)
        else:
            self._stats["rejections_not_logged"] += 1
        self._save_stats()
        return {"ok": False, "error_code": error_code, "message": message,
                "decision_id": expected if self._session.decision_type != CHAMPIONSHIP_COMPLETE
                else None}


def _id_number(value: str) -> Optional[int]:
    if len(value) == 4 and value[0] == "d" and value[1:].isdigit():
        return int(value[1:])
    return None


def _json_safe(value: Any) -> Any:
    try:
        json.dumps(value, allow_nan=False)
        return copy.deepcopy(value)
    except (TypeError, ValueError):
        return None


def parse_request(raw: bytes) -> Tuple[Optional[Dict[str, Any]], Optional[Dict[str, Any]]]:
    """Return (request, None) or (None, error_response)."""
    if len(raw) > MAX_REQUEST_BYTES:
        return None, {"ok": False, "error_code": "request_too_large",
                      "message": f"requests are limited to {MAX_REQUEST_BYTES} bytes"}
    try:
        request = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None, {"ok": False, "error_code": "malformed_request", "message": "request is not JSON"}
    if not isinstance(request, dict) or request.get("cmd") not in COMMAND_FIELDS:
        return None, {"ok": False, "error_code": "unknown_command",
                      "message": f"commands: {sorted(COMMAND_FIELDS)}"}
    if set(request) != COMMAND_FIELDS[request["cmd"]]:
        return None, {"ok": False, "error_code": "malformed_request",
                      "message": f"{request['cmd']} takes exactly {sorted(COMMAND_FIELDS[request['cmd']])}"}
    return request, None


class _Handler(socketserver.StreamRequestHandler):
    timeout = CONNECTION_TIMEOUT_SEC

    def handle(self) -> None:
        simulator: Simulator = self.server.simulator  # type: ignore[attr-defined]
        try:
            raw = self.rfile.readline(MAX_REQUEST_BYTES + 2)
        except (socket.timeout, OSError):
            return
        request, error = parse_request(raw.rstrip(b"\n"))
        if error is None and request is not None:
            try:
                response = simulator.handle(request)
            except Exception:  # never leak internals
                response = {"ok": False, "error_code": "internal_error", "message": "internal error"}
        else:
            simulator.count_protocol_error()
            response = error
        try:
            self.wfile.write((json.dumps(response, sort_keys=True) + "\n").encode("utf-8"))
        except OSError:
            pass


class _Server(socketserver.ThreadingMixIn, socketserver.UnixStreamServer):
    daemon_threads = True
    request_queue_size = 128


def serve(socket_path: Path = SOCKET_PATH, state_dir: Path = STATE_DIR,
          seed_path: Path = SEED_PATH, ready: Optional[threading.Event] = None) -> _Server:
    simulator = Simulator(state_dir, _load_seed(seed_path))
    socket_path.parent.mkdir(parents=True, exist_ok=True)
    if socket_path.exists() or socket_path.is_symlink():
        socket_path.unlink()
    server = _Server(str(socket_path), _Handler)
    server.simulator = simulator  # type: ignore[attr-defined]
    os.chmod(socket_path, 0o666)
    if ready is not None:
        ready.set()
    return server


def main() -> int:
    try:
        server = serve()
    except (OSError, ValueError, JournalError) as exc:
        print(f"f1sim failed to start: {type(exc).__name__}", file=sys.stderr)
        return 1
    print(f"f1sim {SERVER_VERSION} listening", flush=True)
    server.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
