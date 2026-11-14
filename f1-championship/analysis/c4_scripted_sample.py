#!/usr/bin/env python3
"""Create matched, explicitly SCRIPTED C4 sample bundles (never model results)."""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path

TASK = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(TASK / "src"), str(TASK)]

from f1pitwall.integrated import config as C  # noqa: E402
from f1pitwall.integrated import match as M  # noqa: E402
from f1pitwall.integrated import policies as P  # noqa: E402
from f1pitwall.integrated.engineers import EngineerBroker  # noqa: E402
from track_c.coordination_evaluation import build_bundle_from_run, compare_layers  # noqa: E402
from track_c.engineer_runtime import ImmutableRecommendationStore  # noqa: E402


def _run(layer: int, seed: int, root: Path):
    config = C.two_team(layer, mclearn_engineers=("CHIEF_ONLY" if layer == 1 else "MOCK_ENGINEERS"))
    captures = []
    broker = EngineerBroker(root) if layer == 2 else None
    run = M.run_season(config, seed,
                       {"McLearn Racing": P.scripted("coordinator"),
                        "Red Bool Racing": P.scripted("baseline")},
                       engineer_broker=broker, observer=lambda value: captures.append(value))
    records = {}
    if layer == 2:
        path = root / "mclearn_racing" / "engineer_records.jsonl"
        records["McLearn Racing"] = ImmutableRecommendationStore(path).read_all()
    slots = {team.label: team.slot for team in config.teams}
    return build_bundle_from_run(run=run, observations=captures, layer=f"LAYER_{layer}",
                                 result_kind="SCRIPTED_CONTROL", slot_assignment=slots,
                                 engineer_records=records, run_id=f"c4-scripted-layer-{layer}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--seed", type=int, default=20261114)
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args()
    output = Path(args.output_dir)
    output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="c4-records-") as tmp:
        layer1 = _run(1, args.seed, Path(tmp) / "l1")
        layer2 = _run(2, args.seed, Path(tmp) / "l2")
    (output / "layer1.json").write_text(json.dumps(layer1, indent=2, sort_keys=True) + "\n")
    (output / "layer2.json").write_text(json.dumps(layer2, indent=2, sort_keys=True) + "\n")
    report = compare_layers(layer1, layer2)
    (output / "comparison.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"result_kind": "SCRIPTED_CONTROL", "output_dir": str(output),
                      "team_points_change": report["team_points_change"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
