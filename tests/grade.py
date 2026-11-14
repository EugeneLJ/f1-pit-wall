#!/usr/bin/env python3
"""Trusted verifier. It does not import or execute agent-visible code."""
from __future__ import annotations
import json
import math
import os
from pathlib import Path
from typing import Any

SUBMISSION = Path(os.environ.get("F1_SUBMISSION_PATH", "/app/submission/action.json"))
REWARD = Path(os.environ.get("F1_REWARD_PATH", "/logs/verifier/reward.txt"))
REPORT = Path(os.environ.get("F1_REPORT_PATH", "/logs/verifier/report.json"))
POINTS = (25, 18, 15, 12, 10, 8, 6, 4)
RIVAL_TIMES = (100.0, 102.0, 104.0, 106.0, 109.0, 112.0)
BASE = {"driver_a": 105.0, "driver_b": 108.0}
DELTAS = {
    "driver_a": {"PIT": -4.0, "STAY": 3.0},
    "driver_b": {"PIT": 5.0, "STAY": -3.0},
}
MAX_POINTS = 28


def parse_action(value: Any) -> dict[str, str]:
    if not isinstance(value, dict) or set(value) != {"driver_a", "driver_b"}:
        raise ValueError("submission must contain exactly driver_a and driver_b")
    for driver in ("driver_a", "driver_b"):
        if value[driver] not in ("PIT", "STAY"):
            raise ValueError(f"invalid action for {driver}")
    return value


def trusted_score(action: dict[str, str]) -> tuple[int, float, list[int]]:
    field = [(time, False) for time in RIVAL_TIMES]
    field.extend((BASE[d] + DELTAS[d][action[d]], True) for d in ("driver_a", "driver_b"))
    field.sort(key=lambda entry: entry[0])
    positions = [index + 1 for index, (_, is_apex) in enumerate(field) if is_apex]
    constructors_points = sum(POINTS[position - 1] for position in positions)
    reward = constructors_points / MAX_POINTS
    if not math.isfinite(reward):
        raise ValueError("non-finite reward")
    return constructors_points, min(1.0, max(0.0, reward)), positions


def write_outputs(reward: float, report: dict[str, Any]) -> None:
    REWARD.parent.mkdir(parents=True, exist_ok=True)
    REWARD.write_text(f"{reward:.8f}\n", encoding="utf-8")
    REPORT.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main() -> int:
    reward = 0.0
    report: dict[str, Any] = {"valid": False, "reward": 0.0}
    exit_code = 1
    try:
        action = parse_action(json.loads(SUBMISSION.read_text(encoding="utf-8")))
        points, reward, positions = trusted_score(action)
        report = {"valid": True, "action": action, "constructors_points": points,
                  "positions": positions, "reward": reward}
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
