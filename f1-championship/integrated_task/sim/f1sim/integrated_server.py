"""Sealed sidecar for the integrated SOLO_COORDINATION mode (benchmark 2.0.x).

Same boundary as the 1.1.0 sidecar (f1sim.server): one Unix socket on the shared volume;
seed, live state, journal v2 and the Engineer record store stay in this container's private
directory (0700). Engineer A/B run inside the sidecar in a deterministic offline condition
(no network here), so their reports are produced and recorded by trusted code, never by the
agent. The agent's Chief is the only actor that can submit actions (`act`). After a restart the
session is rebuilt by verified replay of journal v2 and the Engineer store; it never rolls back.
"""

from __future__ import annotations

import json
import os
import sys
import threading
import time
from pathlib import Path
from typing import Any, Dict

from f1pitwall.integrated import config as C
from f1pitwall.integrated import verify as V
from f1pitwall.integrated.engineers import EngineerBroker
from f1pitwall.integrated.session import CHAMPIONSHIP_COMPLETE, IntegratedSession, TickError
from f1pitwall.journal import canonical
from f1sim import server as legacy

MODE_PATH = Path(os.environ.get("F1SIM_MODE_PATH", "/opt/f1sim/secret/mode.json"))
TEAM = "Apex"
OFFLINE_CONDITIONS = ("CHIEF_ONLY", "MOCK_ENGINEERS", "CONFLICTING_LOCAL_RECOMMENDATIONS",
                      "NOMINAL_CONFIDENCE_CONTROL", "HIGH_SELF_REPORTED_CONFIDENCE_CONTROL")


def load_mode(path: Path = MODE_PATH) -> Dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if value.get("mode") != C.SOLO_COORDINATION or value.get("engineers") not in OFFLINE_CONDITIONS:
        raise ValueError("sidecar serves SOLO_COORDINATION with an offline Engineer condition")
    value.setdefault("benchmark_version", C.INTEGRATED_VERSION)
    if value["benchmark_version"] not in (C.INTEGRATED_VERSION,) + C.OPT_IN_VERSIONS:
        raise ValueError("unsupported benchmark_version in mode file")
    if not isinstance(value.get("c5_weekend", False), bool):
        raise ValueError("c5_weekend must be a boolean")
    return value


def task_config(mode: Dict[str, Any]) -> C.IntegratedConfig:
    """The sidecar's and the verifier's configuration (one function, so they cannot diverge)."""
    base = C.solo_coordination(engineers=mode["engineers"], chief={"provider": "harbor_agent"})
    if mode.get("c5_weekend"):  # opt-in 2.2.0 C5 practice/qualifying weekend
        return C.with_c5_weekend(base)
    return C.with_version(base, mode["benchmark_version"])


def public_rules(config: C.IntegratedConfig) -> Dict[str, Any]:
    from f1pitwall.integrated.race import TEAM_ORDER_MODEL
    rules = json.loads(json.dumps(legacy.PUBLIC_RULES))
    rules.update({
        "benchmark_version": config.benchmark_version,
        "mode": config.mode,
        "contract": "f1-championship integrated contract v2 (Track A + Track B + Track C team orders)",
        "decision_id": "every observation carries decision_id (= tick_id, e.g. t001); act must echo it",
        "team_orders": TEAM_ORDER_MODEL,
        "engineers": {"condition": config.teams[0].engineers,
                      "note": ("Engineer A/B each see only their own driver and public rivals; their reports appear "
                               "in observation.engineer_reports with a record_hash. Reports are advice, not actions. "
                               "List the record hashes you used in the optional consumed_reports field.")},
        "objective": "maximize Apex constructors' points over the whole championship",
    })
    if config.benchmark_version in ("2.1.0", "2.2.0"):  # 2.2.0 keeps the 2.1.0 PU rules
        from f1pitwall import pu_rules
        rules["power_unit_rules"] = pu_rules.RULES
        rules["track_a_model"] = json.loads(json.dumps(pu_rules.with_fia_pu_rules(rules["track_a_model"])))
        rules["track_a_model"]["allocation"] = {
            "superseded_by": "power_unit_rules (2.1.0)",
            "note": ("2.1.0: no shared free-unit pool. Each driver has an element allocation per type; "
                     "a REPLACE needs a unit in the team's physical stock; using more elements than the "
                     "allocation costs grid places (first extra element of a type 4, later 2, cumulative); "
                     "above 5 places the driver starts behind all other cars, in qualifying order.")}
    if getattr(config, "c5_weekend", False):
        rules["weekend"] = weekend_rules()
    return rules


def weekend_rules() -> Dict[str, Any]:
    """Public C5 weekend rules (2.2.0). Priors, noise model and budgets come from the C5 fixture."""
    from track_c import c5
    model = c5.load_model("mixed")
    return {
        "phases": "COMPONENT_DECISION -> PRACTICE (session 1) -> PRACTICE (session 2) -> QUALIFYING -> RACE_STRATEGY x 14",
        "setups": {k: v for k, v in model["setups"].items()},
        "noise_model": model["noise_model"],
        "lap_budget_per_driver": model["lap_budget_per_driver"],
        "sessions_total": model["sessions_total"],
        "programs": {p: f"measures {v['metric']}" for p, v in model["noise_model"]["programs"].items()},
        "hidden_truth": ("each setup's true effect per weekend is drawn once from its published prior; practice "
                         "measurements are that truth plus published Gaussian noise"),
        "qualifying": ("time = published base pace + true qualifying offset of the chosen setup + per-run noise; "
                       "TWO_RUN keeps the better run; rivals run the default setup once. The order is the "
                       "provisional grid; power-unit grid penalties are applied after it."),
        "parc_ferme": ("each car races with its qualifying setup: its true long-run pace offset is added to the "
                       "car's race pace and its true degradation factor multiplies the car's tyre degradation"),
        "fallback": "no practice laps; default setup with one qualifying run",
        "data_status": "synthetic_only",
    }


class IntegratedSimulator:
    def __init__(self, state_dir: Path, base_seed: int, mode: Dict[str, Any]) -> None:
        self._lock = threading.Lock()
        self._dir = state_dir
        state_dir.mkdir(parents=True, exist_ok=True)
        os.chmod(state_dir, 0o700)
        self._journal_path = state_dir / "journal.jsonl"
        self._sealed_path = state_dir / "SEALED"
        self._stats_path = state_dir / "stats.json"
        self._store = state_dir / "engineers"
        self.config = task_config(mode)
        self._seed = base_seed
        self._stats = {"observe": 0, "rules": 0, "ping": 0, "act_accepted": 0, "act_rejected": 0,
                       "protocol_errors": 0}
        broker = EngineerBroker(self._store) if mode["engineers"] != "CHIEF_ONLY" else None
        entries = []
        if self._journal_path.exists():
            entries = [json.loads(x) for x in self._journal_path.read_text(encoding="utf-8").splitlines() if x]
        if entries:
            replay_broker = EngineerBroker.replaying(self._store) if broker else None
            self.session = V.replay(self.config, base_seed, entries, engineer_broker=replay_broker,
                                    require_complete=False)["session"]
            self.session._broker = broker
            self.session.journal = entries  # verified chain incl. logged rejections; new entries continue it
        else:
            self.session = IntegratedSession(self.config, base_seed, engineer_broker=broker)
        self._persisted = len(self.session.journal)
        if self._stats_path.exists():
            self._stats.update(json.loads(self._stats_path.read_text(encoding="utf-8")))

    def _flush(self) -> None:
        new = self.session.journal[self._persisted:]
        if new:
            with self._journal_path.open("a", encoding="utf-8") as handle:
                for entry in new:
                    handle.write(json.dumps(entry, sort_keys=True, separators=(",", ":")) + "\n")
                handle.flush()
                os.fsync(handle.fileno())
            self._persisted = len(self.session.journal)
        self._stats_path.write_text(json.dumps(self._stats, sort_keys=True), encoding="utf-8")

    def count_protocol_error(self) -> None:
        with self._lock:
            self._stats["protocol_errors"] += 1
            self._flush()

    def _observation(self) -> Dict[str, Any]:
        obs = self.session.observation(TEAM)
        obs["decision_id"] = None if self.session.decision_type == CHAMPIONSHIP_COMPLETE else self.session.tick_id
        return obs

    def handle(self, request: Dict[str, Any]) -> Dict[str, Any]:
        with self._lock:
            cmd = request["cmd"]
            if cmd == "ping":
                self._stats["ping"] += 1
                return {"ok": True, "server_version": self.config.benchmark_version,
                        "benchmark_version": self.config.benchmark_version}
            if cmd == "rules":
                self._stats["rules"] += 1
                self._flush()
                return {"ok": True, "rules": public_rules(self.config)}
            if cmd == "observe":
                self._stats["observe"] += 1
                self._flush()
                return {"ok": True, "observation": self._observation()}
            return self._act(request)

    def _act(self, request: Dict[str, Any]) -> Dict[str, Any]:
        if self._sealed_path.exists():
            self._stats["act_rejected"] += 1
            self._flush()
            return {"ok": False, "error_code": "sealed", "message": "evaluation has been sealed"}
        if self.session.decision_type == CHAMPIONSHIP_COMPLETE:
            self._stats["act_rejected"] += 1
            self._flush()
            return {"ok": False, "error_code": "championship_complete", "message": "championship is already complete"}
        tick = request["decision_id"]
        try:
            canonical(request["action"])
            self.session.submit(TEAM, tick if isinstance(tick, str) else repr(tick), request["action"],
                                submitted_via="f1ctl_socket")
        except (TickError, TypeError, ValueError) as exc:
            self._stats["act_rejected"] += 1
            self._flush()
            code = "invalid_action"
            if tick != self.session.tick_id:
                code = "out_of_order_decision"
            return {"ok": False, "error_code": code, "message": str(exc), "decision_id": self.session.tick_id}
        self._stats["act_accepted"] += 1
        self._flush()
        return {"ok": True, "accepted": tick, "observation": self._observation()}


def serve(socket_path: Path = legacy.SOCKET_PATH, state_dir: Path = legacy.STATE_DIR,
          seed_path: Path = legacy.SEED_PATH, mode_path: Path = MODE_PATH, ready=None):
    simulator = IntegratedSimulator(state_dir, legacy._load_seed(seed_path), load_mode(mode_path))
    socket_path.parent.mkdir(parents=True, exist_ok=True)
    if socket_path.exists() or socket_path.is_symlink():
        socket_path.unlink()
    srv = legacy._Server(str(socket_path), legacy._Handler)
    srv.simulator = simulator
    os.chmod(socket_path, 0o666)
    if ready is not None:
        ready.set()
    return srv


def main() -> int:
    try:
        srv = serve()
    except (OSError, ValueError, V.ReplayError) as exc:
        print(f"f1sim integrated failed to start: {type(exc).__name__}", file=sys.stderr)
        return 1
    print(f"f1sim integrated {C.INTEGRATED_VERSION} listening", flush=True)
    srv.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
