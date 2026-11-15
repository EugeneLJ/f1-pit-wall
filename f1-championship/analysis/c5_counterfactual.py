#!/usr/bin/env python3
"""C5 strategic-relevance check: do qualifying setup choices change race outcomes? (no model calls)

For each of the eight races of the task seed, under opt-in 2.2.0 with the C5 weekend:
  1. Earlier races are played identically (neutral weekend, published baseline race policy).
  2. Practice at the race under test follows one fixed public plan (QUALI_SIM then LONG_RUN on the
     two non-default setups), so the information available is the same for every option.
  3. At QUALIFYING every legal setup pair (3 x 3, TWO_RUN) is submitted on a copy of the session.
     The race then starts from that qualifying grid with those parc-ferme setups, and is rolled out
     with the authoritative engine over K public SC/VSC futures (published model, conditioned on the
     observed first segment) with a fixed continuation policy for every car. Value = exact expected
     Apex points over the published retirement probabilities (the same estimator as b21_decisions).
  4. Control: balanced/balanced (the no-practice-information default, zero race effect).
Also reported: what the public-information C5 reference (track_c.c5.qualifying_reference) would choose
from priors alone and after practice, and the true-effect value of each choice.

Usage: scripts/py312 analysis/c5_counterfactual.py [--futures 32]
Writes analysis/results/c5/counterfactual.json
"""

from __future__ import annotations

import argparse
import copy
import itertools
import json
import statistics as st
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
TASK = HERE.parent
sys.path[:0] = [str(TASK / "src"), str(TASK), str(HERE)]

import b6_eval as E  # noqa: E402
from f1pitwall.integrated import config as C  # noqa: E402
from f1pitwall.integrated import session as S  # noqa: E402
from f1pitwall.integrated.policies import scripted  # noqa: E402
from track_c import c5  # noqa: E402

SEED = json.loads((TASK / "tests" / "hidden_seed.json").read_text())["base_seed"]
CFG = C.with_c5_weekend(C.solo_coordination(engineers="CHIEF_ONLY", chief={"provider": "harbor_agent"}))
SETUPS = ("balanced", "low_drag", "high_downforce")
NEUTRAL_P = {"type": "PRACTICE", "driver_a": {"program": "SETUP_TEST", "setup_id": "balanced", "laps": 0},
             "driver_b": {"program": "SETUP_TEST", "setup_id": "balanced", "laps": 0}}
PLAN = [  # the fixed public practice plan at the race under test (session 1, session 2)
    {"type": "PRACTICE", "driver_a": {"program": "QUALI_SIM", "setup_id": "low_drag", "laps": 8},
     "driver_b": {"program": "QUALI_SIM", "setup_id": "high_downforce", "laps": 8}},
    {"type": "PRACTICE", "driver_a": {"program": "LONG_RUN", "setup_id": "low_drag", "laps": 16},
     "driver_b": {"program": "LONG_RUN", "setup_id": "high_downforce", "laps": 16}},
]
RACE = scripted("baseline")


def qual(a, b):
    return {"type": "QUALIFYING", "driver_a": {"setup_id": a, "run_plan": "TWO_RUN"},
            "driver_b": {"setup_id": b, "run_plan": "TWO_RUN"}}


def session_at_qualifying(race_index):
    s = S.IntegratedSession(CFG, SEED, clock=lambda: 0.0)
    practice_done = 0
    while not (s.decision_type == S.QUALIFYING and s.state.race_index == race_index):
        if s.decision_type == S.PRACTICE:
            if s.state.race_index == race_index:
                action, practice_done = PLAN[practice_done], practice_done + 1
            else:
                action = NEUTRAL_P
        elif s.decision_type == S.QUALIFYING:
            action = qual("balanced", "balanced")
        else:
            action = RACE(s.observation("Apex"))
        s.submit("Apex", s.tick_id, action)
    return s


def evaluate(s, a, b, futures, continuation):
    node = copy.deepcopy(s)
    node.submit("Apex", node.tick_id, qual(a, b))
    race = node.race_state
    fut = E.futures_for(race, futures, f"c5|{node.state.race_index}")
    first = {"Apex": E.policy_action(continuation, race, "Apex")}
    values = [E.expected_team_points(E.rollout(race, first, {"Apex": continuation}, f), "Apex") for f in fut]
    grid = [node.public_driver(d) for d in node._active.starting_grid]
    return {"mean": st.mean(values), "values": values,
            "grid_A": grid.index("Apex A") + 1, "grid_B": grid.index("Apex B") + 1}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--futures", type=int, default=32)
    args = parser.parse_args()
    rows = []
    for race_index in range(8):
        s = session_at_qualifying(race_index)
        wk = s._weekend
        state = wk.states["Apex"]
        model = c5.load_model(wk.archetype)
        truth = {setup: {m: round(c5.core._true_effect(wk._key, wk.weekend_id, "Apex", setup, m, model), 4)
                         for m in ("qualifying_pace_offset_sec", "long_run_pace_offset_sec_per_lap", "deg_multiplier_factor")}
                 for setup in SETUPS}
        estimates = {setup: {m: {k: v[k] for k in ("mean", "ci95", "laps_observed")}
                             for m, v in state["practice"]["known_setup_estimates"][setup].items()}
                     for setup in SETUPS}
        options = {}
        for cont in ("baseline", "event_aware"):
            for a, b in itertools.product(SETUPS, SETUPS):
                options.setdefault(f"{a}/{b}", {})[cont] = evaluate(s, a, b, args.futures, cont)
        control = options["balanced/balanced"]
        ranked = sorted(options, key=lambda k: -options[k]["baseline"]["mean"])
        best = ranked[0]
        diff = [x - y for x, y in zip(options[best]["baseline"]["values"], control["baseline"]["values"])]
        se = st.pstdev(diff) / len(diff) ** 0.5
        # Priors-only view: the same weekend reached through two zero-lap practice sessions (no measurements).
        prior_state = c5.initial_public_state(model, weekend_id=state["weekend_id"], team="Apex",
                                              car_ids=state["car_ids"], field=state["field"])
        for _ in range(2):
            prior_state = c5.simulate_practice(prior_state, NEUTRAL_P, wk._key)["state"]
        ref_prior = c5.qualifying_reference(prior_state)
        ref_post = c5.qualifying_reference(state)
        prior_key = f"{ref_prior['driver_a']['setup_id']}/{ref_prior['driver_b']['setup_id']}"
        post_key = f"{ref_post['driver_a']['setup_id']}/{ref_post['driver_b']['setup_id']}"
        rows.append({
            "race": race_index + 1, "track": s.state.calendar[race_index].name, "archetype": wk.archetype,
            "truth_hidden": truth, "public_estimates_after_practice": estimates,
            "options": {k: {c: {"expected_points": round(v[c]["mean"], 3), "grid_A": v[c]["grid_A"], "grid_B": v[c]["grid_B"]}
                            for c in v} for k, v in options.items()},
            "control": "balanced/balanced", "control_points": round(control["baseline"]["mean"], 3),
            "best": best, "best_points": round(options[best]["baseline"]["mean"], 3),
            "best_minus_control": round(st.mean(diff), 3), "best_minus_control_se": round(se, 3),
            "best_under_event_aware": max(options, key=lambda k: options[k]["event_aware"]["mean"]),
            "worst": ranked[-1], "spread": round(options[best]["baseline"]["mean"] - options[ranked[-1]]["baseline"]["mean"], 3),
            "reference_priors_only": prior_key, "reference_after_practice": post_key,
            "reference_after_practice_points": round(options[post_key]["baseline"]["mean"], 3) if post_key in options else None,
            "reference_priors_only_points": round(options[prior_key]["baseline"]["mean"], 3) if prior_key in options else None,
        })
        print(f"R{race_index + 1} {wk.archetype:16s} control {rows[-1]['control_points']:6.2f}  best {best:28s} "
              f"{rows[-1]['best_points']:6.2f} (+{rows[-1]['best_minus_control']:.2f} ± {se:.2f})  "
              f"ref prior {prior_key} → after practice {post_key}")
    out = {"schema_version": 1, "benchmark_version": "2.2.0", "config": CFG.as_dict(), "futures": args.futures,
           "practice_plan": PLAN, "race_policy": "published baseline for every car (also event_aware)",
           "estimator": "exact expected Apex points over published retirement probabilities, public SC/VSC futures",
           "rows": rows}
    path = HERE / "results" / "c5" / "counterfactual.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(out, indent=1) + "\n")


if __name__ == "__main__":
    main()
