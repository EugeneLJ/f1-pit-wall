#!/usr/bin/env python3
"""Freeze the C7 live selection over the preregistered expansion candidates (no model output used).

The preregistration (track_c/fixtures/c7_adaptive_expansion_prereg.json) fixes the live pilot to
exactly the frozen candidates: 3 VALIDATED_REVERSAL, 3 NO_CHANGE_CONTROL, 2 NEAR_TIE pairs, at most
16 model calls including smoke. This script only records those 8 pairs, in file order, with the
source file's SHA-256, in the selection format c7_live_paired_probe.py / c7_evaluate_live.py read.
"""

from __future__ import annotations

import hashlib
import json
import sys
from collections import Counter
from pathlib import Path

TASK = Path(__file__).resolve().parents[1]
SOURCE = TASK / "analysis/results/c7/adaptive_expansion_candidates.json"
PREREG = TASK / "track_c/fixtures/c7_adaptive_expansion_prereg.json"
OUT = TASK / "analysis/results/c7/live_selection_expansion.json"


def main():
    source_bytes = SOURCE.read_bytes()
    artifact = json.loads(source_bytes)
    prereg = json.loads(PREREG.read_text())
    if artifact.get("actual_model_results") is not False:
        raise SystemExit("candidate file must not contain model results")
    rows = artifact["targeted_probes"]
    sys.path.insert(0, str(TASK / "analysis"))
    from c7_select_probes import row_class as cls  # C7's corrected, mutually exclusive class precedence
    counts = Counter(cls(r) for r in rows)
    wanted = prereg["conditional_live_pilot"]["pairs"]
    out = {"schema_version": 1, "selection_version": "c7-expansion-selection-v1",
           "source_sha256": hashlib.sha256(source_bytes).hexdigest(),
           "criteria": "all 8 preregistered expansion candidates, in frozen file order; no model output used",
           "counts": dict(counts), "preregistered_counts": wanted,
           "maximum_model_calls": prereg["conditional_live_pilot"]["maximum_model_calls"],
           "pairs": [{"pair_id": r["pair"]["pair_id"], "reference_class": cls(r),
                      "probe_category": r.get("probe_category"),
                      "baseline_observation_hash": r["pair"]["public_evidence_diff"]["baseline_observation_hash"],
                      "altered_observation_hash": r["pair"]["public_evidence_diff"]["altered_observation_hash"]}
                     for r in rows]}
    if dict(counts) != {"REVERSAL" if k == "VALIDATED_REVERSAL" else k: v for k, v in wanted.items()}:
        raise SystemExit(f"candidate classes {dict(counts)} differ from the preregistration {wanted}")
    if len(out["pairs"]) * 2 > out["maximum_model_calls"]:
        raise SystemExit("selection exceeds the preregistered call budget")
    OUT.write_text(json.dumps(out, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"pairs": len(out["pairs"]), "counts": out["counts"], "source_sha256": out["source_sha256"][:16]}))


if __name__ == "__main__":
    sys.exit(main())
