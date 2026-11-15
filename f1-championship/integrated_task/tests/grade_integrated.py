#!/usr/bin/env python3
"""Trusted verifier for the integrated SOLO_COORDINATION task (benchmark 2.0.x).

Reads only sidecar evidence (journal v2 + Engineer record store + manifest) and the hidden seed
in this image. Integrity: manifest hashes, journal hash chain, and a full replay from the seed
that re-supplies the exact recorded Engineer reports and recomputes every observation hash.

Scalar `b6-integrated-p0` (same form as the 1.1.0 p0 scalar, separate version):
  reward = 0 if not complete or not intact, else clip((P - D) / (U - D), 0, 1)
  P = Apex points, D = published-fallback policy (USE when legal / STAY / team order RACE) on the
  same seed in the same mode, U = 43 points per race. Commitment compliance, team-order use and
  Engineer consumption are REPORTED, never added to the reward (no artificial points).
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from f1pitwall import engine  # noqa: E402
from f1pitwall.integrated import config as C  # noqa: E402
from f1pitwall.integrated import verify as V  # noqa: E402
from f1pitwall.integrated.engineers import EngineerBroker  # noqa: E402
from f1pitwall.integrated.session import CHAMPIONSHIP_COMPLETE, IntegratedSession  # noqa: E402

EVIDENCE_DIR = Path(os.environ.get("F1_EVIDENCE_DIR", "/evidence/f1sim"))
SEED_PATH = Path(os.environ.get("F1_SEED_PATH", str(Path(__file__).resolve().parent / "hidden_seed.json")))
MODE_PATH = Path(os.environ.get("F1_MODE_PATH", str(Path(__file__).resolve().parent / "mode.json")))
REWARD = Path(os.environ.get("F1_REWARD_PATH", "/logs/verifier/reward.txt"))
REPORT = Path(os.environ.get("F1_REPORT_PATH", "/logs/verifier/report.json"))
SCALAR_VERSION = "b6-integrated-p0"


def fallback_points(config, seed):
    session = IntegratedSession(config, seed)
    while session.decision_type != CHAMPIONSHIP_COMPLETE:
        session.close_tick(session.tick_id)
    return session.state.team_points["Apex"]


def grade():
    report = {"benchmark_version": None, "scalar_version": SCALAR_VERSION,
              "completion": {"complete": False}, "integrity": {"intact": False, "error": None}, "reward": 0.0}
    journal_path, manifest_path = EVIDENCE_DIR / "journal.jsonl", EVIDENCE_DIR / "manifest.json"
    if not journal_path.is_file() or not manifest_path.is_file():
        report["integrity"]["error"] = "missing sidecar evidence"
        return report
    raw = journal_path.read_bytes()
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    mode = json.loads(MODE_PATH.read_text(encoding="utf-8"))
    mode.setdefault("benchmark_version", C.INTEGRATED_VERSION)
    config = C.with_features(
        C.with_version(C.solo_coordination(engineers=mode["engineers"], chief={"provider": "harbor_agent"}),
                       mode["benchmark_version"]), mode)
    if mode.get("c5_weekend"):
        config = C.with_c5_weekend(config)
    seed = json.loads(SEED_PATH.read_text(encoding="utf-8"))["base_seed"]
    report["benchmark_version"] = config.benchmark_version
    if manifest.get("benchmark_version") != config.benchmark_version:
        report["integrity"]["error"] = "evidence version differs from the task version"
        return report
    try:
        if manifest.get("journal_sha256") != hashlib.sha256(raw).hexdigest():
            raise V.ReplayError("journal does not match sealed manifest")
        for rel, digest in manifest.get("engineer_record_files", {}).items():
            if hashlib.sha256((EVIDENCE_DIR / rel).read_bytes()).hexdigest() != digest:
                raise V.ReplayError("Engineer record store does not match sealed manifest")
        entries = [json.loads(x) for x in raw.decode("utf-8").splitlines() if x]
        if manifest.get("journal_entries") != len(entries):
            raise V.ReplayError("journal entry count does not match manifest")
        broker = EngineerBroker.replaying(EVIDENCE_DIR / "engineers") if mode["engineers"] != "CHIEF_ONLY" else None
        result = V.replay(config, seed, entries, engineer_broker=broker, require_complete=False)
    except Exception as exc:  # integrity failure of any kind -> 0
        report["integrity"]["error"] = f"{type(exc).__name__}: {exc}"
        return report
    session = result["session"]
    report["integrity"] = {"intact": True, "error": None,
                           "rejected_requests_logged": sum(1 for e in entries if e["kind"] == "rejected")}
    report["completion"] = {"complete": result["complete"], "resolved_ticks": result["resolved_ticks"],
                            "races_completed": session.state.race_index}
    points = session.state.team_points["Apex"]
    orders, commitments, reports = Counter(), Counter(), {"delivered": 0, "referenced": 0}
    for rr in session.race_results:
        team = rr["team_orders"]["Apex"]
        for r in team["order_log"]:
            orders[f"{r['order']}:{r['status']}"] += 1
        for c in ([team["commitment"]] if team["commitment"] else []) + team["closed_commitments"]:
            commitments[c["status"]] += 1
    for e in entries:
        if e["kind"] == "resolved":
            delivered = e["engineer_record_hashes"].get("Apex", [])
            reports["delivered"] += len(delivered)
            used = e["submissions"]["Apex"]["action"].get("consumed_reports", [])
            reports["referenced"] += len(set(used) & set(delivered))
    report["performance"] = {"apex_constructors_points": points, "team_points": session.standings()["team_points"],
                             "team_orders": dict(orders), "commitment_outcomes": dict(commitments),
                             "engineer_reports": reports,
                             "note": "orders, commitments and report use are diagnostics, not part of the reward"}
    nothing = fallback_points(config, seed)
    upper = (engine.POINTS[0] + engine.POINTS[1]) * len(session.state.calendar)
    report["normalization"] = {"formula": "complete and intact ? clip((P - D) / (U - D), 0, 1) : 0",
                               "P": points, "D_fallback_same_seed": nothing, "U": upper}
    if result["complete"] and upper > nothing:
        value = min(1.0, max(0.0, (points - nothing) / (upper - nothing)))
        if math.isfinite(value):
            report["reward"] = value
    return report


def main():
    try:
        report = grade()
    except Exception as exc:
        report = {"reward": 0.0, "integrity": {"intact": False, "error": f"verifier error: {type(exc).__name__}"}}
    REWARD.parent.mkdir(parents=True, exist_ok=True)
    REWARD.write_text(f"{report['reward']:.8f}\n", encoding="utf-8")
    REPORT.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
