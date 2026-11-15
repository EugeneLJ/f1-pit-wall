#!/usr/bin/env python3
"""Execute the preregistered ten-seed C7 adaptive-rival revalidation."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

TASK = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(TASK / "src"), str(TASK), str(TASK / "analysis")]

from c6_adaptive_probes import build_rows  # noqa: E402
from c7_reconcile_counts import observation_pair, validated_class  # noqa: E402

SELECTION_SALT = "c7-adaptive-expansion-v1"


def aggregate(rows):
    row_counts = Counter(validated_class(row) for row in rows)
    unique_by_class = defaultdict(set)
    classes_by_pair = defaultdict(set)
    for row in rows:
        key = observation_pair(row)
        kind = validated_class(row)
        unique_by_class[kind].add(key)
        classes_by_pair[key].add(kind)
    return {
        "row_counts": dict(row_counts),
        "unique_pair_counts": {key: len(value) for key, value in sorted(unique_by_class.items())},
        "unique_pairs_overall": len(classes_by_pair),
        "pairs_with_conflicting_reference_classes": sum(len(value) > 1 for value in classes_by_pair.values()),
    }


def evidence_index(rows):
    output = []
    for row in sorted(rows, key=lambda value: value["pair"]["pair_id"]):
        pair = row["pair"]
        output.append({
            "pair_id": pair["pair_id"],
            "class": validated_class(row),
            "baseline_observation_hash": pair["public_evidence_diff"]["baseline_observation_hash"],
            "altered_observation_hash": pair["public_evidence_diff"]["altered_observation_hash"],
            "condition_a_reference_action": pair["condition_a"]["reference_action"],
            "condition_b_reference_action": pair["condition_b"]["reference_action"],
            "condition_a_reference_gap": pair["condition_a"]["reference_gap"],
            "condition_b_reference_gap": pair["condition_b"]["reference_gap"],
        })
    return output


def select_live(rows, requested):
    chosen, used_observation_hashes = [], set()
    for kind in ("VALIDATED_REVERSAL", "NO_CHANGE_CONTROL", "NEAR_TIE"):
        candidates = sorted((row for row in rows if validated_class(row) == kind),
                            key=lambda row: hashlib.sha256(
                                f"{SELECTION_SALT}|{kind}|{row['pair']['pair_id']}".encode()).hexdigest())
        bucket = []
        for row in candidates:
            a, b = observation_pair(row)
            if {a, b} & used_observation_hashes:
                continue
            bucket.append(row)
            used_observation_hashes.update((a, b))
            if len(bucket) == requested[kind]:
                break
        if len(bucket) != requested[kind]:
            return [], f"only {len(bucket)} disjoint-prompt {kind} candidates"
        chosen.extend(bucket)
    return chosen, None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--prereg", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--candidates-output", required=True)
    args = parser.parse_args()
    prereg_path = Path(args.prereg)
    prereg_bytes = prereg_path.read_bytes()
    prereg = json.loads(prereg_bytes)
    settings = prereg["generator"]
    started = time.monotonic()
    rows, sampled = build_rows(settings["seeds"], settings["common_futures_per_condition"])
    runtime = round(time.monotonic() - started, 3)
    counts = aggregate(rows)
    validated_unique = counts["unique_pair_counts"].get("VALIDATED_REVERSAL", 0)
    go = validated_unique >= 3
    requested = prereg["conditional_live_pilot"]["pairs"]
    selected, selection_blocker = select_live(rows, requested) if go else ([], "fewer than 3 unique reversals")
    go = go and selection_blocker is None
    index = evidence_index(rows)
    output = {
        "schema_version": 1,
        "prereg_sha256": hashlib.sha256(prereg_bytes).hexdigest(),
        "preregistered_seeds": settings["seeds"],
        "common_futures_per_condition": settings["common_futures_per_condition"],
        "near_tie_threshold_points": settings["near_tie_threshold_points"],
        "runtime_seconds": runtime,
        "sampled_pre_action_states": sampled,
        "eligible_rows": len(rows),
        **counts,
        "go_no_go": "GO" if go else "NO_GO",
        "selection_blocker": selection_blocker,
        "live_calls_made": 0,
        "evidence_index_sha256": hashlib.sha256(
            json.dumps(index, sort_keys=True, separators=(",", ":")).encode()).hexdigest(),
        "evidence_index": index,
    }
    Path(args.output).write_text(json.dumps(output, indent=2, sort_keys=True, allow_nan=False) + "\n")
    candidate_output = {
        "schema_version": 1,
        "source_result_sha256": hashlib.sha256(Path(args.output).read_bytes()).hexdigest(),
        "selection_salt": SELECTION_SALT,
        "targeted_probe_count": len(selected),
        "targeted_probes": selected,
        "actual_model_results": False,
        "selection_blocker": selection_blocker,
    }
    Path(args.candidates_output).write_text(
        json.dumps(candidate_output, indent=2, sort_keys=True, allow_nan=False) + "\n")
    print(json.dumps({"go_no_go": output["go_no_go"], "runtime_seconds": runtime,
                      "row_counts": counts["row_counts"],
                      "unique_pair_counts": counts["unique_pair_counts"],
                      "selected": len(selected), "blocker": selection_blocker}, sort_keys=True))


if __name__ == "__main__":
    main()
