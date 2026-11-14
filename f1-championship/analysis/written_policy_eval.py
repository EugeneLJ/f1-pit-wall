#!/usr/bin/env python3
"""Evaluate an agent-written policy across many seeds (paired, same task distribution).

The Harbor task fixes the calendar and varies the hidden seed (SC/VSC schedule and
retirement draws). An agent-written policy is a function of public observations, so
its expected performance is estimated by replaying full seasons on many fresh seeds
(never the hidden evaluation seed). Every policy sees the same seeds (paired).

Policies (component part + race part):
  gemini            the agent's decide_component + decide_strategy
  baseline          public heuristic (solution/play.py) for both parts
  gemini_comp+base  Gemini components, public baseline race play   (attribution)
  base_comp+gemini  public baseline components, Gemini race play   (attribution)
  rule+base         replacement-rule components, baseline race play
  greedy+base       greedy components (CRN race values), baseline race play
  gemini_comp+rollout  Gemini components with the B4 public-information rollout race reference
  gemini_patched_*  Gemini policy with exactly one confirmed rule-level flaw removed (analysis only)
The reward column uses the verifier's provisional P0 formula with D = do-nothing on the same seed.
Usage: python3 analysis/written_policy_eval.py <policy.py> [--seeds 200] [--rollout-seeds 60] [--workers 10]
"""

from __future__ import annotations

import argparse
import copy
import importlib.util
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

import track_a_solver as ts  # noqa: E402
from f1pitwall import coefficients as coef  # noqa: E402
from f1pitwall import engine  # noqa: E402
from f1pitwall.championship_contract import ChampionshipSession  # noqa: E402

HIDDEN = json.loads((TASK / "tests" / "hidden_seed.json").read_text())["base_seed"]
UPPER = (engine.POINTS[0] + engine.POINTS[1]) * 8
POLICY_PATH = None
COMPONENT_FN = "decide_component"
RACE_FN = "decide_strategy"
_BOT = None


def bot():
    """Agent policy module for POLICY_PATH (cached per path: one process may evaluate several)."""
    global _BOT
    if _BOT is None or _BOT.__file__ != POLICY_PATH:
        from importlib.machinery import SourceFileLoader
        spec = importlib.util.spec_from_file_location("agent_policy", POLICY_PATH,
                                                      loader=SourceFileLoader("agent_policy", POLICY_PATH))
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        _BOT = module
    return _BOT


def eval_seeds(count):
    rng = random.Random("written-policy-eval-seeds")
    seeds = []
    while len(seeds) < count:
        s = rng.getrandbits(62)
        if s != HIDDEN:
            seeds.append(s)
    return seeds


# ---- component parts (all deterministic given the calendar; computed per season) ----

def _quiet(fn, *args):
    """Agent policies print progress; keep evaluation output readable."""
    import contextlib
    import io
    with contextlib.redirect_stdout(io.StringIO()):
        return fn(*args)


def comp_gemini(obs, session):
    return _quiet(getattr(bot(), COMPONENT_FN), obs)


def comp_baseline(obs, session):
    from play import component_action
    return component_action(obs)


def _comp_from_solver(rule):
    def choose(obs, session):
        solver = ts.Solver(coef.DEFAULT)
        option = solver.choose(session.state, rule)
        return {"type": "COMPONENT_DECISION",
                "decisions": [{"driver": d, "component": c, "action": a} for d, c, a in option]}
    return choose


# ---- race parts ----

def race_gemini(obs, session):
    return _quiet(getattr(bot(), RACE_FN), obs)


def race_baseline(obs, session):
    from play import race_action
    return race_action(obs)


def race_stay(obs, session):
    return {"type": "RACE_STRATEGY", "driver_a": "STAY", "driver_b": "STAY"}


def race_rollout(obs, session):
    import b4_counterfactual as b4
    action = b4.rollout_action(ts._copy_race(session._active_race.race_state))
    return {"type": "RACE_STRATEGY", **action}


def race_gemini_patched_late(obs, session):
    """Gemini race policy, but never stops with <= 2 segments left unless the two-compound rule needs it."""
    action = _quiet(getattr(bot(), RACE_FN), obs)
    rp = obs["race_progress"]
    for key in ("driver_a", "driver_b"):
        needs = len(set(rp["drivers"][key]["compounds_used"])) < 2
        if action[key] != "STAY" and rp["laps_remaining"] <= 2 * rp["segment_laps"] and not needs:
            action[key] = "STAY"
    return action


COMPONENTS = {"gemini": comp_gemini, "baseline": comp_baseline, "rule": _comp_from_solver("rival_rule"),
              "greedy": _comp_from_solver("greedy"), "always_use": _comp_from_solver("always_use")}
RACES = {"gemini": race_gemini, "baseline": race_baseline, "stay": race_stay, "rollout": race_rollout,
         "gemini_patched_late": race_gemini_patched_late}
POLICIES = {
    "gemini": ("gemini", "gemini"),
    "baseline": ("baseline", "baseline"),
    "gemini_comp+base_race": ("gemini", "baseline"),
    "base_comp+gemini_race": ("baseline", "gemini"),
    "rule+base_race": ("rule", "baseline"),
    "greedy+base_race": ("greedy", "baseline"),
    "do_nothing": ("always_use", "stay"),
    "gemini_patched_late_stops": ("gemini", "gemini_patched_late"),
}
ROLLOUT_POLICIES = {"gemini_comp+rollout_race": ("gemini", "rollout")}


def play_season(args):
    policy_path, name, comp_key, race_key, seed, cached_components, fns = args
    global POLICY_PATH, COMPONENT_FN, RACE_FN
    POLICY_PATH = policy_path
    COMPONENT_FN, RACE_FN = fns
    session = ChampionshipSession(base_seed=seed)
    per_race, stops, late_stops, race_points = [], 0, 0, []
    component_log = []
    comp_index = 0
    accepted = 0
    while session.decision_type != "CHAMPIONSHIP_COMPLETE":
        obs = session.observation()
        obs["decision_id"] = f"d{accepted + 1:03d}"  # the sidecar adds this; agent policies may read it
        accepted += 1
        if obs["decision_type"] == "COMPONENT_DECISION":
            if cached_components is not None:
                action = cached_components[comp_index]
            else:
                action = COMPONENTS[comp_key](obs, session)
            comp_index += 1
            component_log.append(action)
            before = session.state.team_points["Apex"]
            session.submit(action)
        else:
            action = RACES[race_key](obs, session)
            rp = obs["race_progress"]
            for key in ("driver_a", "driver_b"):
                if action[key] != "STAY":
                    stops += 1
                    if rp["laps_remaining"] <= 2 * rp["segment_laps"]:
                        late_stops += 1
            race_before = session.state.race_index
            session.submit(action)
            if session.state.race_index != race_before:
                race_points.append(session.state.team_points["Apex"] - before)
    return {"policy": name, "seed": seed, "points": session.state.team_points["Apex"], "per_race": race_points,
            "stops": stops, "late_stops": late_stops, "components": component_log}


def components_plan(policy_path, comp_key):
    """Component decisions do not depend on race events, so the plan is the same on every seed."""
    result = play_season((policy_path, "plan", comp_key, "baseline", 1, None, (COMPONENT_FN, RACE_FN)))
    return result["components"]


def summarize(rows, ref="gemini"):
    by = {}
    for r in rows:
        by.setdefault(r["policy"], {})[r["seed"]] = r
    nothing = by["do_nothing"]
    lines = ["| Policy | Seeds | Mean pts ± s.e. | Median | Min / Max | Mean reward (P0) | Paired Δ vs Gemini ± s.e. | Gemini better on | Stops / season | Stops with ≤ 6 laps left / season |",
             "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|"]
    g = by[ref]
    order = ["gemini", "gemini_patched_late_stops", "gemini_comp+rollout_race", "gemini_comp+base_race",
             "base_comp+gemini_race", "rule+base_race", "greedy+base_race", "baseline", "do_nothing"]
    for name in [n for n in order if n in by]:
        rs = by[name]
        seeds = sorted(rs)
        pts = [rs[s]["points"] for s in seeds]
        reward = [min(1, max(0, (rs[s]["points"] - nothing[s]["points"]) / (UPPER - nothing[s]["points"]))) for s in seeds]
        diff = [rs[s]["points"] - g[s]["points"] for s in seeds if s in g]
        se = st.pstdev(pts) / math.sqrt(len(pts))
        dse = st.pstdev(diff) / math.sqrt(len(diff)) if len(diff) > 1 else 0
        better = sum(d < 0 for d in diff)
        lines.append(f"| {name} | {len(seeds)} | {st.mean(pts):.1f} ± {se:.1f} | {st.median(pts):.0f} | {min(pts)} / {max(pts)} | "
                     f"{st.mean(reward):.3f} | {st.mean(diff):+.1f} ± {dse:.1f} | {better}/{len(diff)} | "
                     f"{st.mean(rs[s]['stops'] for s in seeds):.1f} | {st.mean(rs[s]['late_stops'] for s in seeds):.2f} |")
    lines += ["", "Per-race mean points (Gemini vs baseline vs Gemini components + rollout race):", "",
              "| Race | " + " | ".join(n for n in ("gemini", "baseline", "gemini_comp+rollout_race") if n in by) + " |",
              "|---:|" + "---:|" * len([n for n in ("gemini", "baseline", "gemini_comp+rollout_race") if n in by])]
    for i in range(8):
        cells = []
        for n in ("gemini", "baseline", "gemini_comp+rollout_race"):
            if n in by:
                cells.append(f"{st.mean(r['per_race'][i] for r in by[n].values()):.1f}")
        lines.append(f"| {i + 1} | " + " | ".join(cells) + " |")
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("policy")
    parser.add_argument("--seeds", type=int, default=200)
    parser.add_argument("--rollout-seeds", type=int, default=60)
    parser.add_argument("--workers", type=int, default=10)
    parser.add_argument("--out", default=str(HERE / "results" / "b4_written_policy_eval.json"))
    parser.add_argument("--component-fn", default="decide_component")
    parser.add_argument("--race-fn", default="decide_strategy")
    parser.add_argument("--hidden-seed", type=int, default=None, help="this run's hidden seed for the replay check")
    args = parser.parse_args()
    policy_path = str(Path(args.policy).resolve())
    global POLICY_PATH, COMPONENT_FN, RACE_FN
    POLICY_PATH = policy_path
    COMPONENT_FN, RACE_FN = args.component_fn, args.race_fn
    fns = (COMPONENT_FN, RACE_FN)
    started = time.time()
    plans = {k: components_plan(policy_path, k) for k in ("gemini", "baseline", "rule", "greedy", "always_use")}
    seeds = eval_seeds(args.seeds)
    jobs = [(policy_path, name, c, r, s, plans[c], fns) for name, (c, r) in POLICIES.items() for s in seeds]
    jobs += [(policy_path, name, c, r, s, plans[c], fns) for name, (c, r) in ROLLOUT_POLICIES.items()
             for s in seeds[:args.rollout_seeds]]
    with mp.Pool(args.workers) as pool:
        rows = pool.map(play_season, jobs, chunksize=4)
    check_seed = HIDDEN if args.hidden_seed is None else args.hidden_seed
    hidden = [play_season((policy_path, name, c, r, check_seed, plans[c], fns)) for name, (c, r) in POLICIES.items()]
    out = {"seeds": len(seeds), "rollout_seeds": args.rollout_seeds,
           "component_plans": {k: [[d["driver"] + ":" + d["component"] for d in a["decisions"] if d["action"] == "REPLACE"]
                                   for a in v] for k, v in plans.items()},
           "rows": [{k: v for k, v in r.items() if k != "components"} for r in rows],
           "hidden_seed_check": {r["policy"]: r["points"] for r in hidden},
           "wall_seconds": round(time.time() - started, 1)}
    Path(args.out).write_text(json.dumps(out, indent=1))
    print(f"wall {out['wall_seconds']}s; replay on this run's hidden seed (compare with the Harbor run): {out['hidden_seed_check']}")
    print("component plans:", json.dumps(out["component_plans"]))
    print(summarize(out["rows"]))


if __name__ == "__main__":
    main()
