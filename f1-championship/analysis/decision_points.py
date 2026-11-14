#!/usr/bin/env python3
"""B3 analysis: how many decision points per race are strategically meaningful?

Trajectories: for each sampled race, the public baseline policy plays K fixed public
event paths. At every decision on a trajectory we score all joint legal Apex actions:

  Q(a) = mean over M fixed public future event paths (shared by every action, common
         random numbers) of the exact retirement-expected Apex points when a is played
         now and the baseline policy plays the rest of the race.

Per decision:
  stakes = Q(a*) - Q(STAY/STAY)   # does acting matter here at all?
  gain   = Q(a*) - Q(baseline)    # one-step improvement available over the rule
where a* is selected on one set of M futures and every Q above is re-estimated on an
independent set of M futures, so the maximum over actions is not biased upward.
A decision is counted "meaningful" if stakes > 0.5 pt, and "baseline-improvable" if gain > 0.25 pt.
These are one-step-lookahead statistics with a baseline continuation (lower bounds on the
value of full replanning). No hidden seeds are read: all event paths are public CRN paths.

Usage: python3 analysis/decision_points.py [--scenarios 24] [--workers 10]
Writes analysis/results/b3_decision_points.json
"""

from __future__ import annotations

import argparse
import json
import multiprocessing as mp
import random
import statistics as st
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import track_a_solver as ts  # noqa: E402
from f1pitwall import engine  # noqa: E402

RACE_INDICES = (0, 3, 6)
FORMATS = ("long", "b3")
OUTPUT = "b4_decision_points"
TRAJECTORIES = 4
FUTURES = 48
MEANINGFUL = 0.5
IMPROVABLE = 0.25


def _paths(remaining, probs, samples, tag):
    rng = random.Random(f"{tag}|{remaining}|{sorted(probs.items())}")
    green, vsc = probs["GREEN"], probs["GREEN"] + probs["VSC"]
    return [["GREEN" if (u := rng.random()) < green else "VSC" if u < vsc else "SC" for _ in range(remaining)]
            for _ in range(samples)]


def q_values(node, futures, keys=None):
    legal = engine.legal_actions(node)
    out = {}
    for a in legal:
        for b in legal:
            if keys is not None and f"{a}/{b}" not in keys:
                continue
            action = {"driver_a": a, "driver_b": b}
            total = 0.0
            for future in futures:
                child = ts._copy_race(node)
                engine.step(child, action)
                child["events"][child["step"]:] = future
                while child["step"] < len(child["events"]):
                    engine.step(child, ts.baseline_race_action(engine.observation(child)))
                total += ts.expected_apex_points_at_finish(child)
            out[f"{a}/{b}"] = total / len(futures)
    return out


def race_job(args):
    import scenarios as sc  # noqa: F401
    from f1pitwall import coefficients as coef
    from f1pitwall.championship import new_championship_state
    from f1pitwall.championship_transition import initial_inventory
    spec, index, fmt = args
    coeffs = {"long": coef.DEFAULT,  # B4: long format with SC/VSC dynamics
              "b3": coef.ablate(coef.DEFAULT, "neutralization_dynamics"),
              "short": coef.ablate(coef.DEFAULT, "long_race_format")}[fmt]
    solver = ts.Solver(coeffs)
    state = new_championship_state(calendar=spec["calendar"], resource_inventory=initial_inventory(coeffs))
    for _ in range(index):
        state = ts.after_race(ts.prepare(state, solver.choose(state, "rival_rule"), coeffs), coeffs)
    prepared = ts.prepare(state, solver.choose(state, "rival_rule"), coeffs)
    race = ts.prepared_race_state(prepared, coeffs)
    probs = engine.event_probabilities(race)
    n = len(race["events"])
    started = time.time()
    decisions = []
    for k, path in enumerate(ts.crn_event_paths(race, TRAJECTORIES)):
        node = ts._copy_race(race)
        node["events"] = list(path)
        while node["step"] < n:
            select = ts.public_futures(node, FUTURES, "select")
            q_sel = q_values(node, select)
            best_key = max(q_sel, key=q_sel.get)
            obs = engine.observation(node)
            base = ts.baseline_race_action(obs)
            base_key = f"{base['driver_a']}/{base['driver_b']}"
            # Score on independent futures so the max over actions is not biased upward.
            evaluate = ts.public_futures(node, FUTURES, "evaluate")
            q = q_values(node, evaluate, keys={best_key, base_key, "STAY/STAY"})
            decisions.append({"trajectory": k, "decision": node["step"] + 1, "lap": obs["lap"],
                              "status": obs["track_status"], "best": best_key, "baseline": base_key,
                              "stakes": q[best_key] - q["STAY/STAY"], "gain": q[best_key] - q[base_key],
                              "selection_spread": q_sel[best_key] - min(q_sel.values())})
            engine.step(node, base)
    return {"scenario": spec["id"], "race_index": index, "format": fmt, "decisions_per_race": n,
            "decisions": decisions, "seconds": round(time.time() - started, 1)}


def summarize(results):
    lines = ["| Format | Decisions per race | Meaningful per race (stakes > 0.5) | Baseline-improvable per race (gain > 0.25) | Mean gain per decision | Max gain |",
             "|---|---:|---:|---:|---:|---:|"]
    for fmt in ("short", "b3", "long"):
        rows = [r for r in results if r["format"] == fmt]
        if not rows:
            continue
        per_traj_meaning, per_traj_improve, gains = [], [], []
        for r in rows:
            for k in range(TRAJECTORIES):
                ds = [d for d in r["decisions"] if d["trajectory"] == k]
                per_traj_meaning.append(sum(d["stakes"] > MEANINGFUL for d in ds))
                per_traj_improve.append(sum(d["gain"] > IMPROVABLE for d in ds))
                gains += [d["gain"] for d in ds]
        lines.append(f"| {fmt} | {rows[0]['decisions_per_race']} | {st.mean(per_traj_meaning):.2f} "
                     f"(median {st.median(per_traj_meaning):.0f}) | {st.mean(per_traj_improve):.2f} "
                     f"(median {st.median(per_traj_improve):.0f}) | {st.mean(gains):.3f} | {max(gains):.2f} |")
    long_rows = [d for r in results if r["format"] == "long" for d in r["decisions"]]  # B4
    if long_rows:
        lines += ["", "Long format, by decision index (mean stakes / mean gain / share meaningful):", "",
                  "| Decision | Lap | Mean stakes | Mean gain | Meaningful share | Improvable share |", "|---:|---:|---:|---:|---:|---:|"]
        for i in sorted({d["decision"] for d in long_rows}):
            ds = [d for d in long_rows if d["decision"] == i]
            lines.append(f"| {i} | {ds[0]['lap']} | {st.mean(d['stakes'] for d in ds):.2f} | "
                         f"{st.mean(d['gain'] for d in ds):.3f} | {sum(d['stakes'] > MEANINGFUL for d in ds) / len(ds):.2f} | "
                         f"{sum(d['gain'] > IMPROVABLE for d in ds) / len(ds):.2f} |")
        lines += ["", "| Status | Decisions | Mean gain | Improvable share |", "|---|---:|---:|---:|"]
        for status in ("GREEN", "VSC", "SC"):
            ds = [d for d in long_rows if d["status"] == status]
            if ds:
                lines.append(f"| {status} | {len(ds)} | {st.mean(d['gain'] for d in ds):.3f} | "
                             f"{sum(d['gain'] > IMPROVABLE for d in ds) / len(ds):.2f} |")
    return "\n".join(lines)


def main():
    import scenarios as sc
    parser = argparse.ArgumentParser()
    parser.add_argument("--scenarios", type=int, default=24)
    parser.add_argument("--workers", type=int, default=10)
    args = parser.parse_args()
    specs = sc.generate_specs(args.scenarios)
    jobs = [(s, i, f) for s in specs for i in RACE_INDICES for f in FORMATS]
    started = time.time()
    with mp.Pool(args.workers) as pool:
        results = pool.map(race_job, jobs)
    out = {"trajectories": TRAJECTORIES, "futures": FUTURES, "races": results,
           "wall_seconds": round(time.time() - started, 1)}
    (HERE / "results" / f"{OUTPUT}.json").write_text(json.dumps(out, indent=1))
    print(f"wall {out['wall_seconds']}s")
    print(summarize(results))


if __name__ == "__main__":
    main()
