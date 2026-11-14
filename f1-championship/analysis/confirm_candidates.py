#!/usr/bin/env python3
"""Second-stage check of failure candidates with the agent's own policy as continuation.

Input: a frontier_trace.py output (baseline continuation) for one run. Candidates are race
decisions whose loss vs the best public alternative exceeds 1 pt and 2 standard errors.
For each candidate, re-estimate four actions -- the agent's, the best alternative found under
the baseline continuation, the baseline's, and STAY/STAY -- with the agent's own policy playing
the rest of the race, on futures independent of those used before (public, conditioned only on
what the agent had observed). A candidate is 'confirmed' if the loss also exceeds 1 pt and
2 standard errors here.

Usage: python3 analysis/confirm_candidates.py <evidence_dir> <trace.json> <policy.py:function> <seed> <out.json>
        [--futures 24] [--workers 10]
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
sys.path.insert(0, str(HERE))

import frontier_trace as ft  # noqa: E402
from f1pitwall.journal import parse_journal  # noqa: E402


def job(args):
    node, keys, futures_n, policy = args
    ft.CONTINUATION = ft.load_agent_policy(policy)
    futures = ft.ts.public_futures(node, futures_n, "confirm")
    return ft.q_eval(node, keys, futures)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("evidence")
    parser.add_argument("trace")
    parser.add_argument("policy")
    parser.add_argument("seed", type=int)
    parser.add_argument("out")
    parser.add_argument("--futures", type=int, default=24)
    parser.add_argument("--workers", type=int, default=10)
    args = parser.parse_args()
    trace = json.loads(Path(args.trace).read_text())
    candidates = {(d["race_index"], d["decision"]): d for d in trace["decisions"]
                  if d["loss_vs_best"] > 1 and d["loss_vs_best"] > 2 * d["loss_se"]}
    entries = parse_journal((Path(args.evidence) / "journal.jsonl").read_text())
    jobs, meta = [], []
    for entry, before, _ in ft.replay_decisions(entries, args.seed):
        if entry["decision_type"] != "RACE_STRATEGY":
            continue
        node = ft.ts._copy_race(before._active_race.race_state)
        node["config"] = ft.public_context(node["config"], before.observation())
        key = (before.state.race_index, node["step"] + 1)
        if key in candidates:
            d = candidates[key]
            keys = sorted({d["agent"], d["best"], d["baseline"], "STAY/STAY"})
            jobs.append((node, keys, args.futures, args.policy))
            meta.append(d)
    with mp.Pool(args.workers) as pool:
        values = pool.map(job, jobs)
    out = []
    for d, q in zip(meta, values):
        diff = [x - y for x, y in zip(q[d["best"]], q[d["agent"]])]
        se = st.pstdev(diff) / math.sqrt(len(diff)) if len(diff) > 1 else 0.0
        own = st.mean(diff)
        out.append({**{k: d[k] for k in ("race_index", "decision", "lap", "status", "category", "agent", "best",
                                         "baseline", "drivers")},
                    "loss_baseline_continuation": d["loss_vs_best"], "se_baseline_continuation": d["loss_se"],
                    "loss_own_continuation": own, "se_own_continuation": se,
                    "q_own": {k: st.mean(v) for k, v in q.items()},
                    "confirmed": own > 1 and own > 2 * se})
    Path(args.out).write_text(json.dumps(out, indent=1, default=str))
    print(f"candidates {len(out)}, confirmed {sum(o['confirmed'] for o in out)}")
    for o in out:
        print(f"R{o['race_index'] + 1} d{o['decision']:>2} lap{o['lap']:>2} {o['status']:<5} {o['category']:<10} "
              f"agent {o['agent']:<22} best {o['best']:<22} loss base {o['loss_baseline_continuation']:.2f} "
              f"own {o['loss_own_continuation']:.2f}±{o['se_own_continuation']:.2f} {'CONFIRMED' if o['confirmed'] else ''}")


if __name__ == "__main__":
    main()
