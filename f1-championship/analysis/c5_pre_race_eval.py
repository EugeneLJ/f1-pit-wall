#!/usr/bin/env python3
"""Evaluate the agent-independent C5 Practice/Qualifying scenario fixture."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

TASK = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(TASK / "src"), str(TASK)]

from track_c.pre_race_evaluation import paired_reversal, practice_test_information_value  # noqa: E402
from track_c.pre_race_planning import PreRaceConfig, PreRaceSession  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--fixture", default=str(TASK / "track_c/fixtures/pre_race_scenarios.json"))
    parser.add_argument("--output")
    args = parser.parse_args()
    fixture = json.loads(Path(args.fixture).read_text(encoding="utf-8"))
    rows = []
    for item in fixture["scenarios"]:
        config = PreRaceConfig(item["track_archetype"])
        result = paired_reversal(config, item["trusted_seed"], item["test_action"])
        if result["control_or_reversal"] != item["expected_class"]:
            raise ValueError(f"fixture classification drift: {item['id']}")
        initial = PreRaceSession(config, item["trusted_seed"]).observation()
        value = practice_test_information_value(initial, item["test_action"]["test"],
                                                item["test_action"].get("driver"))
        rows.append({"id": item["id"], **result, "information_value": value})
    summary = {"schema_version": 1, "result_kind": "SYNTHETIC_SCRIPTED_EVALUATION",
               "actual_model_results": False, "data_status": fixture["data_status"],
               "scenario_count": len(rows),
               "reversals": sum(row["reversal"] for row in rows),
               "no_change_controls": sum(not row["reversal"] for row in rows), "scenarios": rows}
    text = json.dumps(summary, indent=2, sort_keys=True, allow_nan=False) + "\n"
    if args.output:
        Path(args.output).write_text(text, encoding="utf-8")
    else:
        print(text, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
