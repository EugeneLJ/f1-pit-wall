#!/usr/bin/env python3
"""Staged, cached paired evaluation of the 2.1.0 reference (integrated SOLO_COORDINATION, CHIEF_ONLY).

The "sidecar" is an in-process IntegratedSession holding the evaluation seed; the reference only
receives JSON copies of the team observation (exactly what f1ctl prints) and the published rules.
Policies: reference21 (integrated_task/solution/reference_v21.py), baseline and coordinator
(published scripted policies), fallback (the published fallback: USE/STAY/RACE every decision).
Tiers: smoke = 2 dev seeds, dev = 5 dev seeds (disjoint from every evaluation list), inter10/inter20.
Cache: analysis/results/cache/<version>/<policy>/<source hash>/<seed>.json.
Usage: scripts/py312 analysis/reference21_eval.py --stage smoke|dev|inter10|inter20 [--version 2.1.0]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import multiprocessing as mp
import statistics as st
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
TASK = HERE.parent
import os
import subprocess

BUILT = Path(os.environ.get("REF21_TASK_DIR", HERE / "results" / "cache" / "_built_integrated_task"))
for p in (TASK / "src", TASK, BUILT / "solution", BUILT / "environment" / "sim"):
    sys.path.insert(0, str(p))


def build_task(version):
    """Generate the real integrated Harbor task once; the evaluator imports its sidecar rules and solution."""
    subprocess.run(["bash", str(TASK / "scripts" / "make_integrated_task.sh"), str(BUILT), "CHIEF_ONLY", version],
                   check=True, capture_output=True)

STAGES = {"smoke": [7100, 7117], "dev": [7100 + 17 * i for i in range(5)],
          "inter10": [7300 + 29 * i for i in range(10)], "inter20": [7300 + 29 * i for i in range(20)]}
SOURCES = {"reference21": [TASK / "integrated_task/solution/reference_v21.py", TASK / "solution/reference.py",
                           TASK / "solution/play.py", TASK / "integrated_task/sim/f1sim/integrated_server.py"],
           "baseline": [TASK / "src/f1pitwall/integrated/policies.py"],
           "coordinator": [TASK / "src/f1pitwall/integrated/policies.py"],
           "fallback": [TASK / "src/f1pitwall/integrated/session.py"]}


def engine_hash():
    h = hashlib.sha256()
    for p in sorted((TASK / "src/f1pitwall").rglob("*")):
        if p.is_file() and "__pycache__" not in p.parts:
            h.update(p.read_bytes())
    return h.hexdigest()[:10]


def key(policy, version):
    h = hashlib.sha256()
    for p in SOURCES[policy]:
        h.update(Path(p).read_bytes())
    return f"{h.hexdigest()[:10]}-{engine_hash()}"


def play(args):
    policy, seed, version = args
    path = HERE / "results" / "cache" / version / policy / key(policy, version) / f"{seed}.json"
    if path.exists():
        return json.loads(path.read_text()) | {"cached": True}
    from f1pitwall.integrated import config as C, policies as P
    from f1pitwall.integrated.session import CHAMPIONSHIP_COMPLETE, IntegratedSession
    from f1sim.integrated_server import public_rules
    cfg = C.with_version(C.solo_coordination(engineers="CHIEF_ONLY", chief={"provider": policy}), version)
    session = IntegratedSession(cfg, seed)
    stats = {}
    started = time.time()
    if policy == "fallback":
        while session.decision_type != CHAMPIONSHIP_COMPLETE:
            session.close_tick(session.tick_id)
    else:
        if policy == "reference21":
            import reference_v21
            player = reference_v21.Reference21(json.loads(json.dumps(public_rules(cfg))))
            decide = player.decide
        else:
            decide = P.scripted(policy)
        while session.decision_type != CHAMPIONSHIP_COMPLETE:
            obs = json.loads(json.dumps(session.observation("Apex")))
            obs["decision_id"] = obs["tick_id"]
            session.submit("Apex", session.tick_id, decide(obs))
        if policy == "reference21":
            stats = {k: v for k, v in player.stats.items() if k != "version"}
    grid_penalties = sum(1 for rr in session.race_results for e in rr["classification"] if False)
    out = {"version": version, "policy": policy, "seed": seed, "points": session.state.team_points["Apex"],
           "replacements": {d: sum(c.replacements for c in session.state.power_units[d].values()) for d in ("Apex A", "Apex B")},
           "stock_left": {k: v for k, v in session.state.resource_inventory["Apex"].items() if k.startswith("stock:")},
           "per_race": [rr["team_points"]["Apex"] for rr in session.race_results],
           "seconds": round(time.time() - started, 1), **stats}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(out))
    return out | {"cached": False}


def main():
    sys.path.insert(0, str(HERE))
    from _runtime import require_runtime_python
    require_runtime_python()
    parser = argparse.ArgumentParser()
    parser.add_argument("--stage", choices=tuple(STAGES), required=True)
    parser.add_argument("--version", default="2.1.0")
    parser.add_argument("--policies", nargs="+", default=["reference21", "coordinator", "baseline", "fallback"])
    parser.add_argument("--workers", type=int, default=10)
    args = parser.parse_args()
    seeds = STAGES[args.stage]
    build_task(args.version)
    started = time.time()
    with mp.Pool(args.workers) as pool:
        rows = pool.map(play, [(p, s, args.version) for p in args.policies for s in seeds], chunksize=1)
    by = {(r["policy"], r["seed"]): r for r in rows}
    base = args.policies[0]
    report = {"stage": args.stage, "version": args.version, "seeds": seeds, "wall_seconds": round(time.time() - started, 1), "policies": {}}
    for p in args.policies:
        diffs = [by[(base, s)]["points"] - by[(p, s)]["points"] for s in seeds]
        report["policies"][p] = {"points": [by[(p, s)]["points"] for s in seeds],
                                 "mean_points": round(st.mean(by[(p, s)]["points"] for s in seeds), 2),
                                 f"{base}_minus_policy": diffs, "mean_paired_gap": round(st.mean(diffs), 2),
                                 "seconds_per_season": round(st.mean(by[(p, s)]["seconds"] for s in seeds), 1),
                                 "fallbacks": sum(by[(p, s)].get("fallbacks", 0) for s in seeds),
                                 "resyncs": sum(by[(p, s)].get("resyncs", 0) for s in seeds),
                                 "replacements": [by[(p, s)]["replacements"] for s in seeds]}
    out = HERE / "results" / f"reference21_{args.version}_{args.stage}.json"
    out.write_text(json.dumps({"report": report, "rows": rows}, indent=1))
    print(json.dumps(report, indent=1))
    print("note: descriptive only at this tier")


if __name__ == "__main__":
    main()
