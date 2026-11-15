#!/usr/bin/env python3
"""Generate matched adaptive-rival probes from public post-action states.

The prior rival action is applied before the probed Chief decision, so its pit
history is public.  All alternatives use unchanged engine mechanics and common
public-event futures.  Probe selection depends only on reference reversals/controls,
never on a model's observed errors.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
import statistics as st
import sys
from collections import Counter, defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
TASK = HERE.parent
sys.path[:0] = [str(TASK / "src"), str(TASK), str(HERE)]

import b6_eval as E  # noqa: E402
from f1pitwall import engine  # noqa: E402
from f1pitwall.integrated import race as ir  # noqa: E402
from track_c.adaptive_rival_evaluation import classify_adaptation  # noqa: E402

VARIANTS = ("conservative_2stop", "opportunistic", "undercut", "long_stint", "event_aware")
SLOT, RIVAL = "Apex", "Orion"


def obs_hash(value):
    text = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(text.encode()).hexdigest()


def action_key(action):
    return f"{action['driver_a']}/{action['driver_b']}"


def reference(post, rival_policy, futures, common_futures):
    legal = engine.legal_actions(post)
    rival_now = E.policy_action(rival_policy, post, RIVAL)
    values = {}
    raw = {}
    for a in legal:
        for b in legal:
            key = f"{a}/{b}"
            first = {SLOT: {"driver_a": a, "driver_b": b, "team_order": {"order": "RACE"}},
                     RIVAL: rival_now}
            samples = [E.expected_team_points(E.rollout(post, first, {SLOT: "baseline", RIVAL: rival_policy}, future), SLOT)
                       for future in common_futures[:futures]]
            values[key], raw[key] = st.mean(samples), samples
    ranked = sorted(values, key=lambda key: (-values[key], key))
    best, second = ranked[:2]
    diff = [a - b for a, b in zip(raw[best], raw[second])]
    mean = st.mean(diff)
    se = st.stdev(diff) / math.sqrt(len(diff)) if len(diff) > 1 else 0.0
    return {"reference_action": best, "reference_gap": max(0.0, mean - 1.96 * se),
            "reference_gap_mean": mean, "reference_gap_ci95": [mean - 1.96 * se, mean + 1.96 * se],
            "q_all": {key: round(value, 5) for key, value in values.items()},
            "rival_current_action": action_key(rival_now)}


def build_rows(seeds, futures):
    rows = []
    sampled_states = 0
    for seed in seeds:
        for race_index, state in E.sample_states(seed, every=1):
            if state["complete"]:
                continue
            sampled_states += 1
            own_prior = E.policy_action("baseline", state, SLOT)
            rival_base = E.policy_action("baseline", state, RIVAL)
            for variant in VARIANTS:
                rival_alt = E.policy_action(variant, state, RIVAL)
                if rival_alt == rival_base:
                    continue
                base, altered = copy.deepcopy(state), copy.deepcopy(state)
                ir.step(base, {SLOT: own_prior, RIVAL: rival_base})
                ir.step(altered, {SLOT: own_prior, RIVAL: rival_alt})
                if base["complete"] or altered["complete"]:
                    continue
                base_obs, alt_obs = E.team_obs(base, SLOT), E.team_obs(altered, SLOT)
                base_pits = base_obs["race_progress"].get("public_pit_history", [])
                alt_pits = alt_obs["race_progress"].get("public_pit_history", [])
                if base_pits == alt_pits:
                    continue
                common = E.futures_for(base, futures, f"c6|{seed}|{race_index}|{state['step']}|{variant}")
                ra = reference(base, "baseline", futures, common)
                rb = reference(altered, variant, futures, common)
                pair = {"pair_id": f"s{seed}-r{race_index}-d{state['step'] + 1}-{variant}",
                        "result_kind": "SYNTHETIC_DIAGNOSTIC_PROBE",
                        "public_evidence_diff": {"visible_before_chief_decision": True,
                                                 "baseline_observation_hash": obs_hash(base_obs),
                                                 "altered_observation_hash": obs_hash(alt_obs),
                                                 "baseline_public_observation": base_obs,
                                                 "altered_public_observation": alt_obs,
                                                 "baseline_public_pit_history": base_pits,
                                                 "altered_public_pit_history": alt_pits},
                        "condition_a": ra, "condition_b": rb,
                        "reference_provenance": {"engine": "authoritative public-input rollout",
                                                 "futures": futures, "common_futures": True,
                                                 "continuation": "baseline own; named rival policy",
                                                 "realized_future_used_as_observation": False},
                        "uses_hidden_policy_as_observation": False}
                classified = classify_adaptation(pair)
                base_stops = sum(value != "STAY" for value in (rival_base["driver_a"], rival_base["driver_b"]))
                alt_stops = sum(value != "STAY" for value in (rival_alt["driver_a"], rival_alt["driver_b"]))
                category = ("EARLIER_OR_EXTRA_RIVAL_PIT" if alt_stops > base_stops else
                            "LATER_OR_FEWER_RIVAL_PIT" if alt_stops < base_stops else
                            "RIVAL_COMPOUND_OR_ORDER_CHANGE")
                if state["events"][state["step"]] != "GREEN":
                    category = "SC_VSC_OPPORTUNISTIC_RIVAL_ACTION"
                elif variant == "undercut":
                    category = "RIVAL_UNDERCUT_ATTEMPT"
                rows.append({"seed": seed, "race_index": race_index, "source_decision": state["step"] + 1,
                             "variant": variant, "probe_category": category,
                             "prior_track_status": state["events"][state["step"]],
                             "baseline_prior_rival_action": action_key(rival_base),
                             "altered_prior_rival_action": action_key(rival_alt),
                             "pair": pair, "reference_classification": classified["classification"],
                             "reference_reversal": classified["reference_reversal"]})
    return rows, sampled_states


def select(rows, per_bucket=3):
    buckets = defaultdict(list)
    for row in rows:
        kind = ("REVERSAL" if row["reference_reversal"] else
                "NEAR_TIE" if row["reference_classification"] == "NEAR_TIE" else "NO_CHANGE_CONTROL")
        buckets[(row["variant"], kind)].append(row)
    selected = []
    for key in sorted(buckets):
        selected.extend(sorted(buckets[key], key=lambda row: row["pair"]["pair_id"])[:per_bucket])
    return selected


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--seeds", type=int, default=12)
    parser.add_argument("--offset", type=int, default=400)
    parser.add_argument("--futures", type=int, default=12)
    parser.add_argument("--per-bucket", type=int, default=3)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    seeds = list(range(args.offset, args.offset + args.seeds))
    rows, sampled_states = build_rows(seeds, args.futures)
    selected = select(rows, args.per_bucket)
    output = {"schema_version": 1, "generator": {"seeds": seeds, "futures": args.futures,
                                                   "selection": "first pair IDs per variant/reference class; no model outputs"},
              "natural_sampled_pre_action_states": sampled_states,
              "candidate_state_variant_pairs": sampled_states * len(VARIANTS),
              "eligible_visible_action_pairs": len(rows),
              "natural_frequency_visible_pairs": round(
                  len(rows) / (sampled_states * len(VARIANTS)), 6) if sampled_states else 0.0,
              "reference_classes": dict(Counter("REVERSAL" if row["reference_reversal"] else
                                                 "NEAR_TIE" if row["reference_classification"] == "NEAR_TIE"
                                                 else "NO_CHANGE_CONTROL" for row in rows)),
              "categories": dict(Counter(row["probe_category"] for row in rows)),
              "targeted_probe_count": len(selected), "targeted_probes": selected,
              "actual_model_results": False}
    Path(args.output).write_text(json.dumps(output, indent=2, sort_keys=True, allow_nan=False) + "\n")
    print(json.dumps({key: output[key] for key in ("eligible_visible_action_pairs", "natural_frequency_visible_pairs",
                                                    "reference_classes", "targeted_probe_count")}, sort_keys=True))


if __name__ == "__main__":
    main()
