#!/usr/bin/env python3
"""B7-P0 -> C4: build C4 bundles from the live pilot runs and evaluate them with
track_c.coordination_evaluation (71a3c8d). No model call, no engine change.

Each decision gets an `equal_information_reference` from b7_analysis (authoritative-engine
public-input rollout; model-access advantage): regret_ci = mean +/- 1.96 se over common public
futures, near_tie_threshold 1.0 point. Hypotheses are attached only with concrete evidence:
  FAILURE_TO_ADAPT_TO_SC_VSC_OR_RIVAL           decision under SC/VSC (or the rival team within 2 s)
  EXCESSIVE_RELIANCE_ON_ENGINEER_RECOMMENDATIONS  the Chief's pit choice for a driver equals that
                                                 driver's Engineer proposal and differs from the reference
  UNJUSTIFIED_REJECTION_OF_USEFUL_RECOMMENDATIONS the Engineer proposed the reference's choice and the
                                                 Chief chose otherwise
C4 confirms a label only if the regret CI's lower bound exceeds the threshold.
Usage: scripts/py312 analysis/b7_c4.py analysis/results/b7     -> analysis/results/b7/c4_report.json
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
TASK = HERE.parent
sys.path[:0] = [str(TASK / "src"), str(TASK)]

from track_c.coordination_evaluation import build_bundle_from_run, compare_layers, summarize_bundle  # noqa: E402

NEAR_TIE = 1.0


def load_layer(d: Path):
    summary = json.loads((d / "summary.json").read_text())
    journal = [json.loads(x) for x in (d / "journal.jsonl").read_text().splitlines() if x]
    ticks = [json.loads(x) for x in (d / "ticks.jsonl").read_text().splitlines() if x]
    analysis = json.loads((d / "analysis.json").read_text())
    records = {}
    store = d / "engineers" / "mclearn_racing" / "engineer_records.jsonl"
    if store.exists():
        records["McLearn Racing"] = [json.loads(x) for x in store.read_text().splitlines() if x]
    return summary, journal, ticks, analysis, records


def bundle_for(d: Path, layer: str):
    summary, journal, ticks, analysis, records = load_layer(d)
    run = {"journal": journal, "base_seed_id": summary["seed_id"], "rival_condition": summary["config"]["rival_condition"],
           "standings": summary["standings"], "race_results": summary["race_results"], "complete": summary["complete"]}
    slots = {t["label"]: t["slot"] for t in summary["config"]["teams"]}
    bundle = build_bundle_from_run(run=run, observations=ticks, layer=layer, result_kind="ACTUAL_MODEL",
                                   slot_assignment=slots, engineer_records=records,
                                   run_id=f"b7p0-{layer.lower()}-{summary['seed_id']}")
    refs = {(r["tick_id"], r["team"]): r for r in analysis["decisions"]}
    for decision in bundle["decisions"]:
        ref = refs.get((decision["tick_id"], decision["team"]))
        if ref is None:
            continue
        lo, hi = ref["regret"] - 1.96 * ref["se"], ref["regret"] + 1.96 * ref["se"]
        decision["equal_information_reference"] = {
            "reference_action": ref["reference"], "chosen_expected_team_points": ref["q_chosen"],
            "reference_expected_team_points": ref["q_reference"],
            "regret_ci": {"low": round(lo, 4), "mean": ref["regret"], "high": round(hi, 4)},
            "source": "AUTHORITATIVE_ENGINE_PUBLIC_INPUT_ROLLOUT", "uses_future_realization": False,
            "sensitivity": {"near_tie_threshold_points": NEAR_TIE, "futures": analysis["reference"]["futures"],
                            "continuation": analysis["reference"]["continuation"],
                            "rival_same_tick": analysis["reference"]["rival_same_tick"],
                            "model_access": "reference executes the exact engine; Chiefs do not"}}
        hyps = []
        if ref["status"] != "GREEN" or "opponent:rival_team_within_2s" in ref["tags"]:
            hyps.append({"label": "FAILURE_TO_ADAPT_TO_SC_VSC_OR_RIVAL",
                         "evidence": [f"status={ref['status']}", f"chosen={ref['chosen']}",
                                      f"reference={ref['reference']}", *[t for t in ref["tags"] if t.startswith(("event", "opponent", "double"))]]})
        chosen_pits = dict(zip(("driver_a", "driver_b"), ref["chosen"].split("|")[0].split("/")))
        ref_pits = dict(zip(("driver_a", "driver_b"), ref["reference"].split("|")[0].split("/")))
        for wrapped in decision["engineer_reports"]:
            rec = wrapped["record"].get("recommendation") or {}
            prop = rec.get("proposed_action", {})
            if "choice" not in prop:
                continue
            drv = prop["driver"]
            if prop["choice"] == chosen_pits[drv] != ref_pits[drv]:
                hyps.append({"label": "EXCESSIVE_RELIANCE_ON_ENGINEER_RECOMMENDATIONS",
                             "evidence": [f"{wrapped['record']['engineer_id']} proposed {prop['choice']} for {drv}",
                                          f"Chief chose {chosen_pits[drv]}", f"reference {ref_pits[drv]}"]})
            elif prop["choice"] == ref_pits[drv] != chosen_pits[drv]:
                hyps.append({"label": "UNJUSTIFIED_REJECTION_OF_USEFUL_RECOMMENDATIONS",
                             "evidence": [f"{wrapped['record']['engineer_id']} proposed {prop['choice']} for {drv}",
                                          f"reference {ref_pits[drv]}", f"Chief chose {chosen_pits[drv]}"]})
        decision["diagnostic_hypotheses"] = hyps
    return bundle


def main():
    root = Path(sys.argv[1])
    bundles = {}
    for n, layer in ((1, "LAYER_1"), (2, "LAYER_2")):
        d = root / f"layer{n}"
        if (d / "analysis.json").exists():
            bundles[layer] = bundle_for(d, layer)
            (d / "c4_bundle.json").write_text(json.dumps(bundles[layer], sort_keys=True))
    if len(bundles) == 2:
        report = compare_layers(bundles["LAYER_1"], bundles["LAYER_2"])
    else:
        report = {"single": summarize_bundle(next(iter(bundles.values())))}
    (root / "c4_report.json").write_text(json.dumps(report, indent=1, sort_keys=True, allow_nan=False))
    for key in ("layer_1", "layer_2"):
        part = report.get(key) or report.get("single")
        if part:
            print(key, part["integrity"]["integrity"], part["integrity"]["resolved_ticks"], "decisions", part["decision_count"],
                  "failure_counts", part["failure_counts"], "commitments", len(part["commitments"]))
    if "team_points_change" in report:
        print("team_points_change", report["team_points_change"])


if __name__ == "__main__":
    main()
