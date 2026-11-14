#!/usr/bin/env python3
"""B8 Priority A/B: multi-component penalty bundling and circuit-specific penalty timing under the
opt-in FIA-2026-based PU rules (benchmark 2.1.0). No model call; nothing tuned.

Scenario generation (declared sampling distribution, chosen before any evaluation):
  calendars  scenarios.generate_specs(N) (the same generator used since P1)
  history    every team follows the published threshold rule (replace at wear >= 0.65) until a
             race-start state where an Apex driver has >= 2 components with wear >= 0.45
             ("decision state"). Its natural frequency is reported.
Plans for that driver (the teammate and all rivals keep the published rule):
  BUNDLE_NOW    replace every component with wear >= 0.45 at this race (penalties stack)
  DISTRIBUTE    replace the most worn now, the next one at the next race, ...
  DEFER_BUNDLE  replace nothing now, bundle all of them at the next race
  NO_CHANGE     never replace unless forced (wear above the use limit)
Value: expected Apex constructors' points over the REST of the season (exact over the published
retirement probabilities), averaged over K SC/VSC schedules drawn from the published process
(independent analysis seeds, never the hidden race seeds). Race strategy: the public baseline
rule for every car. Same public information for every plan.
Penalty timing (B): each decision state is paired with the same state where the next two races are
swapped. A reversal means the preferred of BUNDLE_NOW / DEFER_BUNDLE changes with the circuit order.
Usage: scripts/py312 analysis/b8_penalties.py [--calendars 40] [--futures 8] [--workers 10]
Writes analysis/results/b8_penalties.json
"""

from __future__ import annotations

import argparse
import copy
import json
import math
import multiprocessing as mp
import statistics as st
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
TASK = HERE.parent
sys.path.insert(0, str(TASK / "src"))
sys.path.insert(0, str(HERE))

import scenarios as sc  # noqa: E402
import track_a_solver as ts  # noqa: E402
from f1pitwall import coefficients as coef  # noqa: E402
from f1pitwall import engine, pu_rules  # noqa: E402
from f1pitwall.championship import TEAM_DRIVERS, new_championship_state  # noqa: E402
from f1pitwall.championship_adapter import finish_prepared_race, start_prepared_race  # noqa: E402
from f1pitwall.championship_transition import driver_team, initial_inventory, prepare_race  # noqa: E402

COEFFS = pu_rules.with_fia_pu_rules(coef.DEFAULT)
WORN = 0.45
THRESHOLD = COEFFS["rival_component_policy"]["threshold"]
LIMIT = coef.max_wear_for_use(COEFFS)
PLANS = ("BUNDLE_NOW", "DISTRIBUTE", "DEFER_BUNDLE", "NO_CHANGE")
NEAR_TIE = 1.0


def rule_decisions(state, skip=None):
    out = []
    for driver, comps in state.power_units.items():
        for name, comp in comps.items():
            if (driver, name) == skip or (skip and driver == skip[0]):
                continue
            stock = state.resource_inventory[driver_team(driver)].get(pu_rules.stock_key(name), 0)
            replace = (comp.wear >= THRESHOLD and stock > 0) or comp.wear > LIMIT
            out.append({"driver": driver, "component": name, "action": "REPLACE" if replace else "USE"})
    return out


def run_race(state, decisions, events):
    prepare_race(state, decisions, COEFFS)
    active = start_prepared_race(state, 0, COEFFS, events=events)
    race = active.race_state
    while not race["complete"]:
        engine.step(race, ts.baseline_race_action(engine.observation(race)))
    value = ts.expected_apex_points_at_finish(race)
    grid = list(active.starting_grid)
    finish_prepared_race(state, active, COEFFS)
    return value, grid


def plan_decisions(state, driver, plan, worn, step):
    """Component actions for `driver` at plan step `step` (0 = decision race)."""
    comps = state.power_units[driver]
    if plan == "BUNDLE_NOW":
        targets = set(worn) if step == 0 else set()
    elif plan == "DISTRIBUTE":
        targets = {worn[step]} if step < len(worn) else set()
    elif plan == "DEFER_BUNDLE":
        targets = set(worn) if step == 1 else set()
    else:
        targets = set()
    out = []
    for name, comp in comps.items():
        replace = name in targets or comp.wear > LIMIT
        if replace and state.resource_inventory[driver_team(driver)].get(pu_rules.stock_key(name), 0) <= 0:
            replace = comp.wear > LIMIT  # no stock: only a forced change (raises if impossible)
        out.append({"driver": driver, "component": name, "action": "REPLACE" if replace else "USE"})
    return out


def season_value(start_state, driver, plan, worn, schedules):
    vals, grids = [], []
    for schedule_set in schedules:
        state = copy.deepcopy(start_state)
        total, first_grid = 0.0, None
        for step in range(len(state.calendar) - state.race_index):
            decisions = rule_decisions(state, skip=(driver, None)) + plan_decisions(state, driver, plan, worn, step)
            value, grid = run_race(state, decisions, schedule_set[step])
            total += value
            first_grid = first_grid or grid
        vals.append(total)
        grids.append(first_grid)
    return vals, grids[0]


def seed_of(*parts) -> int:
    import hashlib
    return int(hashlib.sha256(repr(parts).encode()).hexdigest()[:8], 16)


def schedules_for(state, key, k):
    n = len(coef.race_format(COEFFS)["decision_laps"])
    model = coef.race_format(COEFFS)["neutralization"]
    races = len(state.calendar) - state.race_index
    return [[engine.neutralization_schedule(seed_of("b8-eval", key, j, r), n, model) for r in range(races)]
            for j in range(k)]


def compare(state, driver, worn, schedules):
    q, grids = {}, {}
    for plan in PLANS:
        q[plan], grids[plan] = season_value(state, driver, plan, worn, schedules)
    means = {p: st.mean(v) for p, v in q.items()}
    best = max(means, key=means.get)

    def diff(a, b):
        d = [x - y for x, y in zip(q[a], q[b])]
        se = st.pstdev(d) / math.sqrt(len(d)) if len(d) > 1 else 0.0
        return {"mean": round(st.mean(d), 3), "ci95": [round(st.mean(d) - 1.96 * se, 3), round(st.mean(d) + 1.96 * se, 3)]}
    return {"values": {p: round(v, 3) for p, v in means.items()}, "best": best,
            "bundle_minus_distribute": diff("BUNDLE_NOW", "DISTRIBUTE"),
            "now_minus_defer": diff("BUNDLE_NOW", "DEFER_BUNDLE"),
            "bundle_minus_no_change": diff("BUNDLE_NOW", "NO_CHANGE"),
            "first_race_grid_by_plan": grids,
            "penalty_places_now": {"BUNDLE_NOW": pu_rules.penalty_for(state, driver, worn),
                                   "DISTRIBUTE": pu_rules.penalty_for(state, driver, worn[:1])}}


def find_decision_state(spec):
    """Walk the published-rule season; return the first decision state (or None)."""
    state = new_championship_state(calendar=spec["calendar"], resource_inventory=initial_inventory(COEFFS))
    model = coef.race_format(COEFFS)["neutralization"]
    n = len(coef.race_format(COEFFS)["decision_laps"])
    while state.race_index < len(state.calendar) - 2:
        for driver in TEAM_DRIVERS["Apex"]:
            worn = sorted((c for c, comp in state.power_units[driver].items() if comp.wear >= WORN),
                          key=lambda c: -state.power_units[driver][c].wear)
            if len(worn) >= 2:
                return state, driver, worn
        events = engine.neutralization_schedule(seed_of("b8-history", spec["id"], state.race_index), n, model)
        run_race(state, rule_decisions(state), events)
    return None


def synthetic_state(spec):
    """Declared SYNTHETIC generator (coverage, not F1 incidence): published-rule history up to a
    race index r in {2,3,4}; then Apex A's per-type usage is drawn from {1,2} elements (team stock
    reduced to match) and wear from U(0.35, 0.85). A decision state needs >= 2 worn components."""
    import random
    rng = random.Random(seed_of("b8-generator", spec["id"]))
    target = rng.choice((2, 3, 4))
    state = new_championship_state(calendar=spec["calendar"], resource_inventory=initial_inventory(COEFFS))
    model = coef.race_format(COEFFS)["neutralization"]
    n = len(coef.race_format(COEFFS)["decision_laps"])
    while state.race_index < target:
        events = engine.neutralization_schedule(seed_of("b8-history", spec["id"], state.race_index), n, model)
        run_race(state, rule_decisions(state), events)
    driver = "Apex A"
    team = driver_team(driver)
    for name, comp in state.power_units[driver].items():
        used = rng.choice((1, 2))
        extra = used - 1 - comp.replacements
        comp.replacements = used - 1
        comp.wear = round(rng.uniform(0.35, 0.85), 3)
        key = pu_rules.stock_key(name)
        state.resource_inventory[team][key] = max(0, state.resource_inventory[team][key] - max(0, extra))
    worn = sorted((c for c, comp in state.power_units[driver].items() if comp.wear >= WORN),
                  key=lambda c: -state.power_units[driver][c].wear)
    state.validate()
    return (state, driver, worn) if len(worn) >= 2 else None


def job(args):
    spec, k, generator = args
    found = synthetic_state(spec) if generator == "synthetic" else find_decision_state(spec)
    if found is None:
        return {"scenario": spec["id"], "decision_state": False}
    state, driver, worn = found
    schedules = schedules_for(state, spec["id"], k)
    base = compare(state, driver, worn, schedules)
    swapped_state = copy.deepcopy(state)
    i = state.race_index
    swapped_state.calendar[i], swapped_state.calendar[i + 1] = state.calendar[i + 1], state.calendar[i]
    swapped = compare(swapped_state, driver, worn, schedules)
    track = lambda r: {"name": r.name, "archetype": r.archetype, "overtaking_difficulty": r.overtaking_difficulty,
                       "power_unit_stress": r.power_unit_stress, "tyre_degradation": r.tyre_degradation}
    pref = lambda c: "NOW" if c["now_minus_defer"]["mean"] > 0 else "DEFER"
    clear = lambda c: c["now_minus_defer"]["ci95"][0] > 0 or c["now_minus_defer"]["ci95"][1] < 0
    return {"scenario": spec["id"], "decision_state": True, "race_index": i, "driver": driver,
            "worn": {c: round(state.power_units[driver][c].wear, 3) for c in worn},
            "elements_used": {c: pu_rules.elements_used(state, driver, c) for c in worn},
            "tracks": [track(state.calendar[i]), track(state.calendar[i + 1])],
            "original_order": base, "swapped_order": swapped,
            "timing_preference": {"original": pref(base), "swapped": pref(swapped),
                                  "reversal": pref(base) != pref(swapped) and clear(base) and clear(swapped),
                                  "both_clear": clear(base) and clear(swapped)}}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--calendars", type=int, default=40)
    parser.add_argument("--futures", type=int, default=8)
    parser.add_argument("--workers", type=int, default=10)
    parser.add_argument("--offset", type=int, default=0, help="held-out set: use calendars [offset, offset+N)")
    parser.add_argument("--generator", choices=("synthetic", "natural"), default="synthetic")
    args = parser.parse_args()
    specs = sc.generate_specs(args.offset + args.calendars)[args.offset:]
    with mp.Pool(args.workers) as pool:
        rows = pool.map(job, [(s, args.futures, args.generator) for s in specs])
    found = [r for r in rows if r["decision_state"]]
    summary = {
        "calendars": len(rows), "decision_states": len(found),
        "natural_frequency": round(len(found) / len(rows), 3),
        "best_plan_counts": {p: sum(1 for r in found if r["original_order"]["best"] == p) for p in PLANS},
        "bundle_vs_distribute": {
            "bundle_better_clear": sum(1 for r in found if r["original_order"]["bundle_minus_distribute"]["ci95"][0] > 0),
            "distribute_better_clear": sum(1 for r in found if r["original_order"]["bundle_minus_distribute"]["ci95"][1] < 0),
            "near_tie": sum(1 for r in found if abs(r["original_order"]["bundle_minus_distribute"]["mean"]) < NEAR_TIE)},
        "timing": {"reversals": sum(1 for r in found if r["timing_preference"]["reversal"]),
                   "clear_no_change": sum(1 for r in found if r["timing_preference"]["both_clear"]
                                          and not r["timing_preference"]["reversal"]),
                   "unclear": sum(1 for r in found if not r["timing_preference"]["both_clear"])},
        "settings": {"futures": args.futures, "worn_threshold": WORN, "rules": pu_rules.FIA_MODE,
                     "offset": args.offset, "generator": args.generator}}
    name = f"b8_penalties_{args.generator}" + ("" if args.offset == 0 else f"_heldout_{args.offset}") + ".json"
    (HERE / "results" / name).write_text(json.dumps({"summary": summary, "rows": rows}, indent=1))
    print(json.dumps(summary, indent=1))


if __name__ == "__main__":
    main()
