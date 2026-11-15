#!/usr/bin/env python3
"""Evaluate completed C7 live records with the unchanged C6 classifier."""

from __future__ import annotations

import argparse
import hashlib
import json
import statistics
import sys
from collections import Counter
from pathlib import Path

TASK = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(TASK / "src"), str(TASK)]

from track_c.live_paired_probe import evaluate_live_pair  # noqa: E402


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--selection", required=True)
    parser.add_argument("--source", required=True)
    parser.add_argument("--records", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    selection = json.loads(Path(args.selection).read_text())
    source_bytes = Path(args.source).read_bytes()
    if hashlib.sha256(source_bytes).hexdigest() != selection["source_sha256"]:
        raise SystemExit("frozen source hash mismatch")
    artifact = json.loads(source_bytes)
    rows = {row["pair"]["pair_id"]: row for row in artifact["targeted_probes"]}
    records = [json.loads(line) for line in Path(args.records).read_text().splitlines() if line]
    grouped = {}
    for record in records:
        key = (record["pair_id"], record["condition"])
        if key in grouped:
            raise SystemExit(f"duplicate live record: {key}")
        grouped[key] = record
    results, missing = [], []
    for item in selection["pairs"]:
        pair_records = [grouped.get((item["pair_id"], condition)) for condition in ("a", "b")]
        if any(record is None for record in pair_records):
            missing.append(item["pair_id"])
            continue
        results.append(evaluate_live_pair(rows[item["pair_id"]], pair_records))
    calls = [grouped[key] for key in sorted(grouped)]
    latencies = [record["latency_ms"] for record in calls]
    usage_fields = ("input_tokens", "output_tokens", "thinking_tokens", "cached_input_tokens", "total_tokens")
    output = {
        "schema_version": 1,
        "experiment": "C7_LIVE_PAIRED_DIAGNOSTIC",
        "official_frontier_reference_gap": False,
        "selection_version": selection["selection_version"],
        "selection_criteria": selection["criteria"],
        "requested_model": calls[0]["requested_model"] if calls else None,
        "returned_models": dict(Counter(record["returned_model"] for record in calls)),
        "sampling": calls[0]["sampling"] if calls else None,
        "calls": len(calls),
        "valid_actions": sum(record["valid_action"] for record in calls),
        "usage": {field: sum((record["usage"].get(field) or 0) for record in calls) for field in usage_fields},
        "estimated_cost_usd": round(sum((record["estimated_cost"]["amount_usd"] or 0) for record in calls), 8),
        "latency_ms": {"mean": round(statistics.mean(latencies), 3) if latencies else None,
                       "p95": round(sorted(latencies)[max(0, int(len(latencies) * .95) - 1)], 3) if latencies else None},
        "classifications": dict(Counter(result["classification"] for result in results)),
        "completed_pairs": len(results),
        "missing_pairs": missing,
        "pair_results": results,
    }
    Path(args.output).write_text(json.dumps(output, indent=2, sort_keys=True, allow_nan=False) + "\n")
    print(json.dumps({key: output[key] for key in ("calls", "valid_actions", "completed_pairs",
                                                    "classifications", "estimated_cost_usd")}, sort_keys=True))


if __name__ == "__main__":
    main()
