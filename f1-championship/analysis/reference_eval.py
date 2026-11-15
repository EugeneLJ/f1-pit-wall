#!/usr/bin/env python3
"""Matched-seed evaluation of the executable reference (solution/reference.py).

The reference is driven exactly as in Harbor: it receives public observations only and returns
actions. Here the simulator is an in-process ChampionshipSession holding the evaluation seed; the
reference object never gets the session or the seed (see `play_reference`). Compared on the same
seeds: the four agent-written Gemini policies (final scripts of runs r0-r3), the public baseline
(Harbor oracle of earlier versions), do-nothing, and stop-early.

Usage: scripts/py312 analysis/reference_eval.py [--seeds 100] [--workers 10]
       scripts/py312 analysis/reference_eval.py --harbor-seeds     # the four seeds of runs r0-r3
Writes analysis/results/reference_eval.json (or reference_eval_harbor_seeds.json)
"""

from __future__ import annotations

import argparse
import json
import math
import multiprocessing as mp
import statistics as st
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
TASK = HERE.parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(TASK / "solution"))

import written_policy_eval as wpe  # noqa: E402
from f1pitwall import engine  # noqa: E402
from f1pitwall.championship_contract import ChampionshipSession  # noqa: E402

RUNS = HERE / "results" / "rep_runs"
GEMINI = {  # run -> (script, component fn, race fn), as evaluated in FRONTIER_REPEAT_REPORT.md
    "gemini_r0": (RUNS / "r0/scripts/app_pitwall_bot.py.txt", "decide_component", "decide_strategy"),
    "gemini_r1": (RUNS / "r1/scripts/app_champion.py.txt", "choose_component_decision", "choose_race_strategy"),
    "gemini_r2": (RUNS / "r2/scripts/app_run_championship.py.txt", "evaluate_component_decision", "evaluate_best_race_action"),
    "gemini_r3": (RUNS / "r3/scripts/app_run_championship.py.txt", "decide_component", "decide_race_strategy"),
}
UPPER = (engine.POINTS[0] + engine.POINTS[1]) * 8


def play_reference(seed):
    import reference
    session = ChampionshipSession(base_seed=seed)   # the "sidecar"; the player below never sees it
    player = reference.Reference()
    started, accepted, per_race, before = time.time(), 0, [], 0
    while session.decision_type != "CHAMPIONSHIP_COMPLETE":
        obs = json.loads(json.dumps(session.observation()))  # what f1ctl would print
        accepted += 1
        obs["decision_id"] = f"d{accepted:03d}"
        race = session.state.race_index
        session.submit(player.decide(obs))
        if session.state.race_index != race:
            per_race.append(session.state.team_points["Apex"] - before)
            before = session.state.team_points["Apex"]
    return {"policy": "reference", "seed": seed, "points": session.state.team_points["Apex"],
            "per_race": per_race, "seconds": round(time.time() - started, 1), **player.stats}


def play_simple(args):
    name, seed = args
    if name == "reference":
        return play_reference(seed)
    session = ChampionshipSession(base_seed=seed)
    import play
    accepted = 0
    while session.decision_type != "CHAMPIONSHIP_COMPLETE":
        obs = session.observation()
        accepted += 1
        if name == "stop_early" and accepted > 60:   # walks away after half the season
            return {"policy": name, "seed": seed, "points": session.state.team_points["Apex"], "complete": False}
        if obs["decision_type"] == "COMPONENT_DECISION":
            session.submit(play.component_action(obs))
        elif name == "do_nothing":
            session.submit({"type": "RACE_STRATEGY", "driver_a": "STAY", "driver_b": "STAY"})
        else:
            session.submit(play.race_action(obs))
    return {"policy": name, "seed": seed, "points": session.state.team_points["Apex"], "complete": True}


def play_gemini(args):
    name, path, fns, seed = args
    row = wpe.play_season((path, name, "gemini", "gemini", seed, None, fns))
    return {"policy": name, "seed": seed, "points": row["points"], "per_race": row["per_race"]}


def reward(points, nothing, complete=True):
    return min(1.0, max(0.0, (points - nothing) / (UPPER - nothing))) if complete else 0.0


def main():
    from _runtime import require_runtime_python
    require_runtime_python()
    parser = argparse.ArgumentParser()
    parser.add_argument("--seeds", type=int, default=100)
    parser.add_argument("--workers", type=int, default=10)
    parser.add_argument("--harbor-seeds", action="store_true")
    args = parser.parse_args()
    if args.harbor_seeds:
        seeds = [wpe.HIDDEN] + json.loads((RUNS / "repeat_seeds.json").read_text())["seeds"]
        out_path = HERE / "results" / "reference_eval_harbor_seeds.json"
    else:
        seeds = wpe.eval_seeds(args.seeds)   # the same public list as written_policy_eval.py
        out_path = HERE / "results" / "reference_eval.json"
    started = time.time()
    with mp.Pool(args.workers) as pool:
        ref = pool.map_async(play_simple, [("reference", s) for s in seeds], chunksize=1)
        simple = pool.map(play_simple, [(n, s) for n in ("baseline", "do_nothing", "stop_early") for s in seeds])
        gem = pool.map(play_gemini, [(n, str(p), (c, r), s)
                                     for n, (p, c, r) in GEMINI.items() for s in seeds], chunksize=2)
        rows = ref.get() + simple + gem
    by = {}
    for r in rows:
        by.setdefault(r["policy"], {})[r["seed"]] = r
    nothing = {s: by["do_nothing"][s]["points"] for s in seeds}
    summary = {}
    for name, rs in by.items():
        pts = [rs[s]["points"] for s in seeds]
        rew = [reward(rs[s]["points"], nothing[s], rs[s].get("complete", True)) for s in seeds]
        diff = [by["reference"][s]["points"] - rs[s]["points"] for s in seeds]
        rdiff = [reward(by["reference"][s]["points"], nothing[s]) - w for s, w in zip(seeds, rew)]
        n = len(seeds)
        summary[name] = {
            "mean_points": st.mean(pts), "sd_points": st.stdev(pts) if n > 1 else 0.0,
            "mean_reward": st.mean(rew),
            "reference_minus_policy_points": st.mean(diff),
            "se_points": st.stdev(diff) / math.sqrt(n) if n > 1 else 0.0,
            "reference_minus_policy_reward": st.mean(rdiff),
            "se_reward": st.stdev(rdiff) / math.sqrt(n) if n > 1 else 0.0,
            "reference_better_equal_worse": [sum(d > 0 for d in diff), sum(d == 0 for d in diff), sum(d < 0 for d in diff)],
        }
    out = {"seeds": seeds, "rows": rows, "summary": summary, "wall_seconds": round(time.time() - started, 1)}
    out_path.write_text(json.dumps(out, indent=1))
    refs = by["reference"]
    print(f"wall {out['wall_seconds']}s; reference s/season mean {st.mean(r['seconds'] for r in refs.values()):.0f}, "
          f"fallbacks {sum(r['fallbacks'] for r in refs.values())}, resyncs {sum(r['resyncs'] for r in refs.values())}")
    print("| Policy | Mean pts | SD | Mean reward | Reference − policy, pts (± s.e.) | Reward gap (± s.e.) | Ref better / tie / worse |")
    print("|---|---:|---:|---:|---:|---:|---:|")
    for name in ["reference"] + sorted(GEMINI) + ["baseline", "stop_early", "do_nothing"]:
        s = summary[name]
        b = s["reference_better_equal_worse"]
        print(f"| {name} | {s['mean_points']:.1f} | {s['sd_points']:.1f} | {s['mean_reward']:.3f} | "
              f"{s['reference_minus_policy_points']:+.1f} ± {s['se_points']:.1f} | "
              f"{s['reference_minus_policy_reward']:+.3f} ± {s['se_reward']:.3f} | {b[0]} / {b[1]} / {b[2]} |")
    if args.harbor_seeds:
        print("per seed:", {n: [by[n][s]["points"] for s in seeds] for n in by})


if __name__ == "__main__":
    main()
