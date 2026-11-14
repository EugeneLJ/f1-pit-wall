#!/usr/bin/env python3
"""Trusted sequential verifier; agent-visible code and claimed scores are ignored."""

from __future__ import annotations

import json
import math
import os
from pathlib import Path
from typing import Any

from trusted_engine import parse_submission, replay

SUBMISSION = Path(os.environ.get("F1_SUBMISSION_PATH", "/app/submission/actions.json"))
REWARD = Path(os.environ.get("F1_REWARD_PATH", "/logs/verifier/reward.txt"))
REPORT = Path(os.environ.get("F1_REPORT_PATH", "/logs/verifier/report.json"))
LOW_ANCHOR = 10
HIGH_ANCHOR = 23


def trusted_score(actions: list[dict[str, str]]) -> tuple[float, dict[str, Any]]:
    outcome = replay(actions)
    points = outcome["constructors_points"]
    reward = min(1.0, max(0.0, (points - LOW_ANCHOR) / (HIGH_ANCHOR - LOW_ANCHOR)))
    if not math.isfinite(reward):
        raise ValueError("non-finite reward")
    apex = [entry for entry in outcome["classification"] if entry["team"] == "Apex"]
    return reward, {"valid": True, "actions": actions, "seed": outcome["seed"],
                    "event_history": outcome["events"], "constructors_points": points,
                    "apex_classification": apex, "low_anchor": LOW_ANCHOR,
                    "high_anchor": HIGH_ANCHOR, "reward": reward}


def write_outputs(reward: float, report: dict[str, Any]) -> None:
    REWARD.parent.mkdir(parents=True, exist_ok=True)
    REWARD.write_text(f"{reward:.8f}\n", encoding="utf-8")
    REPORT.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main() -> int:
    reward = 0.0
    report: dict[str, Any] = {"valid": False, "reward": 0.0}
    exit_code = 1
    try:
        actions = parse_submission(json.loads(SUBMISSION.read_text(encoding="utf-8")))
        reward, report = trusted_score(actions)
        exit_code = 0
    except Exception as exc:
        report["error"] = f"{type(exc).__name__}: {exc}"
    try:
        write_outputs(reward, report)
    except Exception:
        return 1
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
