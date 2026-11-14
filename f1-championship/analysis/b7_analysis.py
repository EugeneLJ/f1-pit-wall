#!/usr/bin/env python3
"""B7-P0 analysis of a live pilot season: integrity, behaviour, provider statistics, and
candidate strategic failures against the authoritative-engine public-input reference.

Reference (labelled; it has a MODEL-ACCESS ADVANTAGE over the Chiefs): at each race decision
of each team, every joint pit action (team order RACE) plus the Chief's own action is rolled
out with the exact engine over K public SC/VSC futures drawn from the published model
conditioned on the observed history; afterwards BOTH teams continue with the published
baseline rule, and the rival's same-tick action is also the baseline rule (the reference does
not see the rival's sealed action). Value = expected team points at the finish over the
published retirement probabilities. Regret = Q(best) - Q(chosen) on common futures.
A candidate strategic failure needs regret > 1.0 point AND > 2 standard errors; anything
else (different action, rejected report, broken commitment) is a diagnostic only.

Usage: scripts/py312 analysis/b7_analysis.py analysis/results/b7/layer1 [--futures 12] [--workers 10]
Writes <layer dir>/analysis.json
"""

from __future__ import annotations

import argparse
import copy
import json
import math
import multiprocessing as mp
import statistics as st
import sys
from collections import Counter, defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
TASK = HERE.parent
sys.path.insert(0, str(TASK / "src"))
sys.path.insert(0, str(TASK))
sys.path.insert(0, str(HERE))

import b6_eval as E  # noqa: E402
from f1pitwall import engine  # noqa: E402
from f1pitwall.integrated import config as C  # noqa: E402
from f1pitwall.integrated import race as ir  # noqa: E402
from f1pitwall.integrated import session as S  # noqa: E402
from f1pitwall.integrated import verify as V  # noqa: E402
from f1pitwall.integrated.engineers import EngineerBroker  # noqa: E402

SEED = 20261115
SIGNIFICANT = 1.0


def load(layer_dir):
    summary = json.loads((layer_dir / "summary.json").read_text())
    journal = [json.loads(x) for x in (layer_dir / "journal.jsonl").read_text().splitlines() if x]
    ticks = [json.loads(x) for x in (layer_dir / "ticks.jsonl").read_text().splitlines() if x]
    return summary, journal, ticks


def replay_states(cfg, journal, broker):
    """Replay the journal; capture every race decision's pre-action state and both actions."""
    V.verify_chain(journal)
    session = S.IntegratedSession(cfg, SEED, engineer_broker=broker, clock=lambda: 0.0)
    states = []
    for entry in journal:
        if entry["kind"] != "resolved":
            continue
        if session._obs_hash != entry["obs_before_sha256"]:
            raise V.ReplayError(f"{entry['tick_id']}: observation hash differs")
        if session.decision_type == S.RACE_STRATEGY:
            states.append({"tick_id": entry["tick_id"], "race_index": session.state.race_index,
                           "race": copy.deepcopy(session.race_state),
                           "actions": {label: sub["action"] for label, sub in entry["submissions"].items()},
                           "status": {label: sub["status"] for label, sub in entry["submissions"].items()},
                           "observations": {label: session.observation(label) for label in session.teams}})
        tick, late = session.tick_id, []
        for label, sub in sorted(entry["submissions"].items()):
            if sub["status"] == S.SUBMITTED:
                session.submit(label, tick, sub["action"], submitted_via=sub["submitted_via"])
            else:
                late.append(sub["status"])
        if late:
            session.close_tick(tick, reason=late[0])
        if session._obs_hash != entry["obs_after_sha256"]:
            raise V.ReplayError(f"{tick}: observation hash after differs")
    return session, states


def evaluate(args):
    item, slot_of, futures = args
    race = item["race"]
    fut = E.futures_for(race, futures, f"b7|{item['tick_id']}")
    legal = engine.legal_actions(race)
    out = {}
    for label, slot in slot_of.items():
        other = next(s for s in slot_of.values() if s != slot)
        chosen = item["actions"][label]
        chosen_action = {"driver_a": chosen["driver_a"], "driver_b": chosen["driver_b"], "team_order": chosen["team_order"]}
        rival_now = E.policy_action("baseline", race, other)
        cont = {slot: "baseline", other: "baseline"}
        cands = {f"{a}/{b}|RACE": {"driver_a": a, "driver_b": b, "team_order": {"order": "RACE"}}
                 for a in legal for b in legal}
        key = f"{chosen['driver_a']}/{chosen['driver_b']}|{chosen['team_order']['order']}"
        cands.setdefault(key, chosen_action)
        if chosen_action["team_order"]["order"] not in ir.legal_team_orders(race, slot):
            continue
        q = {}
        for k, act in cands.items():
            if "RACE" not in ir.legal_team_orders(race, slot) and k.endswith("|RACE"):
                act = {**act, "team_order": {"order": "KEEP_ORDER"}}
            vals = []
            for f in fut:
                first = {slot: act, other: rival_now}
                vals.append(E.expected_team_points(E.rollout(race, first, cont, f), slot))
            q[k] = vals
        best = max(q, key=lambda k: st.mean(q[k]))
        diff = [x - y for x, y in zip(q[best], q[key])]
        se = st.pstdev(diff) / math.sqrt(len(diff)) if len(diff) > 1 else 0.0
        out[label] = {"chosen": key, "reference": best, "regret": round(st.mean(diff), 4), "se": round(se, 4),
                      "q_chosen": round(st.mean(q[key]), 3), "q_reference": round(st.mean(q[best]), 3),
                      "q_all": {k: round(st.mean(v), 4) for k, v in q.items()},
                      "q_se_vs_chosen": {k: round(st.pstdev([x - y for x, y in zip(v, q[key])]) / math.sqrt(len(v)), 4)
                                         for k, v in q.items()}}
    return item["tick_id"], out


def tags(item, label, slot, cfg_layer, records_by_tick):
    """Context tags (not causal attributions)."""
    race, action = item["race"], item["actions"][label]
    status = race["events"][race["step"]]
    t = []
    if status != "GREEN":
        t.append(f"event:{status}")
    if action["driver_a"] != "STAY" and action["driver_b"] != "STAY":
        t.append("double_stack")
    if action["team_order"]["order"] != "RACE" or ir.exchange_feasibility(race, slot, {})["executable"]:
        t.append("coordination:team_order_context")
    order = sorted(race["cars"], key=lambda c: (c["elapsed"], c["name"]))
    own = set(ir.team_cars(slot).values())
    rival_team = set()  # the other controlled team's two cars
    for other in race["integrated"]["controlled"]:
        if other != slot:
            rival_team |= set(ir.team_cars(other).values())
    for i, car in enumerate(order):
        if car["name"] in own:
            for j in (i - 1, i + 1):
                if 0 <= j < len(order) and order[j]["name"] in rival_team and \
                        abs(order[j]["elapsed"] - car["elapsed"]) < 2.0:
                    t.append("opponent:rival_team_within_2s")
                    break
    recs = records_by_tick.get((label, item["tick_id"]), [])
    for r in recs:
        rec = r.get("recommendation") or {}
        prop = rec.get("proposed_action", {})
        if "choice" in prop and action.get(prop["driver"]) != prop["choice"]:
            t.append(f"coordination:differs_from_{r['engineer_id']}")
    if item["status"][label] != S.SUBMITTED:
        t.append(f"fallback:{item['status'][label]}")
    return sorted(set(t))


def behaviour(session, states, ticks, slot_of, journal):
    out = {}
    prov = [p for t in ticks for p in t["provenance"]]
    for label, slot in slot_of.items():
        acts = [s["actions"][label] for s in states]
        pits = Counter(a[k] for a in acts for k in ("driver_a", "driver_b") if a[k] != "STAY")
        neutral = [s for s in states if s["race"]["events"][s["race"]["step"]] != "GREEN"]
        team_p = [p for p in prov if p["team"] == label]
        md = [p["metadata"] for p in team_p]
        lat = [p["latency_ms"] for p in team_p]
        usage = [m.get("usage") or {} for m in md]
        cons = [len(s["actions"][label].get("consumed_reports", [])) for s in states]
        team_orders = defaultdict(Counter)
        commitments = Counter()
        for rr in session.race_results:
            team = rr["team_orders"][label]
            for r in team["order_log"]:
                team_orders[r["order"]][r["status"]] += 1
            for c in ([team["commitment"]] if team["commitment"] else []) + team["closed_commitments"]:
                commitments[c["status"]] += 1
        out[label] = {
            "pit_stops_by_compound": dict(pits), "stops_total": sum(pits.values()),
            "double_stacks": sum(1 for a in acts if a["driver_a"] != "STAY" and a["driver_b"] != "STAY"),
            "neutralized_decisions": len(neutral),
            "stops_under_sc_vsc": sum((s["actions"][label]["driver_a"] != "STAY") + (s["actions"][label]["driver_b"] != "STAY")
                                      for s in neutral),
            "team_orders": {k: dict(v) for k, v in team_orders.items()},
            "commitments": dict(commitments),
            "decisions_citing_engineer_reports": sum(1 for c in cons if c),
            "provider_status": dict(Counter(p["status"] for p in team_p)),
            "invalid_outputs": sum(1 for m in md if m.get("status") == "INVALID_OUTPUT"),
            "retries": sum(m.get("retries") or 0 for m in md),
            "returned_models": dict(Counter(m.get("returned_model") for m in md)),
            "latency_ms": {"mean": round(st.mean(lat), 1), "p95": sorted(lat)[int(0.95 * len(lat)) - 1], "max": max(lat)} if lat else None,
            "tokens": {k: sum(u.get(k) or 0 for u in usage) for k in ("input_tokens", "output_tokens", "thinking_tokens")},
            "estimated_cost_usd": round(sum((m.get("estimated_cost") or {}).get("amount") or 0 for m in md), 6),
            "tool_delegation": "not applicable: direct-API Chief without tools (submitted_via=provider)",
        }
    return out


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("layer_dir")
    parser.add_argument("--futures", type=int, default=12)
    parser.add_argument("--workers", type=int, default=10)
    args = parser.parse_args()
    layer_dir = Path(args.layer_dir)
    summary, journal, ticks = load(layer_dir)
    cfg = C.IntegratedConfig.from_dict(summary["config"])
    layer = summary["layer"]
    broker = EngineerBroker.replaying(layer_dir / "engineers") if layer == 2 else None
    session, states = replay_states(cfg, journal, broker)
    slot_of = {t.label: t.slot for t in cfg.teams}
    records_by_tick = defaultdict(list)
    if layer == 2:
        for path in (layer_dir / "engineers").rglob("*.jsonl"):
            for line in path.read_text().splitlines():
                r = json.loads(line)
                records_by_tick[(r["team"], r["tick_id"])].append(r)
    with mp.Pool(args.workers) as pool:
        evals = dict(pool.map(evaluate, [(s, slot_of, args.futures) for s in states], chunksize=4))
    decisions, candidates = [], []
    for s in states:
        for label, slot in slot_of.items():
            ev = evals.get(s["tick_id"], {}).get(label)
            if ev is None:
                continue
            row = {"tick_id": s["tick_id"], "race_index": s["race_index"], "decision": s["race"]["step"] + 1,
                   "lap": engine._decision_laps(s["race"])[s["race"]["step"]], "team": label,
                   "status": s["race"]["events"][s["race"]["step"]], **ev,
                   "tags": tags(s, label, slot, layer, records_by_tick)}
            decisions.append(row)
            if ev["regret"] > SIGNIFICANT and ev["regret"] > 2 * ev["se"]:
                obs = s["observations"][label]["race_progress"]
                candidates.append({**row, "legal_actions": obs["legal_actions"],
                                   "legal_team_orders": s["observations"][label]["team_orders"]["legal_team_orders"],
                                   "own_cars": obs["drivers"], "track_status": obs["track_status"],
                                   "replay_reproduces_observation": True})
    standings = session.standings()
    a, b = (t.label for t in cfg.teams)
    result = {
        "layer": layer, "complete": session.decision_type == S.CHAMPIONSHIP_COMPLETE,
        "replay": {"ok": standings == summary["standings"], "resolved_ticks": len([e for e in journal if e["kind"] == "resolved"]),
                   "rejected_entries": len([e for e in journal if e["kind"] == "rejected"])},
        "standings": standings, "margin": standings["team_points"][a] - standings["team_points"][b],
        "per_race": [{"race": rr["race_name"], "events": "".join({"GREEN": ".", "SC": "S", "VSC": "V"}[e] for e in rr["events"]),
                      "team_points": {a: rr["team_points"][a], b: rr["team_points"][b]}} for rr in session.race_results],
        "behaviour": behaviour(session, states, ticks, slot_of, journal),
        "reference": {"kind": "authoritative-engine public-input rollout (model-access advantage)",
                      "futures": args.futures, "continuation": "baseline rule for both teams",
                      "rival_same_tick": "baseline rule (sealed rival action not used)",
                      "candidate_rule": "regret > 1.0 and > 2 se"},
        "regret_summary": {label: {"decisions": len(rows), "mean_regret": round(st.mean(r["regret"] for r in rows), 3),
                                   "sum_regret": round(sum(r["regret"] for r in rows), 2),
                                   "same_as_reference": round(st.mean(r["chosen"] == r["reference"] for r in rows), 3),
                                   "candidates": sum(1 for c in candidates if c["team"] == label)}
                           for label in slot_of for rows in [[r for r in decisions if r["team"] == label]] if rows},
        "candidate_tags": {label: dict(Counter(t for c in candidates if c["team"] == label for t in c["tags"]))
                           for label in slot_of},
        "candidates": candidates, "decisions": decisions,
    }
    if layer == 2:
        acc = defaultdict(Counter)
        for s in states:
            act = s["actions"]["McLearn Racing"]
            for r in records_by_tick.get(("McLearn Racing", s["tick_id"]), []):
                rec = r.get("recommendation")
                if rec is None:
                    acc[r["engineer_id"]][f"report_{r['status']}"] += 1
                    continue
                prop = rec["proposed_action"]
                if "choice" in prop:
                    acc[r["engineer_id"]]["followed" if act.get(prop["driver"]) == prop["choice"] else "not_followed"] += 1
                else:
                    acc[r["engineer_id"]]["team_order_request"] += 1
                acc[r["engineer_id"]]["cited" if r["record_hash"] in act.get("consumed_reports", []) else "not_cited"] += 1
        result["engineer_use"] = {k: dict(v) for k, v in acc.items()}
    (layer_dir / "analysis.json").write_text(json.dumps(result, indent=1, default=str))
    print(json.dumps({k: result[k] for k in ("layer", "complete", "replay", "standings", "margin", "regret_summary",
                                             "candidate_tags")}, indent=1))


if __name__ == "__main__":
    main()
