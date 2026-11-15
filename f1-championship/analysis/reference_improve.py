#!/usr/bin/env python3
"""Bounded reference-improvement study (1.1.0; no simulator, reward or seed change).

Variants of solution/reference.py, each changing one knob of the reference itself:
  base        as shipped: one-step lookahead, 32 futures, baseline continuation; plan 48 paths, 4 sweeps
  f16, f64    search budget: 16 / 64 futures per decision
  two_step    the top-3 one-step actions are re-scored with a continuation that plays a one-step
              lookahead (8 futures) at the NEXT decision, then the baseline (16 outer futures)
  plan_rich   component planning budget: 96 paths per race value, 8 sweeps
Seeds: development set = 10 seeds, held-out set = 20 seeds, disjoint from each other and from the
100 evaluation seeds of reference_eval.py. Development is used to pick; held-out reports.
Usage: scripts/py312 analysis/reference_improve.py --set dev|heldout [--variants ...] [--workers 10]
Writes analysis/results/reference_improve_<set>.json
"""

from __future__ import annotations

import argparse
import json
import math
import multiprocessing as mp
import random
import statistics as st
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
TASK = HERE.parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(TASK / "solution"))

VARIANTS = ("base", "f16", "f64", "two_step", "plan_rich")
SEEDS = {"dev": [9000 + 17 * i for i in range(10)], "heldout": [9500 + 31 * i for i in range(20)]}


def configure(variant):
    import reference as R
    if variant in ("f16", "f64"):  # rollout_action binds futures=FUTURES at definition: wrap it
        n = 16 if variant == "f16" else 64
        fixed = R.rollout_action
        R.FUTURES = n
        R.rollout_action = lambda race, futures=n: fixed(race, futures=futures)
    elif variant == "plan_rich":
        R.PLAN_PATHS, R.PLAN_SWEEPS = 96, 8
    elif variant == "two_step":
        base_rollout = R.rollout_action

        def inner_policy(race):
            if race["step"] >= len(race["events"]):
                return None
            action, _ = base_rollout(race, futures=8)
            return action

        def two_step(race, futures=16):
            _, table = base_rollout(race, futures=futures)
            top = sorted(table, key=table.get, reverse=True)[:3]
            seen = race["events"][:race["step"] + 1]
            rng = random.Random(f"two_step|{len(race['events'])}|{race['step']}|{seen}")
            paths = R.engine.sample_future_statuses(rng, race, futures)
            best, best_value = None, float("-inf")
            for key in top:
                a, b = key.split("/")
                action, total = {"driver_a": a, "driver_b": b}, 0.0
                for future in paths:
                    child = R.copy_race(race)
                    R.engine.step(child, action)
                    child["events"][child["step"]:] = future
                    if child["step"] < len(child["events"]):
                        R.engine.step(child, inner_policy(child))
                    total += R.finish_with_baseline(child)
                if total > best_value + 1e-9:
                    best, best_value = action, total
            return best, table
        R.rollout_action = two_step
    return R


def play(args):
    variant, seed = args
    R = configure(variant)
    from f1pitwall.championship_contract import ChampionshipSession
    session = ChampionshipSession(base_seed=seed)
    player = R.Reference()
    started, n = time.time(), 0
    while session.decision_type != "CHAMPIONSHIP_COMPLETE":
        obs = json.loads(json.dumps(session.observation()))
        n += 1
        obs["decision_id"] = f"d{n:03d}"
        session.submit(player.decide(obs))
    return {"variant": variant, "seed": seed, "points": session.state.team_points["Apex"],
            "seconds": round(time.time() - started, 1), **player.stats}


def main():
    from _runtime import require_runtime_python
    require_runtime_python()
    parser = argparse.ArgumentParser()
    parser.add_argument("--set", choices=tuple(SEEDS), required=True)
    parser.add_argument("--variants", nargs="+", default=list(VARIANTS))
    parser.add_argument("--workers", type=int, default=10)
    args = parser.parse_args()
    seeds = SEEDS[args.set]
    variants = ["base"] + [v for v in args.variants if v != "base"]
    with mp.Pool(args.workers) as pool:
        rows = pool.map(play, [(v, s) for v in variants for s in seeds], chunksize=1)
    by = {(r["variant"], r["seed"]): r for r in rows}
    summary = {}
    for v in variants:
        diff = [by[(v, s)]["points"] - by[("base", s)]["points"] for s in seeds]
        summary[v] = {"mean_points": st.mean(by[(v, s)]["points"] for s in seeds),
                      "gain_vs_base": round(st.mean(diff), 2),
                      "ci95": [round(st.mean(diff) - 1.96 * st.stdev(diff) / math.sqrt(len(diff)), 2),
                               round(st.mean(diff) + 1.96 * st.stdev(diff) / math.sqrt(len(diff)), 2)] if len(diff) > 1 else None,
                      "better_equal_worse": [sum(d > 0 for d in diff), sum(d == 0 for d in diff), sum(d < 0 for d in diff)],
                      "seconds_per_season": round(st.mean(by[(v, s)]["seconds"] for s in seeds), 1),
                      "max_seconds": max(by[(v, s)]["seconds"] for s in seeds),
                      "fallbacks": sum(by[(v, s)]["fallbacks"] for s in seeds)}
    out = {"set": args.set, "seeds": seeds, "rows": rows, "summary": summary}
    (HERE / "results" / f"reference_improve_{args.set}.json").write_text(json.dumps(out, indent=1))
    print(json.dumps(summary, indent=1))


if __name__ == "__main__":
    main()
