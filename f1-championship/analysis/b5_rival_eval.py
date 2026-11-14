#!/usr/bin/env python3
"""B5-P1: rival pit-strategy sensitivity (opt-in rival variants; default benchmark unchanged).

For every rival variant, on the same race-start states and the same TRUE event paths:
  baseline             public heuristic
  full_known           the full public-event planner whose rollouts use the actual rival variant
  full_assumes_public  the same planner, but its rollouts assume the published (default) rival rule
  r0..r3               the unchanged agent-written race policies
Plus a decision-level check: on decision states visited by full_known under the default rivals,
does the planner's best action change when the rival variant changes?
Usage: scripts/py312 analysis/b5_rival_eval.py [--scenarios 24] [--paths 3] [--workers 10]
Writes analysis/results/b5_rival_eval.json
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

import b5_event_eval as b5  # noqa: E402
import event_policies as ep  # noqa: E402
import track_a_solver as ts  # noqa: E402
from f1pitwall import engine  # noqa: E402
from f1pitwall.rival_policies import VARIANTS  # noqa: E402


def with_rivals(node, variant):
    out = ts._copy_race(node)
    out["config"] = dict(node["config"], rival_policy=None if variant == "public" else variant)
    return out


def planner(rollout_variant):
    def act(node):
        return ep.plan_action(with_rivals(node, rollout_variant), "full")[0]
    return act


def play(race, path, variant, fn):
    node = with_rivals(race, variant)
    node["events"] = list(path)
    actions = []
    while node["step"] < len(node["events"]):
        action = fn(node)
        actions.append(f"{action['driver_a']}/{action['driver_b']}")
        engine.step(node, action)
    return ts.expected_apex_points_at_finish(node), actions


def job(args):
    spec, index, paths = args
    race = b5.scenario(spec, index)
    key = f"{spec['id']}|{index}"
    rows, reversals = [], []
    rng = random.Random(f"b5-rival|{key}")
    for p_index, (kind, path) in enumerate(b5.eval_paths(race, key, paths, paths)):
        default_actions = None
        for variant in VARIANTS:
            policies = {"baseline": lambda node: ts.baseline_race_action(engine.observation(node)),
                        "full_known": planner(variant), "full_assumes_public": planner("public")}
            policies.update({name: b5.gemini_fn(name) for name in b5.GEMINI})
            for name, fn in policies.items():
                if variant == "public" and name == "full_assumes_public":
                    continue  # identical to full_known under default rivals
                value, actions = play(race, path, variant, fn)
                rows.append({"scenario": spec["id"], "race_index": index, "path": p_index, "kind": kind,
                             "variant": variant, "policy": name, "points": value, "actions": actions})
                if variant == "public" and name == "full_known":
                    default_actions = actions
        # decision-level: same states (default-rival full trajectory), best action per rival variant
        for step in range(len(path)):
            if path[step] == "GREEN" and rng.random() > 0.25:
                continue
            base = b5.replay_to(with_rivals(race, "public"), path, default_actions, step)
            best = {v: "/".join(ep.plan_action(with_rivals(base, v), "full")[0].values()) for v in VARIANTS}
            reversals.append({"scenario": spec["id"], "race_index": index, "path": p_index, "decision": step + 1,
                              "status": path[step], "best": best})
    return {"rows": rows, "reversals": reversals}


def main():
    import scenarios as sc
    parser = argparse.ArgumentParser()
    parser.add_argument("--scenarios", type=int, default=24)
    parser.add_argument("--paths", type=int, default=2, help="natural and event paths per state (each)")
    parser.add_argument("--workers", type=int, default=10)
    args = parser.parse_args()
    specs = sc.generate_specs(args.scenarios)
    started = time.time()
    with mp.Pool(args.workers) as pool:
        parts = pool.map(job, [(s, i, args.paths) for s in specs for i in b5.RACE_INDICES], chunksize=1)
    out = {"variants": VARIANTS, "rows": [r for p in parts for r in p["rows"]],
           "reversals": [r for p in parts for r in p["reversals"]], "wall_seconds": round(time.time() - started, 1)}
    (HERE / "results" / "b5_rival_eval.json").write_text(json.dumps(out))
    print(f"wall {out['wall_seconds']}s rows {len(out['rows'])} reversal states {len(out['reversals'])}")


if __name__ == "__main__":
    from _runtime import require_runtime_python
    require_runtime_python()
    main()
