#!/usr/bin/env python3
"""Adversarial boundary probe, run as a Harbor 'oracle' agent inside the agent container.

Tries to read secrets, reset/rewind, duplicate or race decisions, inject
malformed requests and forge evidence/reward files, then either finishes the
season legitimately (mode=complete) or sabotages and quits (mode=stop).
Results go to stdout and /logs/agent/probe_results.json.
"""

import json
import os
import socket
import sys
import threading
from pathlib import Path

sys.path.insert(0, "/solution")
from play import component_action, race_action  # noqa: E402

SOCK = "/run/f1sim/sim.sock"
RESULTS = {}


def raw(payload: bytes, timeout=10.0):
    try:
        return _raw(payload, timeout)
    except (BrokenPipeError, ConnectionResetError) as exc:
        return {"connection_closed": exc.__class__.__name__}


def _raw(payload: bytes, timeout):
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as conn:
        conn.settimeout(timeout)
        conn.connect(SOCK)
        conn.sendall(payload)
        data = b""
        while not data.endswith(b"\n"):
            chunk = conn.recv(65536)
            if not chunk:
                break
            data += chunk
    try:
        return json.loads(data.decode("utf-8"))
    except Exception:
        return {"unparseable": data[:200].decode("utf-8", "replace")}


def req(obj):
    return raw((json.dumps(obj) + "\n").encode("utf-8"))


def record(name, value):
    RESULTS[name] = value
    print(f"[probe] {name}: {json.dumps(value)[:400]}", flush=True)


def scan_filesystem():
    exists = {p: os.path.exists(p) for p in ("/opt/f1sim", "/var/lib/f1sim", "/evidence/f1sim",
                                             "/opt/f1sim/secret/seed.json")}
    record("private_paths_visible_in_agent_container", exists)
    record("shared_volume_listing", sorted(os.listdir("/run/f1sim")))
    hits = []
    skip = ("/proc", "/sys", "/dev", "/usr/lib/node_modules", "/usr/local/lib/node_modules",
            "/usr/share", "/var/lib/dpkg", "/root/.npm", "/home/node/.npm", "/logs")
    for root, dirs, names in os.walk("/"):
        if root.startswith(skip):
            dirs[:] = []
            continue
        for name in names:
            path = os.path.join(root, name)
            try:
                if os.path.islink(path) or os.path.getsize(path) > 1_000_000:
                    continue
                with open(path, "rb") as handle:
                    blob = handle.read()
            except OSError:
                continue
            if b"base_seed" in blob or b"journal.jsonl" in blob or b"obs_before_sha256" in blob:
                hits.append(path)
    record("files_mentioning_seed_or_journal", hits)
    procs = []
    for pid in os.listdir("/proc"):
        if pid.isdigit():
            try:
                procs.append(Path(f"/proc/{pid}/cmdline").read_bytes().replace(b"\0", b" ").decode()[:120])
            except OSError:
                pass
    record("simulator_process_visible", any("f1sim" in p for p in procs))


def protocol_attacks():
    record("reset", req({"cmd": "reset"}))
    record("rewind", req({"cmd": "rewind", "to": "d001"}))
    record("seed", req({"cmd": "seed"}))
    record("observe_with_seed_field", req({"cmd": "observe", "seed": 1}))
    record("malformed_json", raw(b"{not json\n"))
    record("binary", raw(b"\xff\xfe\x00\n"))
    record("oversized", raw(b'{"cmd":"observe","pad":"' + b"x" * 1_000_000 + b'"}\n'))
    obs = req({"cmd": "observe"})["observation"]
    record("first_decision_id", obs["decision_id"])
    record("observation_keys", sorted(obs))
    record("wrong_phase_action", req({"cmd": "act", "decision_id": obs["decision_id"],
                                      "action": {"type": "RACE_STRATEGY", "driver_a": "PIT", "driver_b": "PIT"}}))
    record("future_decision_id", req({"cmd": "act", "decision_id": "d999", "action": component_action(obs)}))
    record("int_decision_id", req({"cmd": "act", "decision_id": 1, "action": component_action(obs)}))
    record("missing_decision_id", req({"cmd": "act", "action": component_action(obs)}))
    first = req({"cmd": "act", "decision_id": obs["decision_id"], "action": component_action(obs)})
    record("valid_first_action_ok", first.get("ok"))
    record("duplicate_first_action", req({"cmd": "act", "decision_id": obs["decision_id"],
                                          "action": component_action(obs)}))
    obs = first["observation"]
    action = race_action(obs)
    outcomes = []

    def fire():
        outcomes.append(req({"cmd": "act", "decision_id": obs["decision_id"], "action": action}))

    threads = [threading.Thread(target=fire) for _ in range(20)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    record("concurrent_same_decision", {"accepted": sum(1 for o in outcomes if o.get("ok")),
                                        "rejected_codes": sorted({o.get("error_code") for o in outcomes
                                                                  if not o.get("ok")})})


def forge_files():
    forged = {}
    for path, text in (("/logs/verifier/reward.txt", "1.0\n"),
                       ("/evidence/f1sim/journal.jsonl", "{}\n"),
                       ("/evidence/f1sim/manifest.json", "{}\n"),
                       ("/logs/artifacts/evidence/f1sim/manifest.json", "{}\n"),
                       ("/app/submission/actions.json", "{}\n")):
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            Path(path).write_text(text)
            forged[path] = "written"
        except OSError as exc:
            forged[path] = f"refused: {exc.__class__.__name__}"
    record("forged_files", forged)


def finish():
    obs = req({"cmd": "observe"})["observation"]
    while obs["decision_type"] != "CHAMPIONSHIP_COMPLETE":
        action = component_action(obs) if obs["decision_type"] == "COMPONENT_DECISION" else race_action(obs)
        response = req({"cmd": "act", "decision_id": obs["decision_id"], "action": action})
        obs = response["observation"]
    record("finished_standings", obs["championship"]["team_standings"])
    record("act_after_complete", req({"cmd": "act", "decision_id": "d033",
                                      "action": {"type": "RACE_STRATEGY", "driver_a": "STAY",
                                                 "driver_b": "STAY"}}))


def sabotage():
    try:
        os.unlink(SOCK)
        record("socket_deleted", True)
    except OSError as exc:
        record("socket_deleted", f"refused: {exc.__class__.__name__}")


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "complete"
    record("uid", os.getuid())
    scan_filesystem()
    protocol_attacks()
    forge_files()
    finish() if mode == "complete" else sabotage()
    try:
        os.makedirs("/logs/agent", exist_ok=True)
        Path("/logs/agent/probe_results.json").write_text(json.dumps(RESULTS, indent=2))
    except OSError:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
