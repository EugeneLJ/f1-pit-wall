#!/usr/bin/env python3
"""P1-D: full 8-race horizon ablation, season-level pairs, seed spread, hindsight.

Usage: python3 analysis/run_track_a_season.py [--scenarios 24] [--pair-scenarios 12] [--workers 10]
Writes analysis/results/track_a_p1d.json.
"""

from __future__ import annotations

import argparse
import copy
import json
import multiprocessing as mp
import random
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

POLICIES = ("always_use", "rival_rule", "greedy", "mpc:2", "mpc:3", "mpc:5", "mpc:8", "exact3")
REFERENCE = "mpc:8"
SEEDS = range(5000, 5040)
SENSITIVITY_SCENARIOS = 6
HINDSIGHT_RUNS = ((0, 701), (1, 701), (2, 702), (3, 702))
EARLY_RACES = 3  # races 1-3 are "early" for the cross-world test


def season_state(spec):
    from f1pitwall import coefficients as coef
    from f1pitwall.championship import new_championship_state
    from f1pitwall.championship_transition import initial_inventory
    return new_championship_state(calendar=spec["calendar"], resource_inventory=initial_inventory(coef.DEFAULT))


def season_variants(spec):
    """Same races 1-5; races 6-8 replaced (decision pair) or jittered (control)."""
    import scenarios as sc
    from f1pitwall.championship import RaceEntry
    rng = random.Random(f"season-control:{spec['id']}")

    def jitter(race):
        clip = lambda v: round(min(1.0, max(0.0, v + rng.uniform(-0.03, 0.03))), 3)  # noqa: E731
        return RaceEntry(name=race.name + "j", archetype=race.archetype, power_unit_stress=clip(race.power_unit_stress),
                         overtaking_difficulty=clip(race.overtaking_difficulty),
                         tyre_degradation=clip(race.tyre_degradation), synthetic_placeholder=True)

    def variant(late, label):
        out = copy.deepcopy(dict(spec))
        out["calendar"] = list(spec["calendar"][:5]) + list(late)
        out["id"] = f"{spec['id']}-{label}"
        return out

    return {
        "late_high_speed": variant([sc.midpoint_track(f"{spec['id']}-HS{i}", "high_speed") for i in (1, 2, 3)], "HS"),
        "late_street": variant([sc.midpoint_track(f"{spec['id']}-ST{i}", "street") for i in (1, 2, 3)], "ST"),
        "control": variant([jitter(r) for r in spec["calendar"][5:]], "CT"),
    }


def season_job(args):
    import season_planner as sp
    import track_a_solver as ts
    spec, policy, budget, tag, forced = args
    state = season_state(spec)
    prefix = None
    if forced is not None:
        prefix = sp.options_from_path(state, forced)
    result = sp.run_season(state, policy, budget=budget, forced_prefix=prefix)
    result.update({"scenario": spec["id"].split("-")[0], "variant": tag, "budget": budget,
                   "forced_prefix_races": len(forced) if forced else 0})
    if tag == "main":
        solver = ts.Solver()
        options = sp.options_from_path(season_state(spec), result["path"])
        result["realized"] = {seed: sp.realized_path_points(season_state(spec), options, seed, solver)
                              for seed in SEEDS}
    return result


def hindsight_job(args):
    """Open-loop budgeted search with the seed's realized events and draws (privileged)."""
    import season_planner as sp
    import track_a_solver as ts
    spec, seed, budget = args
    solver = ts.Solver()

    class HindsightEvaluator(sp.Evaluator):
        cache = {}

        def race_value(self, prepared):
            key = (ts.race_key(prepared), prepared.race_index)
            if key not in self.cache:
                if self.budget is not None and self.used >= self.budget:
                    raise sp.BudgetExceeded
                self.used += 1
                self.cache[key] = ts.hindsight_race_value(solver._seeded_race(prepared, seed))[0]
            return self.cache[key]

    started = time.time()
    value, plan, info = sp.search(HindsightEvaluator(solver), season_state(spec), 8, budget)
    return {"scenario": spec["id"], "seed": seed, "hindsight_lower_bound": value, "search": info,
            "seconds": round(time.time() - started, 1)}


def _guard_runtime():
    from _runtime import require_runtime_python
    require_runtime_python()


def main():
    import scenarios as sc
    import season_planner as sp
    parser = argparse.ArgumentParser()
    parser.add_argument("--scenarios", type=int, default=24)
    parser.add_argument("--pair-scenarios", type=int, default=12)
    parser.add_argument("--workers", type=int, default=10)
    args = parser.parse_args()
    specs = sc.generate_specs(args.scenarios)
    budget = sp.DEFAULT_RACE_BUDGET
    started = time.time()
    with mp.Pool(args.workers) as pool:
        main_jobs = [(spec, policy, budget, "main", None) for spec in specs for policy in POLICIES]
        sens_jobs = [(spec, REFERENCE, 2 * budget, "budget_x2", None) for spec in specs[:SENSITIVITY_SCENARIOS]]
        variant_jobs = []
        for spec in specs[:args.pair_scenarios]:
            for tag, vspec in season_variants(spec).items():
                variant_jobs.append((vspec, REFERENCE, budget, tag, None))
                variant_jobs.append((vspec, "greedy", budget, f"{tag}:greedy", None))
        hind_async = pool.map_async(hindsight_job, [(specs[i], seed, budget) for i, seed in HINDSIGHT_RUNS])
        results = []
        for index, r in enumerate(pool.imap_unordered(season_job, main_jobs + sens_jobs + variant_jobs), start=1):
            results.append(r)
            if index % 20 == 0:
                print(f"{index}/{len(main_jobs) + len(sens_jobs) + len(variant_jobs)} seasons, "
                      f"{time.time() - started:.0f}s", flush=True)
        # cross-world: play the other variant's reference decisions for races 1-3, then the reference
        ref = {(r["scenario"], r["variant"]): r for r in results if r["policy"] == REFERENCE}
        cross_jobs = []
        for spec in specs[:args.pair_scenarios]:
            v = season_variants(spec)
            sid = spec["id"]
            for world, other in (("late_high_speed", "late_street"), ("late_street", "late_high_speed"),
                                 ("control", "main")):
                forced = ref[(sid, other)]["path"][:EARLY_RACES]
                cross_jobs.append((v[world], REFERENCE, budget, f"cross:{world}<-{other}", forced))
        cross = pool.map(season_job, cross_jobs)
        hind = hind_async.get()
    out = {"generator_seed": sc.GENERATOR_SEED, "budget": {"race_evaluations_per_decision": budget,
                                                          "plan_evaluation_cap": sp.PLAN_EVALUATION_CAP},
           "seeds": list(SEEDS), "scenarios": [
               {"id": s["id"], "calendar": [[r.name, r.archetype, r.power_unit_stress, r.overtaking_difficulty,
                                             r.tyre_degradation] for r in s["calendar"]]} for s in specs],
           "seasons": results, "cross": cross, "hindsight": hind, "wall_seconds": round(time.time() - started, 1)}
    path = HERE / "results" / "track_a_p1d.json"
    path.write_text(json.dumps(out, indent=1, sort_keys=True, default=str))
    print(f"wrote {path} in {out['wall_seconds']}s")


if __name__ == "__main__":
    _guard_runtime()
    main()
