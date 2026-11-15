#!/usr/bin/env python3
"""Freeze a model-independent C7 selection from the checked-in C6 probe artifact."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path

COUNTS = {"REVERSAL": 5, "NO_CHANGE_CONTROL": 5, "NEAR_TIE": 3}
SELECTION_VERSION = "c7-selection-v1"


def row_class(row):
    if row["reference_classification"] == "NEAR_TIE":
        return "NEAR_TIE"
    if row["reference_reversal"]:
        return "REVERSAL"
    return "NO_CHANGE_CONTROL"


def rank_key(kind, row):
    value = f"{SELECTION_VERSION}|{kind}|{row['pair']['pair_id']}".encode()
    return hashlib.sha256(value).hexdigest(), row["pair"]["pair_id"]


def select(artifact):
    selected = []
    used_observations = set()
    for kind, count in COUNTS.items():
        candidates = [row for row in artifact["targeted_probes"] if row_class(row) == kind]
        if len(candidates) < count:
            raise ValueError(f"not enough {kind} candidates")
        chosen = []
        for row in sorted(candidates, key=lambda row: rank_key(kind, row)):
            evidence = row["pair"]["public_evidence_diff"]
            hashes = {evidence["baseline_observation_hash"], evidence["altered_observation_hash"]}
            if hashes & used_observations:
                continue
            chosen.append(row)
            used_observations.update(hashes)
            if len(chosen) == count:
                break
        if len(chosen) != count:
            raise ValueError(f"not enough unique-observation {kind} candidates")
        selected.extend(chosen)
    return selected


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("source")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    source_path = Path(args.source)
    source_bytes = source_path.read_bytes()
    artifact = json.loads(source_bytes)
    chosen = select(artifact)
    output = {
        "schema_version": 1,
        "selection_version": SELECTION_VERSION,
        "source_sha256": hashlib.sha256(source_bytes).hexdigest(),
        "criteria": ("in class order reversal/no-change/near-tie, sort frozen C6 candidates by "
                     "sha256(c7-selection-v1|class|pair_id), greedily exclude any observation hash "
                     "already selected, then take 5/5/3; no model output used"),
        "counts": dict(Counter(row_class(row) for row in chosen)),
        "pairs": [{"pair_id": row["pair"]["pair_id"], "reference_class": row_class(row),
                   "probe_category": row["probe_category"],
                   "baseline_observation_hash": row["pair"]["public_evidence_diff"]["baseline_observation_hash"],
                   "altered_observation_hash": row["pair"]["public_evidence_diff"]["altered_observation_hash"]}
                  for row in chosen],
    }
    Path(args.output).write_text(json.dumps(output, indent=2, sort_keys=True, allow_nan=False) + "\n")
    print(json.dumps({"counts": output["counts"], "source_sha256": output["source_sha256"]}, sort_keys=True))


if __name__ == "__main__":
    main()
