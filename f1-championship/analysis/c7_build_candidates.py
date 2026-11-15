#!/usr/bin/env python3
"""Reproduce C6 held-out rows and freeze correctly separated C7 candidates.

C6's compact targeted artifact checked `reference_reversal` before `NEAR_TIE`, so
its ten stored reversal-labelled rows are near ties. This script does not change
the C6 classifier or mechanics. It reruns the exact checked-in C6 generator settings
and applies the corrected mutually exclusive class precedence before any live call.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

TASK = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(TASK / "src"), str(TASK), str(TASK / "analysis")]

from c6_adaptive_probes import build_rows  # noqa: E402
from c7_select_probes import COUNTS, SELECTION_VERSION, rank_key, row_class  # noqa: E402

SEEDS = [400, 401, 402, 403]
FUTURES = 4


def choose(rows):
    chosen, used = [], set()
    for kind, count in COUNTS.items():
        candidates = sorted((row for row in rows if row_class(row) == kind),
                            key=lambda row: rank_key(kind, row))
        bucket = []
        for row in candidates:
            evidence = row["pair"]["public_evidence_diff"]
            hashes = {evidence["baseline_observation_hash"], evidence["altered_observation_hash"]}
            if hashes & used:
                continue
            bucket.append(row)
            used.update(hashes)
            if len(bucket) == count:
                break
        if len(bucket) != count:
            raise RuntimeError(f"only {len(bucket)} unique {kind} candidates; refusing live run")
        chosen.extend(bucket)
    return chosen


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    rows, sampled = build_rows(SEEDS, FUTURES)
    census = Counter(row_class(row) for row in rows)
    unique_pairs = Counter()
    seen = {kind: set() for kind in COUNTS}
    for row in rows:
        kind = row_class(row)
        evidence = row["pair"]["public_evidence_diff"]
        key = (evidence["baseline_observation_hash"], evidence["altered_observation_hash"])
        if key not in seen[kind]:
            unique_pairs[kind] += 1
            seen[kind].add(key)
    blocker = None
    try:
        selected = choose(rows)
    except RuntimeError as exc:
        selected = []
        blocker = str(exc)
    output = {
        "schema_version": 1,
        "generator": {
            "parent": "C6 c6_adaptive_probes.build_rows",
            "seeds": SEEDS,
            "futures": FUTURES,
            "selection_version": SELECTION_VERSION,
            "class_precedence": "NEAR_TIE, then separated REVERSAL, else NO_CHANGE_CONTROL",
            "selection_independent_of_model_output": True,
        },
        "natural_sampled_pre_action_states": sampled,
        "eligible_visible_action_pairs": len(rows),
        "corrected_reference_classes": dict(census),
        "unique_public_observation_pairs": dict(unique_pairs),
        "targeted_probe_count": len(selected),
        "targeted_probes": selected,
        "actual_model_results": False,
        "live_calls_made": 0,
        "blocker": blocker,
    }
    Path(args.output).write_text(json.dumps(output, indent=2, sort_keys=True, allow_nan=False) + "\n")
    print(json.dumps({"eligible": len(rows), "classes": output["corrected_reference_classes"],
                      "unique_pairs": output["unique_public_observation_pairs"],
                      "selected": dict(Counter(row_class(row) for row in selected)),
                      "blocker": blocker}, sort_keys=True))
    if blocker:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
