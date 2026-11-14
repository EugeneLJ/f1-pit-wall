#!/usr/bin/env python3
"""P1-B/C experiment: exact reduced-season values, ablations, pairs, hindsight.

Usage: python3 analysis/run_track_a.py [--scenarios 24] [--workers 10]
Writes analysis/results/track_a_p1.json.
"""

from __future__ import annotations

import argparse
import json
import multiprocessing as mp
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

POLICIES = ("always_use", "rival_rule", "greedy")
HINDSIGHT_SCENARIOS = 6
HINDSIGHT_SEEDS = (101, 202)
MC_SCENARIOS = 3
MC_SEEDS = range(1000, 1300)


def _coeffs(mechanic):
    from f1pitwall import coefficients as coef
    return coef.DEFAULT if mechanic is None else coef.ablate(coef.DEFAULT, mechanic)


def eval_job(args):
    import scenarios as sc
    from track_a_solver import Solver, option_label
    spec, mechanic, tag = args
    coeffs = _coeffs(mechanic)
    started = time.time()
    solver = Solver(coeffs)
    state = sc.build_state(spec, coeffs)
    value, option = solver.optimal(state)
    out = {"scenario": spec["id"], "mechanic": mechanic, "tag": tag,
           "optimal": value, "optimal_first": option_label(option), "policies": {}}
    for policy in POLICIES:
        out["policies"][policy] = {"value": solver.evaluate(state, policy),
                                   "first": option_label(solver.choose(state, policy))}
    ranked = sorted(solver.option_values(state), key=lambda item: -item[0])
    out["first_race_options"] = [{"option": option_label(o), "season_value": v, "this_race_value": now}
                                 for v, now, o in ranked[:5]]
    out["race_evaluations"] = solver.race_evaluations
    out["seconds"] = round(time.time() - started, 1)
    return out


def hindsight_job(args):
    import scenarios as sc
    from track_a_solver import Solver
    spec, seed = args
    started = time.time()
    solver = Solver(_coeffs(None))
    state = sc.build_state(spec)
    out = {"scenario": spec["id"], "seed": seed, "hindsight": solver.hindsight(state, seed),
           "realized": {p: solver.realized(state, p, seed) for p in ("optimal",) + POLICIES}}
    out["seconds"] = round(time.time() - started, 1)
    return out


def mc_job(args):
    import scenarios as sc
    from track_a_solver import Solver
    spec = args
    solver = Solver(_coeffs(None))
    state = sc.build_state(spec)
    out = {"scenario": spec["id"]}
    for policy in ("optimal", "greedy"):
        exact = solver.evaluate(state, policy)
        samples = [solver.realized(state, policy, seed) for seed in MC_SEEDS]
        mean = sum(samples) / len(samples)
        var = sum((x - mean) ** 2 for x in samples) / (len(samples) - 1)
        out[policy] = {"exact": exact, "mc_mean": mean, "mc_se": (var / len(samples)) ** 0.5,
                       "n": len(samples)}
    return out


def penalty_cost_job(args):
    """Expected points lost to a 4-place ICE drop, by archetype and overtaking difficulty."""
    import copy
    from track_a_solver import APEX, COMPONENTS, Solver, prepare
    from f1pitwall import coefficients as coef
    from f1pitwall.championship import RaceEntry, new_championship_state
    from f1pitwall.championship_transition import initial_inventory
    archetype, difficulty = args
    entry = RaceEntry(name="P", archetype=archetype, power_unit_stress=0.5, overtaking_difficulty=difficulty,
                      tyre_degradation=0.5, synthetic_placeholder=True)
    state = new_championship_state(calendar=[entry], resource_inventory=initial_inventory(coef.DEFAULT))
    state.resource_inventory["Apex"]["component_spares"] = 0
    solver = Solver()
    base = solver.race_value(prepare(state, solver.choose(state, "always_use"), coef.DEFAULT))
    out = {"archetype": archetype, "difficulty": difficulty, "base": base}
    for driver in APEX:
        option = tuple((d, c, "REPLACE" if (d == driver and c == "ICE") else "USE") for d in APEX for c in COMPONENTS)
        out[driver] = base - solver.race_value(prepare(state, option, coef.DEFAULT))
    return out


def _guard_runtime():
    from _runtime import require_runtime_python
    require_runtime_python()


def main():
    import scenarios as sc
    from f1pitwall.coefficients import MECHANICS
    parser = argparse.ArgumentParser()
    parser.add_argument("--scenarios", type=int, default=24)
    parser.add_argument("--workers", type=int, default=10)
    args = parser.parse_args()

    specs = sc.generate_specs(args.scenarios)
    jobs = [(spec, None, "default") for spec in specs]
    jobs += [(spec, m, "ablation") for spec in specs for m in MECHANICS]
    for spec in specs:
        variants = sc.pair_variants(spec)
        jobs += [(variants[k], None, k) for k in ("late_high_speed", "late_street", "control_b")]
    hindsight = [(spec, seed) for spec in specs[:HINDSIGHT_SCENARIOS] for seed in HINDSIGHT_SEEDS]

    started = time.time()
    with mp.Pool(args.workers) as pool:
        h_async = pool.map_async(hindsight_job, hindsight)
        m_async = pool.map_async(mc_job, specs[:MC_SCENARIOS])
        evals = []
        for index, result in enumerate(pool.imap_unordered(eval_job, jobs), start=1):
            evals.append(result)
            if index % 24 == 0:
                print(f"{index}/{len(jobs)} evals, {time.time() - started:.0f}s", flush=True)
        hind = h_async.get()
        mc = m_async.get()
        grid = pool.map(penalty_cost_job, [(a, d) for a in sorted(sc.ARCHETYPE_RANGES)
                                           for d in (0.1, 0.3, 0.5, 0.7, 0.9)])

    out = {"generator_seed": sc.GENERATOR_SEED, "scenarios": [
        {"id": s["id"], "early_habit": s["early_habit"],
         "calendar": [[r.name, r.archetype, r.power_unit_stress, r.overtaking_difficulty, r.tyre_degradation]
                      for r in s["calendar"]]} for s in specs],
        "evals": evals, "hindsight": hind, "monte_carlo": mc, "penalty_cost_grid": grid,
        "wall_seconds": round(time.time() - started, 1)}
    path = HERE / "results" / "track_a_p1.json"
    path.parent.mkdir(exist_ok=True)
    path.write_text(json.dumps(out, indent=1, sort_keys=True))
    print(f"wrote {path} in {out['wall_seconds']}s")


if __name__ == "__main__":
    _guard_runtime()
    main()
