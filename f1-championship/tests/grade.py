#!/usr/bin/env python3
"""Trusted championship verifier (P0).

Inputs are only the sidecar evidence that Harbor collected from the sim
service's private filesystem, plus the hidden seed shipped in this verifier
image. Nothing written by the agent container is read.

The report keeps three things separate:
  completion  - did the championship reach CHAMPIONSHIP_COMPLETE?
  integrity   - does the evidence hash-chain and replay exactly from the seed?
  performance - raw constructors' points, rank, and baselines on the same seed.

P0 scalar (provisional until P2 adds the reference planner):
  reward = 0                                   if not complete or not intact
  reward = clip((P - D) / (U - D), 0, 1)       otherwise
where P = Apex points, D = do-nothing policy (USE whenever legal, all STAY) on the same
hidden seed, U = theoretical maximum (P1 + P2 = 43 points in every race).
U is a true upper bound, not a reference score. Points only accumulate, so
stopping early can never beat finishing; an unfinished season scores 0.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import sys
from pathlib import Path
from typing import Any, Dict

sys.path.insert(0, str(Path(__file__).resolve().parent))

from f1pitwall import engine  # noqa: E402
from f1pitwall.championship_contract import (  # noqa: E402
    COMPONENT_DECISION,
    RACE_STRATEGY,
    ChampionshipSession,
)
from f1pitwall.journal import JournalError, parse_journal, replay  # noqa: E402

EVIDENCE_DIR = Path(os.environ.get("F1_EVIDENCE_DIR", "/evidence/f1sim"))
SEED_PATH = Path(os.environ.get("F1_SEED_PATH", str(Path(__file__).resolve().parent / "hidden_seed.json")))
REWARD = Path(os.environ.get("F1_REWARD_PATH", "/logs/verifier/reward.txt"))
REPORT = Path(os.environ.get("F1_REPORT_PATH", "/logs/verifier/report.json"))
SCALAR_VERSION = "p0-provisional"


def load_seed() -> int:
    value = json.loads(SEED_PATH.read_text(encoding="utf-8"))
    seed = value["base_seed"]
    if isinstance(seed, bool) or not isinstance(seed, int):
        raise ValueError("invalid hidden seed")
    return seed


def do_nothing_points(base_seed: int) -> int:
    session = ChampionshipSession(base_seed=base_seed)
    while session.decision_type != "CHAMPIONSHIP_COMPLETE":
        obs = session.observation()
        if session.decision_type == COMPONENT_DECISION:
            decisions = [{"driver": d, "component": c,
                          "action": "USE" if "USE" in info["legal_actions"] else "REPLACE"}
                         for d, state in obs["controlled_drivers"].items()
                         for c, info in state["components"].items()]
            session.submit({"type": COMPONENT_DECISION, "decisions": decisions})
        else:
            session.submit({"type": RACE_STRATEGY, "driver_a": "STAY", "driver_b": "STAY"})
    return session.state.team_points["Apex"]


def timing(entries) -> Dict[str, Any]:
    accepted = [e for e in entries if e["kind"] == "accepted"]
    if not accepted:
        return {"accepted_decisions": 0}
    gaps = [b["t_received"] - a["t_done"] for a, b in zip(accepted, accepted[1:])]
    return {
        "accepted_decisions": len(accepted),
        "first_decision_at": accepted[0]["t_received"],
        "last_decision_at": accepted[-1]["t_done"],
        "decision_span_sec": round(accepted[-1]["t_done"] - accepted[0]["t_received"], 3),
        "mean_gap_between_decisions_sec": round(sum(gaps) / len(gaps), 3) if gaps else None,
        "max_gap_between_decisions_sec": round(max(gaps), 3) if gaps else None,
        "max_server_latency_sec": round(max(e["t_done"] - e["t_received"] for e in entries), 6),
    }


def grade() -> Dict[str, Any]:
    report: Dict[str, Any] = {
        "scalar_version": SCALAR_VERSION,
        "completion": {"complete": False, "accepted_decisions": 0, "races_completed": 0},
        "integrity": {"intact": False, "error": None},
        "performance": None,
        "normalization": None,
        "reward": 0.0,
    }
    journal_path = EVIDENCE_DIR / "journal.jsonl"
    manifest_path = EVIDENCE_DIR / "manifest.json"
    if not journal_path.is_file() or not manifest_path.is_file():
        report["integrity"]["error"] = "missing sidecar evidence"
        return report

    raw = journal_path.read_bytes()
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    report["evidence"] = {"manifest": manifest, "journal_sha256": hashlib.sha256(raw).hexdigest()}
    try:
        if manifest.get("journal_sha256") != hashlib.sha256(raw).hexdigest():
            raise JournalError("journal does not match sealed manifest")
        entries = parse_journal(raw.decode("utf-8"))
        if manifest.get("journal_entries") != len(entries):
            raise JournalError("journal entry count does not match manifest")
        base_seed = load_seed()
        result = replay(entries, base_seed)
        if manifest.get("head_hash") != result["head_hash"]:
            raise JournalError("journal head does not match manifest")
    except (JournalError, ValueError, KeyError, UnicodeDecodeError) as exc:
        report["integrity"]["error"] = f"{type(exc).__name__}: {exc}"
        return report

    session = result["session"]
    state = session.state
    report["integrity"] = {"intact": True, "error": None,
                           "rejected_requests_logged": result["rejected"],
                           "request_stats": manifest.get("request_stats", {})}
    report["completion"] = {"complete": result["complete"], "accepted_decisions": result["accepted"],
                            "races_completed": state.race_index, "races_total": len(state.calendar)}
    report["timing"] = timing(entries)

    points = state.team_points["Apex"]
    standings = sorted(state.team_points.items(), key=lambda item: (-item[1], item[0]))
    nothing = do_nothing_points(base_seed)
    upper = (engine.POINTS[0] + engine.POINTS[1]) * len(state.calendar)
    report["performance"] = {
        "apex_constructors_points": points,
        "apex_driver_points": {d: state.driver_points[d] for d in ("Apex A", "Apex B")},
        "championship_rank": [team for team, _ in standings].index("Apex") + 1,
        "margin_to_best_rival": points - max(p for t, p in state.team_points.items() if t != "Apex"),
        "team_points": dict(state.team_points),
        "reference_points": None,
        "regret_vs_reference": None,
    }
    report["normalization"] = {
        "formula": "complete and intact ? clip((P - D) / (U - D), 0, 1) : 0",
        "P_apex_points": points,
        "D_do_nothing_points_same_seed": nothing,
        "U_theoretical_max_points": upper,
        "note": "provisional P0 scale; P2 adds reference-relative regret without treating the reference as max",
    }
    if result["complete"] and upper > nothing:
        reward = min(1.0, max(0.0, (points - nothing) / (upper - nothing)))
        if math.isfinite(reward):
            report["reward"] = reward
    return report


def main() -> int:
    try:
        report = grade()
    except Exception as exc:  # any verifier failure is a zero, never a crash without a reward
        report = {"reward": 0.0, "integrity": {"intact": False, "error": f"verifier error: {type(exc).__name__}"}}
    REWARD.parent.mkdir(parents=True, exist_ok=True)
    REWARD.write_text(f"{report['reward']:.8f}\n", encoding="utf-8")
    REPORT.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
