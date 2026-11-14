#!/usr/bin/env python3
"""Opponent-model sensitivity: evaluate written policies against alternative rival pit policies.

Analysis only: inside each worker the engine's rival pit rule is swapped for a variant; the
benchmark environment and its public rival rule are unchanged. Agent planners that embed a
model of the public rival rule are thereby evaluated against rivals that behave differently.

Variants (all public-information-plausible strategies a real rival could use):
  public          the published rule (control)
  early_stoppers  pit 3 laps before tyre life; SC at age >= 5, VSC at age >= 8
  late_stoppers   run 2 laps past tyre life; SC at age >= 9, VSC at age >= 12
  sc_opportunists stop under any SC/VSC with age >= 3 and >= 9 laps left; otherwise public rule
Usage: python3 analysis/rival_sensitivity.py <runs.json> [--seeds 60] [--workers 10]
runs.json: [{"name", "policy", "component_fn", "race_fn"}]
"""

from __future__ import annotations

import argparse
import json
import math
import multiprocessing as mp
import statistics as st
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import written_policy_eval as wpe  # noqa: E402
from f1pitwall import engine  # noqa: E402

PUBLIC = engine._rival_action


def make_variant(name):
    if name == "public":
        return PUBLIC

    def rule(car, status, step_index, decision_count=len(engine.DECISION_LAPS), tyres=None, laps_remaining=None):
        if tyres is None:
            return PUBLIC(car, status, step_index, decision_count, tyres, laps_remaining)
        life = tyres["compounds"][car["compound"]]["life_laps"]
        needs_second = tyres["two_compound_rule"] and len(set(car["compounds_used"])) < 2
        last = step_index == decision_count - 1
        if name == "early_stoppers":
            pit = ((status == "SC" and car["tyre_age"] >= 5) or (status == "VSC" and car["tyre_age"] >= 8)
                   or (car["tyre_age"] >= life - 3 and not last) or (needs_second and last))
        elif name == "late_stoppers":
            pit = ((status == "SC" and car["tyre_age"] >= 9) or (status == "VSC" and car["tyre_age"] >= 12)
                   or (car["tyre_age"] >= life + 2 and not last) or (needs_second and last))
        elif name == "sc_opportunists":
            if status in ("SC", "VSC") and car["tyre_age"] >= 3 and laps_remaining >= 9:
                pit = True
            else:
                return PUBLIC(car, status, step_index, decision_count, tyres, laps_remaining)
        else:
            raise ValueError(name)
        if not pit:
            return "STAY"
        return "PIT_" + engine.rival_compound(car, laps_remaining, tyres)
    return rule


VARIANTS = ("public", "early_stoppers", "late_stoppers", "sc_opportunists")


def job(args):
    variant, season_args = args
    engine._rival_action = make_variant(variant)
    result = wpe.play_season(season_args)
    result["variant"] = variant
    return result


def _guard_runtime():
    from _runtime import require_runtime_python
    require_runtime_python()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("runs")
    parser.add_argument("--seeds", type=int, default=60)
    parser.add_argument("--workers", type=int, default=10)
    parser.add_argument("--out", default=str(HERE / "results" / "rep_rival_sensitivity.json"))
    args = parser.parse_args()
    runs = json.loads(Path(args.runs).read_text())
    seeds = wpe.eval_seeds(args.seeds)
    jobs = []
    for run in runs:
        policy = str(Path(run["policy"]).resolve())
        fns = (run["component_fn"], run["race_fn"])
        wpe.POLICY_PATH, wpe.COMPONENT_FN, wpe.RACE_FN = policy, fns[0], fns[1]
        plan = wpe.components_plan(policy, "gemini")
        for variant in VARIANTS:
            for s in seeds:
                jobs.append((variant, (policy, run["name"], "gemini", "gemini", s, plan, fns)))
    first = runs[0]
    wpe.POLICY_PATH, wpe.COMPONENT_FN, wpe.RACE_FN = str(Path(first["policy"]).resolve()), first["component_fn"], first["race_fn"]
    base_plan = wpe.components_plan(wpe.POLICY_PATH, "baseline")
    for variant in VARIANTS:
        for s in seeds:
            jobs.append((variant, (wpe.POLICY_PATH, "public_baseline", "baseline", "baseline", s, base_plan,
                                   (first["component_fn"], first["race_fn"]))))
    with mp.Pool(args.workers) as pool:
        rows = pool.map(job, jobs, chunksize=2)
    table = {}
    for r in rows:
        table.setdefault((r["policy"], r["variant"]), {})[r["seed"]] = r["points"]
    out = {"seeds": len(seeds), "rows": [{k: r[k] for k in ("policy", "variant", "seed", "points")} for r in rows]}
    Path(args.out).write_text(json.dumps(out, indent=1))
    names = [r["name"] for r in runs] + ["public_baseline"]
    print("| Policy | " + " | ".join(VARIANTS) + " | Max shift vs public |")
    print("|---|" + "---:|" * (len(VARIANTS) + 1))
    for n in names:
        cells, means = [], {}
        for v in VARIANTS:
            vals = list(table[(n, v)].values())
            means[v] = st.mean(vals)
            cells.append(f"{means[v]:.1f} ± {st.pstdev(vals) / math.sqrt(len(vals)):.1f}")
        shift = max(abs(means[v] - means["public"]) for v in VARIANTS)
        print(f"| {n} | " + " | ".join(cells) + f" | {shift:.1f} |")
    print("\nPaired gap of each agent policy over the public baseline, by rival variant (± s.e.):")
    for n in names[:-1]:
        cells = []
        for v in VARIANTS:
            d = [table[(n, v)][s] - table[("public_baseline", v)][s] for s in table[(n, v)]]
            cells.append(f"{v}: {st.mean(d):+.1f} ± {st.pstdev(d) / math.sqrt(len(d)):.1f}")
        print(f"  {n}: " + "; ".join(cells))


if __name__ == "__main__":
    _guard_runtime()
    main()
