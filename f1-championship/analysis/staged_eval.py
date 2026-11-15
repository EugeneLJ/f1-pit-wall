#!/usr/bin/env python3
"""Staged, cached paired evaluation (1.1.0). Small seed budgets first; 100 seeds only for a final run.

Seed tiers (fixed, disjoint):
  smoke         2 development seeds
  dev           5 development seeds           (9000 + 17 i)
  inter10/20    first 10 / 20 of written_policy_eval.eval_seeds(100)
  final         seeds 21-100 of that list: the frozen HELD-OUT set. Requires --final-reason.
Cache: analysis/results/cache/<benchmark>/<policy>/<policy_hash>-<config_hash>/<seed>.json, where the
policy hash covers the policy's source files and the config hash its knobs. A cached result is reused
only if all four keys match. Existing reference rows in reference_eval.json (produced by the same
reference.py) are imported once with `--import-reference-eval`.
Usage: scripts/py312 analysis/staged_eval.py --stage inter10 --policies reference v110_gemini_01 ...
Prints per-seed paired differences against the first policy, the mean paired gap and runtime.
No significance claims are made below the final tier.
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
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(TASK / "solution"))

import written_policy_eval as wpe  # noqa: E402
from f1pitwall.version import BENCHMARK_VERSION  # noqa: E402

CACHE = HERE / "results" / "cache" / BENCHMARK_VERSION
RUNS = HERE / "results" / "reference_runs"
DEV = [9000 + 17 * i for i in range(5)]
EVAL = None


def tiers():
    global EVAL
    EVAL = EVAL or wpe.eval_seeds(100)
    return {"smoke": DEV[:2], "dev": DEV, "inter10": EVAL[:10], "inter20": EVAL[:20], "final": EVAL[20:]}


def sha(paths) -> str:
    h = hashlib.sha256()
    for p in paths:
        h.update(Path(p).read_bytes())
    return h.hexdigest()[:12]


def policy_spec(name):
    """(source files for the hash, config dict, runner kind)."""
    if name.startswith("reference"):
        variant = name.split(":", 1)[1] if ":" in name else "base"
        files = [TASK / "solution" / "reference.py", TASK / "solution" / "play.py"] + \
            sorted((TASK / "solution" / "lib" / "f1pitwall").rglob("*.py"))
        if variant != "base":
            files.append(HERE / "reference_improve.py")
        return files, {"variant": variant}, "reference"
    if name.startswith("v110_gemini_"):
        run = RUNS / name.replace("_", "-").replace("v110-gemini-", "v110-gemini-")
        return [run / "policy.py", *sorted((run / "scripts").glob("*.txt"))], {"fns": ["decide_component", "decide_strategy"]}, "script"
    if name == "baseline":
        return [TASK / "solution" / "play.py"], {}, "baseline"
    raise ValueError(f"unknown policy {name}")


def cache_path(name, seed):
    files, config, _ = policy_spec(name)
    key = f"{sha(files)}-{hashlib.sha256(json.dumps(config, sort_keys=True).encode()).hexdigest()[:8]}"
    return CACHE / name.replace(":", "@") / key / f"{seed}.json"


def run_one(args):
    name, seed = args
    path = cache_path(name, seed)
    if path.exists():
        return json.loads(path.read_text()) | {"cached": True}
    _, config, kind = policy_spec(name)
    started = time.time()
    if kind == "reference":
        import reference_improve as RI
        R = RI.configure(config["variant"])
        from f1pitwall.championship_contract import ChampionshipSession
        session, player, n = ChampionshipSession(base_seed=seed), R.Reference(), 0
        while session.decision_type != "CHAMPIONSHIP_COMPLETE":
            obs = json.loads(json.dumps(session.observation()))
            n += 1
            obs["decision_id"] = f"d{n:03d}"
            session.submit(player.decide(obs))
        points, extra = session.state.team_points["Apex"], {"fallbacks": player.stats["fallbacks"]}
    elif kind == "script":
        files, _, _ = policy_spec(name)
        row = wpe.play_season((str(files[0]), name, "gemini", "gemini", seed, None, tuple(config["fns"])))
        points, extra = row["points"], {"per_race": row["per_race"]}
    else:
        import play
        from f1pitwall.championship_contract import ChampionshipSession
        session = ChampionshipSession(base_seed=seed)
        while session.decision_type != "CHAMPIONSHIP_COMPLETE":
            obs = session.observation()
            session.submit(play.component_action(obs) if obs["decision_type"] == "COMPONENT_DECISION" else play.race_action(obs))
        points, extra = session.state.team_points["Apex"], {}
    out = {"benchmark": BENCHMARK_VERSION, "policy": name, "seed": seed, "points": points,
           "seconds": round(time.time() - started, 1), **extra}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(out))
    return out | {"cached": False}


def import_reference_eval():
    data = json.loads((HERE / "results" / "reference_eval.json").read_text())
    n = 0
    for row in data["rows"]:
        if row["policy"] in ("reference", "baseline"):
            path = cache_path(row["policy"], row["seed"])
            if not path.exists():
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(json.dumps({"benchmark": BENCHMARK_VERSION, "policy": row["policy"], "seed": row["seed"],
                                            "points": row["points"], "seconds": row.get("seconds"),
                                            "imported_from": "reference_eval.json (commit 408828e, same reference.py)"}))
                n += 1
    return n


def main():
    from _runtime import require_runtime_python
    require_runtime_python()
    parser = argparse.ArgumentParser()
    parser.add_argument("--stage", choices=("smoke", "dev", "inter10", "inter20", "final"))
    parser.add_argument("--policies", nargs="+", default=["reference"])
    parser.add_argument("--workers", type=int, default=10)
    parser.add_argument("--final-reason", help="required for the 100-seed held-out tier")
    parser.add_argument("--import-reference-eval", action="store_true")
    args = parser.parse_args()
    if args.import_reference_eval:
        print(f"imported {import_reference_eval()} cached reference/baseline results")
        if not args.stage:
            return
    if args.stage == "final" and not args.final_reason:
        parser.error("the final held-out tier needs --final-reason")
    seeds = tiers()[args.stage]
    started = time.time()
    with mp.Pool(args.workers) as pool:
        rows = pool.map(run_one, [(p, s) for p in args.policies for s in seeds], chunksize=1)
    by = {(r["policy"], r["seed"]): r for r in rows}
    base = args.policies[0]
    report = {"stage": args.stage, "seeds": seeds, "base": base, "policies": {}, "wall_seconds": round(time.time() - started, 1)}
    for p in args.policies:
        diffs = [by[(base, s)]["points"] - by[(p, s)]["points"] for s in seeds]
        report["policies"][p] = {
            "points": [by[(p, s)]["points"] for s in seeds],
            "mean_points": round(st.mean(by[(p, s)]["points"] for s in seeds), 2),
            f"{base}_minus_policy_per_seed": diffs,
            "mean_paired_gap": round(st.mean(diffs), 2),
            "sd_paired_gap": round(st.stdev(diffs), 2) if len(diffs) > 1 else None,
            "base_better_equal_worse": [sum(d > 0 for d in diffs), sum(d == 0 for d in diffs), sum(d < 0 for d in diffs)],
            "seconds_per_season": round(st.mean(by[(p, s)]["seconds"] or 0 for s in seeds), 1),
            "computed_now": sum(1 for s in seeds if not by[(p, s)]["cached"])}
    out = HERE / "results" / f"staged_{args.stage}.json"
    prev = json.loads(out.read_text()) if out.exists() else {}
    prev.setdefault("runs", []).append(report)
    out.write_text(json.dumps(prev, indent=1))
    print(json.dumps(report, indent=1))
    if args.stage != "final":
        print("note: descriptive only; no significance claims below the final tier")


if __name__ == "__main__":
    main()
