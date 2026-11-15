#!/usr/bin/env python3
"""Audit the C6 historical reversal count against C7's corrected evidence classes."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

TASK = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(TASK / "src"), str(TASK), str(TASK / "analysis")]

from c6_adaptive_probes import build_rows  # noqa: E402

SEEDS = [400, 401, 402, 403]
FUTURES = 4
NEAR_TIE_THRESHOLD = 0.5


def raw_reversal(row):
    pair = row["pair"]
    return pair["condition_a"]["reference_action"] != pair["condition_b"]["reference_action"]


def uncertainty_separated(row):
    pair = row["pair"]
    return min(pair["condition_a"]["reference_gap"], pair["condition_b"]["reference_gap"]) > NEAR_TIE_THRESHOLD


def historical_c6_class(row):
    """The original report ordering: reversal before the classifier's near-tie result."""
    if raw_reversal(row):
        return "REPORTED_REVERSAL"
    if not uncertainty_separated(row):
        return "REPORTED_NEAR_TIE"
    return "REPORTED_NO_CHANGE_CONTROL"


def validated_class(row):
    """Mutually exclusive evidence ordering used for claims."""
    if not uncertainty_separated(row):
        return "NEAR_TIE"
    return "VALIDATED_REVERSAL" if raw_reversal(row) else "NO_CHANGE_CONTROL"


def observation_pair(row):
    evidence = row["pair"]["public_evidence_diff"]
    return evidence["baseline_observation_hash"], evidence["altered_observation_hash"]


def count_unique(rows, classifier):
    buckets = defaultdict(set)
    for row in rows:
        buckets[classifier(row)].add(observation_pair(row))
    return {key: len(value) for key, value in sorted(buckets.items())}


def reconcile(rows, sampled_states):
    cross = Counter(("RAW_REVERSAL" if raw_reversal(row) else "RAW_STABLE",
                     "SEPARATED" if uncertainty_separated(row) else "NEAR_TIE") for row in rows)
    historical = Counter(historical_c6_class(row) for row in rows)
    validated = Counter(validated_class(row) for row in rows)
    all_unique = {observation_pair(row) for row in rows}
    return {
        "schema_version": 1,
        "generator": {"seeds": SEEDS, "futures": FUTURES,
                      "near_tie_threshold_points": NEAR_TIE_THRESHOLD,
                      "sampling_row": "one state x named rival-policy variant",
                      "unique_unit": "ordered baseline/altered public-observation hash pair"},
        "sampled_pre_action_states": sampled_states,
        "eligible_rows": len(rows),
        "unique_public_observation_pairs_overall": len(all_unique),
        "cross_table_rows": {f"{raw}|{gate}": count for (raw, gate), count in sorted(cross.items())},
        "historical_c6_row_counts": dict(historical),
        "historical_c6_unique_pair_counts": count_unique(rows, historical_c6_class),
        "validated_row_counts": dict(validated),
        "validated_unique_pair_counts": count_unique(rows, validated_class),
        "near_tie_precedence_effect": {
            "raw_reversals_reclassified_as_near_tie": cross[("RAW_REVERSAL", "NEAR_TIE")],
            "reported_reversals_before_gate": historical["REPORTED_REVERSAL"],
            "validated_reversals_after_gate": validated["VALIDATED_REVERSAL"],
        },
        "definitions": {
            "raw_action_reversal": "condition_a.reference_action != condition_b.reference_action",
            "uncertainty_separated": "both reference_gap lower bounds are > 0.5 points",
            "near_tie": "at least one reference_gap lower bound is <= 0.5 points",
            "validated_reversal": "raw action reversal AND uncertainty separated",
            "historical_c6_order": "raw reversal first; near tie only among raw-stable rows",
            "validated_order": "near-tie uncertainty gate first; reversal/no-change second",
        },
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    rows, sampled_states = build_rows(SEEDS, FUTURES)
    output = reconcile(rows, sampled_states)
    payload = json.dumps(output, indent=2, sort_keys=True, allow_nan=False) + "\n"
    Path(args.output).write_text(payload)
    print(json.dumps({"sha256": hashlib.sha256(payload.encode()).hexdigest(),
                      "eligible_rows": output["eligible_rows"],
                      "cross_table_rows": output["cross_table_rows"]}, sort_keys=True))


if __name__ == "__main__":
    main()
