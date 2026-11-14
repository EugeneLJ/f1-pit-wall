#!/usr/bin/env python3
"""Verifier-side baselines on the hidden evaluation seed (single seed, realized points).

Component policies use the public baseline race play. 'rollout_reference' combines the
replacement-rule component policy with the B4 public-information in-race rollout reference
(analysis/b4_counterfactual.py: one-step lookahead over public futures; never sees the true
future). These are single-seed outcomes: compare with expected values before generalizing.
Usage: python3 analysis/seed_baselines.py <out.json>
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import track_a_solver as ts  # noqa: E402
import b4_counterfactual as b4  # noqa: E402
from f1pitwall import coefficients as coef  # noqa: E402
from f1pitwall import engine  # noqa: E402
from f1pitwall.championship import new_championship_state  # noqa: E402
from f1pitwall.championship_transition import initial_inventory  # noqa: E402

SEED = json.loads((HERE.parent / "tests" / "hidden_seed.json").read_text())["base_seed"]


def season(component_rule, race_policy):
    solver = ts.Solver(coef.DEFAULT)
    state = new_championship_state(resource_inventory=initial_inventory(coef.DEFAULT))
    per_race, replacements, drops = [], [], []
    while state.race_index < len(state.calendar):
        option = solver.choose(state, component_rule)
        prepared = ts.prepare(state, option, coef.DEFAULT)
        race = solver._seeded_race(prepared, SEED)
        while race["step"] < len(race["events"]):
            engine.step(race, race_policy(race))
        per_race.append(engine.result(race)["constructors_points"])
        replacements.append([f"{d}:{c}" for d, c, a in option if a == "REPLACE"])
        drops.append({d: prepared.grid_penalties[d] for d in ts.APEX})
        state = ts.after_race(prepared, coef.DEFAULT)
    return {"total": sum(per_race), "per_race": per_race, "replacements": replacements, "grid_drops": drops}


def main(out):
    baseline = lambda race: ts.baseline_race_action(engine.observation(race))  # noqa: E731
    stay = lambda race: {"driver_a": "STAY", "driver_b": "STAY"}  # noqa: E731
    results = {
        "do_nothing (always USE, always STAY)": season("always_use", stay),
        "always_use + baseline race": season("always_use", baseline),
        "rival_rule + baseline race": season("rival_rule", baseline),
        "greedy + baseline race": season("greedy", baseline),
        "rival_rule + rollout race reference": season("rival_rule", b4.rollout_action),
    }
    Path(out).write_text(json.dumps(results, indent=1))
    for name, r in results.items():
        print(f"{name}: {r['total']}  {r['per_race']}")


if __name__ == "__main__":
    main(sys.argv[1])
