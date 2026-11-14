#!/usr/bin/env python3
"""B6 evaluation: integrated solo coordination, two-team scripted competition, best-response
sensitivity to the rival's strategy, and the value of team orders / give-backs.

All values are EXPECTED team points at the finish (exact over the published retirement
probabilities, never the hidden retirement draws), averaged over public SC/VSC futures drawn
from the published model conditioned on the observed history (`event_policies.generate`,
mode 'full'), with the authoritative engine and a stated continuation policy. This is the
"authoritative-engine reference using public inputs"; it is not a hindsight oracle.

Usage: scripts/py312 analysis/b6_eval.py [--seeds 12] [--futures 12] [--workers 10]
Writes analysis/results/b6_eval.json
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
import tempfile
import time
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
TASK = HERE.parent
sys.path.insert(0, str(TASK / "src"))
sys.path.insert(0, str(TASK))
sys.path.insert(0, str(HERE))

import event_policies as ep  # noqa: E402
from f1pitwall import engine  # noqa: E402
from f1pitwall.integrated import config as C  # noqa: E402
from f1pitwall.integrated import match as M  # noqa: E402
from f1pitwall.integrated import policies as P  # noqa: E402
from f1pitwall.integrated import race as ir  # noqa: E402
from f1pitwall.integrated import session as S  # noqa: E402
from f1pitwall.integrated import verify as V  # noqa: E402
from f1pitwall.integrated.engineers import EngineerBroker  # noqa: E402

RIVALS = ("baseline", "conservative_2stop", "opportunistic", "undercut", "long_stint", "event_aware")
T95 = 1.96


def ci(values):
    values = list(values)
    if len(values) < 2:
        return {"mean": values[0] if values else None, "n": len(values)}
    m, se = st.mean(values), st.stdev(values) / math.sqrt(len(values))
    return {"mean": round(m, 3), "lo": round(m - T95 * se, 3), "hi": round(m + T95 * se, 3), "n": len(values)}


def expected_team_points(race, slot):
    order = sorted(race["cars"], key=lambda c: (c["elapsed"] + engine.finish_penalty(race, c), c["name"]))
    p = race["config"]["dnf_prob"]
    total = 0.0
    for index, car in enumerate(order):
        if car["team"] != slot:
            continue
        dist = [1.0]
        for ahead in order[:index]:
            q = 1.0 - p[ahead["name"]]
            nxt = [0.0] * (len(dist) + 1)
            for k, mass in enumerate(dist):
                nxt[k] += mass * (1 - q)
                nxt[k + 1] += mass * q
            dist = nxt
        total += (1 - p[car["name"]]) * sum(m * engine.POINTS[k] for k, m in enumerate(dist))
    return total


def team_obs(race, slot):
    view = S.team_race_view(race, slot, lambda n: n, {s: s for s in C.SLOTS}, "rollout")
    return {"decision_type": "RACE_STRATEGY", "race_progress": view, "team_orders": ir.public_order_view(race, slot)}


def policy_action(name, race, slot):
    a = P.race_action(name, team_obs(race, slot))
    return {"driver_a": a["driver_a"], "driver_b": a["driver_b"], "team_order": a["team_order"]}


def rollout(race, first, policies, future):
    """Apply `first` actions now, then everyone follows `policies` on a fixed public future."""
    node = copy.deepcopy(race)
    ir.step(node, first)
    node["events"][node["step"]:] = future
    while not node["complete"]:
        ir.step(node, {slot: policy_action(name, node, slot) for slot, name in policies.items()})
    return node


def futures_for(race, k, tag):
    rng = random.Random(f"b6|{tag}|{race['step']}|{race['events'][:race['step'] + 1]}")
    history = race["events"][:race["step"] + 1]
    return [ep.generate(rng, history, len(race["events"]), race["config"]["neutralization"], "full")
            for _ in range(k)]


# ------------------------------------------------------------------ B6-A
def solo_seasons(seeds, tmp):
    out = []
    for cond in ("CHIEF_ONLY", "MOCK_ENGINEERS", "CONFLICTING_LOCAL_RECOMMENDATIONS"):
        for seed in seeds:
            cfg = C.solo_coordination(engineers=cond)
            broker = EngineerBroker(Path(tmp) / f"{cond}-{seed}") if cond != "CHIEF_ONLY" else None
            res = M.run_season(cfg, seed, {"Apex": P.scripted("coordinator")}, engineer_broker=broker)
            replay_broker = EngineerBroker.replaying(Path(tmp) / f"{cond}-{seed}") if broker else None
            rep = V.replay(cfg, seed, res["journal"], engineer_broker=replay_broker)
            orders, commitments = Counter(), Counter()
            for rr in res["race_results"]:
                team = rr["team_orders"]["Apex"]
                for r in team["order_log"]:
                    if r["order"] != "RACE":
                        orders[f"{r['order']}:{r['status']}"] += 1
                for c in ([team["commitment"]] if team["commitment"] else []) + team["closed_commitments"]:
                    commitments[c["status"]] += 1
            reports = sum(len(e["engineer_record_hashes"].get("Apex", [])) for e in res["journal"] if e["kind"] == "resolved")
            out.append({"condition": cond, "seed": seed, "points": res["standings"]["team_points"]["Apex"],
                        "replay_ok": rep["standings"] == res["standings"], "ticks": rep["resolved_ticks"],
                        "orders": dict(orders), "commitments": dict(commitments), "engineer_records": reports,
                        "points_conserved": all(sum(rr["team_points"].values()) == sum(
                            e["points"] for e in rr["classification"]) for rr in res["race_results"]),
                        "unique_classification": all(sorted(e["position"] for e in rr["classification"]) == list(range(1, 9))
                                                     for rr in res["race_results"])})
    return out


def representative_trajectory(seeds):
    for seed in seeds:
        res = M.run_season(C.solo_coordination(), seed, {"Apex": P.scripted("coordinator")})
        for rr in res["race_results"]:
            team = rr["team_orders"]["Apex"]
            cs = ([team["commitment"]] if team["commitment"] else []) + team["closed_commitments"]
            if cs:
                return {"seed_id": res["base_seed_id"], "race": rr["race_name"], "events": "".join(
                    {"GREEN": ".", "SC": "S", "VSC": "V"}[e] for e in rr["events"]),
                        "order_log": [r for r in team["order_log"] if r["order"] != "RACE"],
                        "commitments": cs, "team_points": rr["team_points"]}
    return None


# ------------------------------------------------------------------ B6-B
def two_team_matrix(seeds):
    rows = []
    for mpol in ("baseline", "coordinator"):
        for rpol in RIVALS:
            margins, mpts = [], []
            for seed in seeds:
                pair = M.run_slot_swapped_pair(C.two_team(1), seed, {"McLearn Racing": P.scripted(mpol),
                                                                     "Red Bool Racing": P.scripted(rpol)})
                margins.append(pair["slot_averaged_margin"])
                mpts.append(st.mean(r["standings"]["team_points"]["McLearn Racing"] for r in pair["runs"]))
            rows.append({"mclearn": mpol, "redbool": rpol, "slot_averaged_margin": ci(margins),
                         "mclearn_points": ci(mpts), "estimand": "ADAPTIVE, slot-swapped, same seeds"})
    return rows


def fixed_vs_adaptive(seeds):
    """Fixed-rival replay vs live adaptive rival: the rival (undercut rule, which reacts to the
    car ahead) is recorded against McLearn=baseline; McLearn then switches to long_stint."""
    out = []
    for seed in seeds:
        live = M.run_season(C.two_team(1), seed, {"McLearn Racing": P.scripted("baseline"),
                                                  "Red Bool Racing": P.scripted("undercut")})
        fixed = M.run_season(C.two_team(1, rival_condition="FIXED_REPLAY"), seed,
                             {"McLearn Racing": P.scripted("long_stint"),
                              "Red Bool Racing": M.ReplayPolicy(live["journal"], "Red Bool Racing")})
        adaptive = M.run_season(C.two_team(1), seed, {"McLearn Racing": P.scripted("long_stint"),
                                                      "Red Bool Racing": P.scripted("undercut")})
        invalid = sum(1 for p in fixed["provenance"] if p["team"] == "Red Bool Racing" and p["status"] != "SUBMITTED")
        changed = sum(1 for a, b in zip(fixed["journal"], adaptive["journal"])
                      if a["kind"] == b["kind"] == "resolved" and
                      a["submissions"]["Red Bool Racing"]["action"] != b["submissions"]["Red Bool Racing"]["action"])
        out.append({"seed": seed, "fixed_mclearn": fixed["standings"]["team_points"]["McLearn Racing"],
                    "adaptive_mclearn": adaptive["standings"]["team_points"]["McLearn Racing"],
                    "baseline_mclearn_vs_recorded_rival": live["standings"]["team_points"]["McLearn Racing"],
                    "rival_actions_that_differ_fixed_vs_adaptive": changed,
                    "fixed_replay_illegal_actions": invalid})
    return out


# ------------------------------------------------------------------ best response & order values
def sample_states(seed, every=3):
    """Race states visited by baseline vs baseline (two-team), McLearn in slot Apex."""
    s = S.IntegratedSession(C.two_team(1), seed)
    pol = {"McLearn Racing": P.scripted("baseline"), "Red Bool Racing": P.scripted("baseline")}
    states = []
    while s.decision_type != S.CHAMPIONSHIP_COMPLETE:
        if s.decision_type == S.RACE_STRATEGY and s.race_state["step"] % every == 0 and s.race_state["step"] < 12:
            states.append((s.state.race_index, copy.deepcopy(s.race_state)))
        tick = s.tick_id
        for label in s.teams:
            s.submit(label, tick, pol[label](s.observation(label)))
    return states


def best_response_job(args):
    seed, futures = args
    out = []
    for race_index, race in sample_states(seed):
        fut = futures_for(race, futures, f"br{seed}")
        legal = engine.legal_actions(race)
        cands = [(a, b) for a in legal for b in legal]
        best, values = {}, {}
        for rpol in RIVALS:
            rival_now = policy_action(rpol, race, "Orion")
            q = {}
            for a, b in cands:
                first = {"Apex": {"driver_a": a, "driver_b": b, "team_order": {"order": "RACE"}}, "Orion": rival_now}
                q[f"{a}/{b}"] = st.mean(expected_team_points(rollout(race, first, {"Apex": "baseline", "Orion": rpol}, f),
                                                             "Apex") for f in fut)
            best[rpol] = max(q, key=q.get)
            values[rpol] = q
        loss = {r: round(values[r][best[r]] - values[r][best["baseline"]], 4) for r in RIVALS}
        out.append({"seed": seed, "race_index": race_index, "decision": race["step"] + 1,
                    "status": race["events"][race["step"]], "best": best, "loss_if_assume_baseline_rival": loss})
    return out


def order_value_job(args):
    """At every state where a McLearn exchange is executable: value of each team order, and for
    a SWAP with commitment, value of KEEP_ORDER vs REQUEST_GIVE_BACK when it falls due."""
    seed, futures = args
    s = S.IntegratedSession(C.two_team(1), seed)
    pol = {"McLearn Racing": P.scripted("baseline"), "Red Bool Racing": P.scripted("baseline")}
    rows = []
    while s.decision_type != S.CHAMPIONSHIP_COMPLETE:
        if s.decision_type == S.RACE_STRATEGY:
            race = s.race_state
            feas = ir.exchange_feasibility(race, "Apex", {})
            if feas["executable"] and race["step"] < 12:
                rows.append(_order_values(copy.deepcopy(race), feas, futures, seed))
        tick = s.tick_id
        for label in s.teams:
            s.submit(label, tick, pol[label](s.observation(label)))
    return rows


def _order_values(race, feas, futures, seed):
    fut = futures_for(race, futures, f"ov{seed}")
    base = policy_action("baseline", race, "Apex")
    rival = policy_action("baseline", race, "Orion")
    cont = {"Apex": "baseline", "Orion": "baseline"}
    q, driver = {}, {}
    for order in ("RACE", "HOLD", "SWAP", "DEFENSIVE_BUFFER"):
        first = {"Apex": {**base, "team_order": {"order": order}}, "Orion": rival}
        finals = [rollout(race, first, cont, f) for f in fut]
        q[order] = st.mean(expected_team_points(n, "Apex") for n in finals)
        driver[order] = _driver_positions(finals)
    lap = engine._decision_laps(race)[race["step"]]
    give = None
    if feas["car_ahead"] and lap + 3 <= engine.laps_total(race) and base["driver_a"] == base["driver_b"] == "STAY":
        commit = {"objective": "PASS_CAR_AHEAD", "deadline_lap": lap + 3, "give_back_if": "OBJECTIVE_NOT_MET"}
        swapped = copy.deepcopy(race)
        ir.step(swapped, {"Apex": {**base, "team_order": {"order": "SWAP", "commitment": commit}}, "Orion": rival})
        c = swapped["integrated"]["teams"]["Apex"]["commitment"]
        if c is not None and c["status"] == "DUE" and not swapped["complete"]:
            fut2 = futures_for(swapped, futures, f"gb{seed}")
            vals, drv = {}, {}
            for follow in ("KEEP_ORDER", "REQUEST_GIVE_BACK"):
                first = {"Apex": {**policy_action("baseline", swapped, "Apex"), "team_order": {"order": follow}},
                         "Orion": policy_action("baseline", swapped, "Orion")}
                finals = [rollout(swapped, first, cont, f) for f in fut2]
                vals[follow] = st.mean(expected_team_points(n, "Apex") for n in finals)
                drv[follow] = _driver_positions(finals)
            give = {"team_points": vals, "driver_mean_position": drv,
                    "feasible_and_safe": bool(c["give_back_feasibility"]["executable_if_no_pit"]
                                              and c["give_back_feasibility"]["safe"])}
    return {"seed": seed, "decision": race["step"] + 1, "lap": lap, "status": race["events"][race["step"]],
            "safe": feas["safe"], "gap": feas["gap_sec"], "rear_gap": feas["rear_gap_sec"],
            "values": q, "driver_mean_position": driver, "give_back": give}


def _driver_positions(finals):
    pos = {"driver_a": [], "driver_b": []}
    for n in finals:
        order = [c["name"] for c in sorted(n["cars"], key=lambda c: (c["elapsed"] + engine.finish_penalty(n, c), c["name"]))]
        for k, name in ir.team_cars("Apex").items():
            pos[k].append(order.index(name) + 1)
    return {k: round(st.mean(v), 3) for k, v in pos.items()}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--seeds", type=int, default=12)
    parser.add_argument("--futures", type=int, default=12)
    parser.add_argument("--workers", type=int, default=10)
    parser.add_argument("--only", choices=["solo_fixed"], default=None,
                        help="recompute only solo seasons and fixed-vs-adaptive into the existing results file")
    args = parser.parse_args()
    if args.only:
        path = HERE / "results" / "b6_eval.json"
        out = json.loads(path.read_text())
        seeds = list(range(100, 100 + out["seeds"]))
        with tempfile.TemporaryDirectory() as tmp:
            out["solo"] = solo_seasons(seeds[:4], tmp)
        out["fixed_vs_adaptive"] = fixed_vs_adaptive(seeds[:8])
        path.write_text(json.dumps(out, indent=1))
        print("updated solo and fixed_vs_adaptive")
        return
    seeds = list(range(100, 100 + args.seeds))
    started = time.time()
    out = {"seeds": len(seeds), "futures": args.futures}
    with tempfile.TemporaryDirectory() as tmp:
        out["solo"] = solo_seasons(seeds[:4], tmp)
    out["trajectory"] = representative_trajectory(seeds)
    out["matrix"] = two_team_matrix(seeds)
    out["fixed_vs_adaptive"] = fixed_vs_adaptive(seeds[:8])
    with mp.Pool(args.workers) as pool:
        out["best_response"] = [r for part in pool.map(best_response_job, [(s, args.futures) for s in seeds]) for r in part]
        out["order_values"] = [r for part in pool.map(order_value_job, [(s, args.futures) for s in seeds]) for r in part]
    out["wall_seconds"] = round(time.time() - started, 1)
    (HERE / "results" / "b6_eval.json").write_text(json.dumps(out, indent=1))
    print(f"wall {out['wall_seconds']}s best-response states {len(out['best_response'])} "
          f"order states {len(out['order_values'])}")


if __name__ == "__main__":
    from _runtime import require_runtime_python
    require_runtime_python()
    main()
