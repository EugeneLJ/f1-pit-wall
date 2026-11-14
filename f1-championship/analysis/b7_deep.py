#!/usr/bin/env python3
"""B7-P0 follow-up investigations on the live pilot seasons (no model calls, no tuning).

  double_stacks   every decision where a team pitted both cars: 16 alternative pit/compound
                  combinations x three future-event assumptions (published model; neutralization
                  ends now; continues one more segment) x four continuation assumptions for the
                  rival team (baseline, event_aware, long_stint, opportunistic); plus a one-segment
                  decomposition (crew queue, pit loss by status, tyre life left, positions).
  selectivity     McLearn vs Red Bool: how often a double stack is the reference-best action.
  team_orders     every non-RACE order: status, feasibility, value vs the same pit action with RACE.
  contract        both Chiefs received the same 2.0.1 action-format contract and prompt template.
Values: expected team points at the finish (authoritative engine, public inputs; labelled
model-access advantage). Usage: scripts/py312 analysis/b7_deep.py analysis/results/b7 [--futures 24]
Writes analysis/results/b7/deep.json
"""

from __future__ import annotations

import argparse
import copy
import json
import math
import multiprocessing as mp
import random
import statistics as st
import sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import b6_eval as E  # noqa: E402
import b7_analysis as A  # noqa: E402
import event_policies as ep  # noqa: E402
from f1pitwall import engine  # noqa: E402
from f1pitwall.integrated import config as C  # noqa: E402
from f1pitwall.integrated import race as ir  # noqa: E402
from f1pitwall.integrated.engineers import EngineerBroker  # noqa: E402

RIVAL_CONTINUATIONS = ("baseline", "event_aware", "long_stint", "opportunistic")


def event_futures(race, k):
    step, n = race["step"], len(race["events"])
    history = race["events"][:step + 1]
    status = history[-1]
    rng = random.Random(f"b7deep|{step}|{history}")
    natural = [ep.generate(rng, history, n, race["config"]["neutralization"], "full") for _ in range(k)]
    ends_now = [["GREEN"] * (n - step - 1)]
    continues = [([status] + ["GREEN"] * (n - step - 2))[: n - step - 1]] if status != "GREEN" else ends_now
    return {"published_model": natural, "ends_now": ends_now, "continues_one_more_segment": continues}


def values(race, slot, other, rival_cont, futures, rival_now):
    legal = engine.legal_actions(race)
    out = {}
    for a in legal:
        for b in legal:
            act = {"driver_a": a, "driver_b": b, "team_order": {"order": "RACE"}}
            if "RACE" not in ir.legal_team_orders(race, slot):
                act["team_order"] = {"order": "KEEP_ORDER"}
            vals = [E.expected_team_points(E.rollout(race, {slot: act, other: rival_now},
                                                     {slot: "baseline", other: rival_cont}, f), slot) for f in futures]
            out[f"{a}/{b}"] = vals
    return out


def decompose(race, slot, chosen):
    """One segment with the realised status: what the double stack cost directly."""
    pit = race["config"]["pit"]
    status = race["events"][race["step"]]
    cars = ir.team_cars(slot)
    by = {c["name"]: c for c in race["cars"]}
    life = race["config"]["tyres"]["compounds"]
    laps_left = engine.laps_total(race) - engine._decision_laps(race)[race["step"]]
    before = [c["name"] for c in sorted(race["cars"], key=lambda c: (c["elapsed"], c["name"]))]
    out = {"status": status, "pit_loss_sec_this_status": pit["loss_sec"][status],
           "pit_loss_sec_green": pit["loss_sec"]["GREEN"], "crew_queue_sec": pit["double_stack_queue_sec"],
           "laps_remaining": laps_left, "cars": {}}
    for key, name in cars.items():
        car = by[name]
        new = engine.pit_compound(chosen[key])
        out["cars"][key] = {"compound": car["compound"], "tyre_age": car["tyre_age"],
                            "life_left_laps": life[car["compound"]]["life_laps"] - car["tyre_age"],
                            "position_before": before.index(name) + 1, "fitted": new,
                            "fitted_life_laps": life[new]["life_laps"] if new else None,
                            "fitted_life_short_of_finish_laps": (laps_left - life[new]["life_laps"]) if new else None}
    pits = {"driver_a": chosen["driver_a"], "driver_b": chosen["driver_b"]}
    for label, act in (("chosen", pits), ("stay_both", {"driver_a": "STAY", "driver_b": "STAY"})):
        node = copy.deepcopy(race)
        others = {s: E.policy_action("baseline", node, s) for s in node["integrated"]["controlled"] if s != slot}
        ir.step(node, {slot: {**act, "team_order": {"order": "RACE"} if "RACE" in ir.legal_team_orders(race, slot)
                              else {"order": "KEEP_ORDER"}}, **others})
        after = [c["name"] for c in sorted(node["cars"], key=lambda c: (c["elapsed"], c["name"]))]
        for key, name in cars.items():
            out["cars"][key][f"position_after_{label}"] = after.index(name) + 1
    return out


def double_stack_job(args):
    item, label, slot, other, futures = args
    race, chosen = item["race"], item["actions"][label]
    fut = event_futures(race, futures)
    chosen_key = f"{chosen['driver_a']}/{chosen['driver_b']}"
    table = {}
    for rival_cont in RIVAL_CONTINUATIONS:
        rival_now = E.policy_action(rival_cont, race, other)
        for name, paths in fut.items():
            q = values(race, slot, other, rival_cont, paths, rival_now)
            means = {k: st.mean(v) for k, v in q.items()}
            best = max(means, key=means.get)
            diff = [x - y for x, y in zip(q[best], q[chosen_key])]
            ranked = sorted(means, key=means.get, reverse=True)
            table[f"{rival_cont}|{name}"] = {
                "best": best, "regret": round(st.mean(diff), 3),
                "se": round(st.pstdev(diff) / math.sqrt(len(diff)), 3) if len(diff) > 1 else 0.0,
                "chosen_rank_of_16": ranked.index(chosen_key) + 1,
                "best_single_stop": max((k for k in means if k.count("STAY") == 1), key=means.get),
                "value_chosen": round(means[chosen_key], 3), "value_best": round(means[best], 3),
                "value_stay_both": round(means["STAY/STAY"], 3),
                "best_double_stack": max((k for k in means if "STAY" not in k), key=means.get)}
    return {"tick_id": item["tick_id"], "race_index": item["race_index"], "team": label,
            "decision": race["step"] + 1, "lap": engine._decision_laps(race)[race["step"]],
            "chosen": chosen_key, "decomposition": decompose(race, slot, chosen), "alternatives": table}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("root")
    parser.add_argument("--futures", type=int, default=24)
    parser.add_argument("--workers", type=int, default=10)
    args = parser.parse_args()
    root = Path(args.root)
    out = {"reference": "authoritative-engine public-input rollouts (model-access advantage); own continuation baseline"}
    jobs, layers = [], {}
    for layer in (1, 2):
        d = root / f"layer{layer}"
        if not (d / "summary.json").exists():
            continue
        summary, journal, ticks = A.load(d)
        cfg = C.IntegratedConfig.from_dict(summary["config"])
        broker = EngineerBroker.replaying(d / "engineers") if layer == 2 else None
        session, states = A.replay_states(cfg, journal, broker)
        slot_of = {t.label: t.slot for t in cfg.teams}
        layers[layer] = (d, cfg, states, slot_of, ticks)
        for item in states:
            for label, slot in slot_of.items():
                act = item["actions"][label]
                if act["driver_a"] != "STAY" and act["driver_b"] != "STAY":
                    other = next(s for s in slot_of.values() if s != slot)
                    jobs.append(((layer,), (item, label, slot, other, args.futures)))
    with mp.Pool(args.workers) as pool:
        results = pool.map(double_stack_job, [j[1] for j in jobs])
    out["double_stacks"] = [{"layer": j[0][0], **r} for j, r in zip(jobs, results)]
    recurrence = Counter((r["layer"], r["team"], r["decomposition"]["status"],
                          "+".join(sorted(set(c["fitted"] for c in r["decomposition"]["cars"].values()))))
                         for r in out["double_stacks"])
    out["double_stack_recurrence"] = [{"layer": k[0], "team": k[1], "status": k[2], "compounds": k[3], "count": v}
                                      for k, v in sorted(recurrence.items())]

    out["selectivity"], out["team_orders"], out["contract"] = {}, {}, {}
    for layer, (d, cfg, states, slot_of, ticks) in layers.items():
        analysis = json.loads((d / "analysis.json").read_text())
        sel = {}
        for label in slot_of:
            rows = [r for r in analysis["decisions"] if r["team"] == label]
            best_ds = [r for r in rows if "STAY" not in r["reference"].split("|")[0]]
            strong = []
            for r in rows:
                ds = {k: v for k, v in r["q_all"].items() if "STAY" not in k.split("|")[0]}
                k = max(ds, key=ds.get)
                gain, se = ds[k] - r["q_chosen"], r["q_se_vs_chosen"][k]
                if gain > 1.0 and gain > 2 * se:
                    strong.append({"tick_id": r["tick_id"], "lap": r["lap"], "status": r["status"],
                                   "chosen": r["chosen"], "best_double_stack": k, "gain": round(gain, 3), "se": se})
            chosen_ds = [r for r in rows if "STAY" not in r["chosen"].split("|")[0]]
            sel[label] = {"decisions": len(rows), "double_stacks_chosen": len(chosen_ds),
                          "double_stack_is_reference_best": len(best_ds),
                          "double_stack_clearly_better_than_chosen": len(strong), "cases": strong,
                          "chosen_double_stacks_with_positive_regret": sum(1 for r in chosen_ds if r["regret"] > 1 and r["regret"] > 2 * r["se"])}
        out["selectivity"][f"layer{layer}"] = sel
        orders = []
        for r in analysis["decisions"]:
            pit, order = r["chosen"].split("|")
            if order != "RACE":
                race_key = f"{pit}|RACE"
                item = next(s for s in states if s["tick_id"] == r["tick_id"])
                log = next((x for rr in json.loads((d / "summary.json").read_text())["race_results"]
                            if rr["race_index"] == item["race_index"]
                            for x in rr["team_orders"][r["team"]]["order_log"] if x["decision"] == r["decision"]), None)
                orders.append({"team": r["team"], "tick_id": r["tick_id"], "race_index": item["race_index"],
                               "lap": r["lap"], "status": r["status"], "order": order,
                               "engine_status": log["status"] if log else None,
                               "feasibility": log["feasibility"] if log else None,
                               "value_vs_same_pit_with_RACE": round(r["q_chosen"] - r["q_all"][race_key], 3)
                               if race_key in r["q_all"] else None,
                               "se": r["q_se_vs_chosen"].get(race_key)})
        commitments = [c for rr in json.loads((d / "summary.json").read_text())["race_results"]
                       for team in rr["team_orders"].values()
                       for c in ([team["commitment"]] if team["commitment"] else []) + team["closed_commitments"]]
        out["team_orders"][f"layer{layer}"] = {"orders": orders, "commitments": commitments}
        schemas, templates, versions = Counter(), Counter(), Counter()
        for t in ticks:
            for label, obs in t["observations"].items():
                schema = obs.get("action_schema") or {}
                skeleton = json.dumps({k: (v if k != "format_example" else "example") for k, v in schema.items()
                                       if k not in ("driver_a", "driver_b", "team_order")}, sort_keys=True)
                schemas[(obs["decision_type"], "format_example" in schema, skeleton.replace(label.split()[0], "TEAM"))] += 1
                versions[obs.get("benchmark_version")] += 1
            for p in t["provenance"]:
                templates[(p["team"], p["metadata"].get("prompt_template_sha256"))] += 1
        out["contract"][f"layer{layer}"] = {
            "benchmark_versions_seen": dict(versions),
            "distinct_action_schema_shapes": len(schemas),
            "all_have_format_example": all(k[1] for k in schemas),
            "prompt_template_by_team": {f"{k[0]}:{(k[1] or '')[:12]}": v for k, v in templates.items()},
            "same_template_for_both_chiefs": len({k[1] for k in templates}) == 1}
    (root / "deep.json").write_text(json.dumps(out, indent=1, default=str))
    print(json.dumps({"double_stack_recurrence": out["double_stack_recurrence"], "selectivity": {
        k: {t: {x: y for x, y in v.items() if x != "cases"} for t, v in s.items()} for k, s in out["selectivity"].items()},
        "contract": out["contract"]}, indent=1))


if __name__ == "__main__":
    main()
