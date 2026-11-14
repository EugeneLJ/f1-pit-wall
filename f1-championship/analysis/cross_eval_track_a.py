#!/usr/bin/env python3
"""Decision value of each mechanic and of the late calendar (level c, by magnitude).

For a true world W and a first-race decision d chosen as optimal in another
world W' (mechanic ablated, or a different late calendar), report
    loss = V*_W - V_W(d then optimal play)
i.e. the expected points lost in W by acting as if W' were true.
Reads analysis/results/track_a_p1.json, writes analysis/results/track_a_p1_cross.json.
"""

from __future__ import annotations

import json
import multiprocessing as mp
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))


def world_job(args):
    import scenarios as sc
    from track_a_solver import Solver, option_label
    spec, tag = args
    solver = Solver()
    state = sc.build_state(spec)
    values = {option_label(o): v for v, _, o in solver.option_values(state)}
    return {"scenario": spec["id"].split("-")[0], "world": tag, "values": values}


def _guard_runtime():
    from _runtime import require_runtime_python
    require_runtime_python()


def main():
    import scenarios as sc
    data = json.loads((HERE / "results" / "track_a_p1.json").read_text())
    specs = sc.generate_specs(len(data["scenarios"]))
    jobs = []
    for spec in specs:
        variants = sc.pair_variants(spec)
        jobs += [(spec, "default"), (variants["late_high_speed"], "late_high_speed"),
                 (variants["late_street"], "late_street")]
    with mp.Pool(10) as pool:
        worlds = pool.map(world_job, jobs)
    table = {(w["scenario"], w["world"]): w["values"] for w in worlds}

    evals = data["evals"]
    pick = {}
    for e in evals:
        key = e["scenario"].split("-")[0]
        tag = e["mechanic"] if e["tag"] == "ablation" else e["tag"]
        pick[(key, tag)] = e["optimal_first"]
        for policy, info in e["policies"].items():
            pick[(key, f"{tag}:{policy}")] = info["first"]

    def loss(world, scenario, label):
        values = table[(scenario, world)]
        if label not in values:
            return None  # decision illegal or pruned in this world
        return max(values.values()) - values[label]

    out = {"mechanic_decision_loss": {}, "pair_cross_loss": [], "greedy_first_loss": []}
    mechanics = sorted({e["mechanic"] for e in evals if e["tag"] == "ablation"})
    ids = sorted({s["id"] for s in data["scenarios"]})
    for mech in mechanics:
        out["mechanic_decision_loss"][mech] = [loss("default", i, pick[(i, mech)]) for i in ids]
    for i in ids:
        out["pair_cross_loss"].append({
            "scenario": i,
            "street_choice_in_high_speed_world": loss("late_high_speed", i, pick[(i, "late_street")]),
            "high_speed_choice_in_street_world": loss("late_street", i, pick[(i, "late_high_speed")]),
            "greedy_first_in_high_speed_world": loss("late_high_speed", i, pick[(i, "late_high_speed:greedy")]),
            "greedy_first_in_street_world": loss("late_street", i, pick[(i, "late_street:greedy")]),
        })
        out["greedy_first_loss"].append(loss("default", i, pick[(i, "default:greedy")]))
    (HERE / "results" / "track_a_p1_cross.json").write_text(json.dumps(out, indent=1))
    print(json.dumps({k: (v if k != "pair_cross_loss" else "...") for k, v in out.items()}, indent=1)[:3000])


if __name__ == "__main__":
    _guard_runtime()
    main()
