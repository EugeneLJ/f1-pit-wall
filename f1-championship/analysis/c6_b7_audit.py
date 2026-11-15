#!/usr/bin/env python3
"""Verify frozen B7 evidence and report what adaptive/Engineer claims it supports."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import Counter
from pathlib import Path

TASK = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(TASK / "src"), str(TASK)]

from track_c.adaptive_rival_evaluation import audit_bundle_visibility, load_verified_bundle  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("b7_dir")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    root = Path(args.b7_dir)
    bundles = {layer: load_verified_bundle(root / layer / "c4_bundle.json.gz")
               for layer in ("layer1", "layer2")}
    visibility = {layer: audit_bundle_visibility(bundle, "McLearn Racing", "Red Bool Racing")
                  for layer, bundle in bundles.items()}
    c4 = json.loads((root / "c4_report.json").read_text(encoding="utf-8"))
    l2 = c4["layer_2"]
    confirmed = [decision for decision in l2["decisions"] if decision["strategic_failures"]]
    labels = Counter(failure["label"] for decision in confirmed for failure in decision["strategic_failures"])
    cases = []
    for decision in confirmed[:5]:
        source = next(d for d in bundles["layer2"]["decisions"]
                      if d["tick_id"] == decision["tick_id"] and d["team"] == decision["team"])
        payload = json.dumps(source["chief_observation"], sort_keys=True, separators=(",", ":"), allow_nan=False)
        cases.append({"tick_id": decision["tick_id"], "team": decision["team"],
                      "observation_hash": hashlib.sha256(payload.encode()).hexdigest(),
                      "regret": decision["regret"], "labels": decision["strategic_failures"],
                      "engineer_usage": decision["engineer_usage"],
                      "information_value": decision["information_value"]})
    output = {
        "schema_version": 1, "source": "frozen B7 f9b47c4", "integrity": "C4_BUNDLES_VERIFIED",
        "adaptive_rival": {
            "visibility": {layer: {k: v for k, v in report.items() if k != "rows"}
                           for layer, report in visibility.items()},
            "paired_chief_responses_available": False,
            "classification": "INSUFFICIENT_EVIDENCE",
            "reason": ("B7 contains one adaptive trajectory per layer, not matched Gemini decisions under "
                       "baseline and altered visible rival evidence"),
            "gemini_deepseek_scores_are_official_gap": False,
        },
        "engineer_coordination": {
            "confirmed_decisions": len(confirmed), "failure_labels": dict(labels),
            "case_studies": cases,
            "causal_claim": "NOT_SUPPORTED_BY_UNMATCHED_LAYER_1_LAYER_2_SEASONS",
            "evidence_scope": "C4 equal-information decision regret and sealed report provenance",
        },
    }
    Path(args.output).write_text(json.dumps(output, indent=2, sort_keys=True, allow_nan=False) + "\n")
    print(json.dumps({"confirmed_engineer_cases": len(confirmed),
                      "adaptive_classification": output["adaptive_rival"]["classification"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
