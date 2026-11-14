#!/usr/bin/env python3
"""B1 analysis: value of in-race compound choice (levels b and c).

For a race start state, exact expectimax over the per-decision SC/VSC/GREEN
tree (published probabilities; the status is observed before each decision)
and over retirements (exact Poisson-binomial expectation). Apex chooses among
all joint legal actions. Rivals follow their public rule. No seeds are read.

Compared, all as exact expectations on the same race:
  optimal        expectimax over STAY / PIT_SOFT / PIT_MEDIUM / PIT_HARD per driver
  compound_blind expectimax with Apex stops fitting MEDIUM (HARD only when needed for the
                 two-compound rule); stop timing is still optimized; rivals unchanged
  baseline       the public heuristic (solution/play.py)
  always_stay    no stops (breaks the two-compound rule)
Ablations re-run optimal and baseline with the tyre cliff or the two-compound rule off.

Usage: python3 analysis/race_expectimax.py [--scenarios 24] [--workers 10]
Writes analysis/results/b1_compound_value.json
"""

from __future__ import annotations

import argparse
import json
import multiprocessing as mp
import sys
import time
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import track_a_solver as ts  # noqa: E402
from f1pitwall import engine  # noqa: E402

RACE_INDICES = (0, 3, 6)
OUTPUT = "b2_race_value"
ABLATIONS = ("tyre_cliff", "two_compound_rule", "pit_loss_by_track", "double_stack_queue", "tyre_warmup")


def _joint(node, restrict):
    if restrict is None:
        legal = engine.legal_actions(node)
        return [{"driver_a": a, "driver_b": b} for a in legal for b in legal]
    a_opts, b_opts = restrict(node, "Apex A"), restrict(node, "Apex B")
    return [{"driver_a": a, "driver_b": b} for a in a_opts for b in b_opts]


def compound_blind(node, name):
    """Rule-aware but compound-blind: a stop fits MEDIUM, or HARD if MEDIUM is the only compound used."""
    car = next(c for c in node["cars"] if c["name"] == name)
    return ["STAY", "PIT_HARD" if set(car["compounds_used"]) == {"MEDIUM"} else "PIT_MEDIUM"]


def expectimax(race, restrict=None):
    """(expected Apex points, optimal action for each status at the first decision)."""

    def value(node):
        if node["step"] == len(node["events"]):
            return ts.expected_apex_points_at_finish(node)
        total = 0.0
        for status, prob in ts.event_probs(node):
            best = float("-inf")
            for action in _joint(node, restrict):
                child = ts._copy_race(node)
                child["events"][child["step"]] = status
                engine.step(child, action)
                best = max(best, value(child))
            total += prob * best
        return total

    first = {}
    total = 0.0
    for status, prob in ts.event_probs(race):
        scored = []
        for action in _joint(race, restrict):
            child = ts._copy_race(race)
            child["events"][child["step"]] = status
            engine.step(child, action)
            scored.append((value(child), action))
        best = max(scored, key=lambda item: item[0])
        first[status] = {"action": best[1], "value": best[0],
                         "table": {f"{a['driver_a']}/{a['driver_b']}": v for v, a in scored}}
        total += prob * best[0]
    return total, first


def always_stay(observation):
    return {"driver_a": "STAY", "driver_b": "STAY"}


def race_job(args):
    import scenarios as sc
    from f1pitwall import coefficients as coef
    spec, index, mechanic = args
    # Exact single-race expectimax is only feasible in the 3-decision short format (B1/B2 analyses).
    coeffs = coef.ablate(coef.DEFAULT, "long_race_format", *([mechanic] if mechanic else []))
    solver = ts.Solver(coeffs)
    from f1pitwall.championship import new_championship_state
    from f1pitwall.championship_transition import initial_inventory
    state = new_championship_state(calendar=spec["calendar"], resource_inventory=initial_inventory(coeffs))
    for _ in range(index):  # public-rule history to reach race `index`
        state = ts.after_race(ts.prepare(state, solver.choose(state, "rival_rule"), coeffs), coeffs)
    prepared = ts.prepare(state, solver.choose(state, "rival_rule"), coeffs)
    race = ts.prepared_race_state(prepared, coeffs)
    started = time.time()
    out = {"scenario": spec["id"], "race_index": index, "mechanic": mechanic,
           "track": [prepared.calendar[index].archetype, prepared.calendar[index].tyre_degradation],
           "apex_start": {k: (v["compound"], v["tyre_age"]) for k, v in engine.observation(race)["drivers"].items()}}
    out["optimal"], first = expectimax(race)
    out["optimal_first"] = {s: f"{v['action']['driver_a']}/{v['action']['driver_b']}" for s, v in first.items()}
    if mechanic is None:
        out["first_tables"] = {s: v["table"] for s, v in first.items()}
    out["baseline"] = ts.expected_race_value(race)
    if mechanic is None:
        out["compound_blind"], _ = expectimax(race, compound_blind)
        out["always_stay"] = ts.expected_race_value(race, always_stay)
    out["seconds"] = round(time.time() - started, 1)
    return out


def main():
    import scenarios as sc
    parser = argparse.ArgumentParser()
    parser.add_argument("--scenarios", type=int, default=24)
    parser.add_argument("--workers", type=int, default=10)
    args = parser.parse_args()
    specs = sc.generate_specs(args.scenarios)
    jobs = [(s, i, m) for s in specs for i in RACE_INDICES for m in (None,) + ABLATIONS]
    started = time.time()
    with mp.Pool(args.workers) as pool:
        results = pool.map(race_job, jobs)
    path = HERE / "results" / f"{OUTPUT}.json"
    path.write_text(json.dumps({"races": results, "wall_seconds": round(time.time() - started, 1)}, indent=1))
    summarize(results)


def summarize(results):
    import statistics as st
    base = [r for r in results if r["mechanic"] is None]

    def line(label, values):
        return (f"| {label} | {st.mean(values):.2f} | {st.median(values):.2f} | {max(values):.2f} | "
                f"{sum(v > 0.5 for v in values)}/{len(values)} |")

    print(f"Races: {len(base)}")
    print("| Comparison (points per race) | Mean | Median | Max | Races > 0.5 pt |\n|---|---:|---:|---:|---:|")
    print(line("Optimal − compound-blind optimal timing (value of compound choice)",
               [r["optimal"] - r["compound_blind"] for r in base]))
    print(line("Compound-blind optimal timing − baseline", [r["compound_blind"] - r["baseline"] for r in base]))
    print(line("Optimal − baseline heuristic", [r["optimal"] - r["baseline"] for r in base]))
    print(line("Baseline − always STAY", [r["baseline"] - r["always_stay"] for r in base]))
    print("\n| Mechanic off | Optimal − baseline (b) | First-decision policy changes (c) | Real-world loss of the ablated first decision: mean / max (c) |")
    print("|---|---:|---:|---:|")
    probs = dict(ts.EVENT_PROBS)  # short format
    for mech in ABLATIONS:
        rows = {(r["scenario"], r["race_index"]): r for r in results if r["mechanic"] == mech}
        if not rows:
            continue
        gap = st.mean(rows[k]["optimal"] - rows[k]["baseline"] for k in rows)
        changed = sum(rows[(r["scenario"], r["race_index"])]["optimal_first"] != r["optimal_first"] for r in base)
        losses = []
        for r in base:
            other = rows[(r["scenario"], r["race_index"])]["optimal_first"]
            losses.append(sum(probs[s] * (max(r["first_tables"][s].values()) - r["first_tables"][s][other[s]])
                              for s in probs))
        print(f"| {mech} | {gap:.2f} | {changed}/{len(base)} | {st.mean(losses):.2f} / {max(losses):.2f} |")
    stacks = Counter((s, a.split("/")[0] != "STAY" and a.split("/")[1] != "STAY")
                     for r in base for s, a in r["optimal_first"].items())
    print("Optimal first decision is a double stack, by status:",
          {s: f"{stacks[(s, True)]}/{stacks[(s, True)] + stacks[(s, False)]}" for s in probs})
    compounds = Counter(a for r in base for a in r["optimal_first"].values())
    print("Optimal first-decision actions (all statuses):", dict(compounds.most_common()))


if __name__ == "__main__":
    main()
