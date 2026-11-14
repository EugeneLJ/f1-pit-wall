#!/usr/bin/env python3
"""B5-P1: event-driven counterfactual decision reversals (evaluation only).

On decision states visited by the full public-event planner (from b5_event_eval.json), the 16
joint actions are evaluated under explicitly constructed future classes. The policy never
chooses with knowledge of these classes; they show how the best action depends on the future.

  GREEN states      no_event (all GREEN) | sc_next (SC of 2 segments starts at the next decision)
                    | mixture (published process, 48 public futures)
  SC, 1st segment   SC lasts d = 1, 2, 3 segments in total (then GREEN) | mixture
  SC/VSC states     the same history with the current status flipped SC <-> VSC (mixture)
  late (>= lap 33)  mixture: is a stop worth it or not?
Each state is classified by its mixture-best action and by whether the class-best actions differ.
Usage: scripts/py312 analysis/b5_reversals.py [--workers 10]
Writes analysis/results/b5_reversals.json
"""

from __future__ import annotations

import argparse
import json
import math
import multiprocessing as mp
import random
import statistics as st
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import b5_event_eval as b5  # noqa: E402
import event_policies as ep  # noqa: E402
from f1pitwall import engine  # noqa: E402

MIX = 48
MARGIN = 0.5


def best(q):
    return max(q, key=lambda k: st.mean(q[k]))


def gain(q, a, b):
    d = [x - y for x, y in zip(q[a], q[b])] if len(q[a]) == len(q[b]) else None
    if d is None:
        return st.mean(q[a]) - st.mean(q[b]), 0.0
    return st.mean(d), (st.pstdev(d) / math.sqrt(len(d)) if len(d) > 1 else 0.0)


def explicit(node, statuses):
    n, step = len(node["events"]), node["step"]
    future = list(statuses)[: n - step - 1]
    return future + ["GREEN"] * (n - step - 1 - len(future))


def analyse_state(node):
    status = node["events"][node["step"]]
    so_far = engine.segments_so_far(node["events"], node["step"])
    lap = engine._decision_laps(node)[node["step"]]
    mix = ep.q_values(node, ep.planner_futures(node, "full", MIX, tag="reversal"))
    out = {"status": status, "segments_so_far": so_far, "lap": lap, "decision": node["step"] + 1,
           "best_mixture": best(mix)}
    g, se = gain(mix, out["best_mixture"], "STAY/STAY")
    out.update({"mixture_gain_over_stay": g, "mixture_gain_se": se})
    if status == "GREEN":
        no_event = ep.q_values(node, [explicit(node, [])])
        sc_next = ep.q_values(node, [explicit(node, ["SC", "SC"])])
        out.update({"best_no_event": best(no_event), "best_sc_next": best(sc_next)})
        # anticipation reversal: the no-event best stops a car that the mixture best keeps out
        out["stay_due_to_event_risk"] = any(a != "STAY" and b == "STAY" for a, b in
                                            zip(out["best_no_event"].split("/"), out["best_mixture"].split("/")))
        out["regret_of_no_event_choice"] = gain(mix, out["best_mixture"], out["best_no_event"])
    if status == "SC" and so_far == 1:
        per_d = {d: best(ep.q_values(node, [explicit(node, ["SC"] * (d - 1))])) for d in (1, 2, 3)}
        out["best_by_sc_duration"] = per_d
        out["duration_reversal"] = len(set(per_d.values())) > 1
    if status in ("SC", "VSC"):
        other = "VSC" if status == "SC" else "SC"
        flipped = b5.flipped(node, other)
        flipped["events"][:node["step"]] = [other if s == status else s for s in node["events"][:node["step"]]]
        out["best_if_" + other] = best(ep.q_values(flipped, ep.planner_futures(flipped, "full", MIX, tag="reversal")))
        out["type_reversal"] = out["best_if_" + other] != out["best_mixture"]
    return out


def job(args):
    spec, index, rows = args
    race = b5.scenario(spec, index)
    rng = random.Random(f"b5-reversal|{spec['id']}|{index}")
    out = []
    for row in rows:
        path = [{"." : "GREEN", "S": "SC", "V": "VSC"}[c] for c in row["events"]]
        for step in range(len(path)):
            status = path[step]
            take = status != "GREEN" or (step >= 10 and rng.random() < 0.5) or rng.random() < 0.12
            if not take:
                continue
            node = b5.replay_to(race, path, row["actions"], step)
            info = analyse_state(node)
            info.update({"scenario": spec["id"], "race_index": index, "path": row["path"], "kind": row["kind"]})
            out.append(info)
    return out


def main():
    import scenarios as sc
    parser = argparse.ArgumentParser()
    parser.add_argument("--workers", type=int, default=10)
    args = parser.parse_args()
    from b5_summarize import load
    data = load("b5_event_eval.json")
    specs = {s["id"]: s for s in sc.generate_specs(24)}
    groups = {}
    for r in data["rows"]:
        if r["policy"] == "full":
            groups.setdefault((r["scenario"], r["race_index"]), []).append(r)
    with mp.Pool(args.workers) as pool:
        parts = pool.map(job, [(specs[s], i, rows) for (s, i), rows in groups.items()], chunksize=1)
    states = [x for p in parts for x in p]
    (HERE / "results" / "b5_reversals.json").write_text(json.dumps({"states": states}, default=str))
    print(f"states analysed: {len(states)}")


if __name__ == "__main__":
    from _runtime import require_runtime_python
    require_runtime_python()
    main()
