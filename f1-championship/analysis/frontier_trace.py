#!/usr/bin/env python3
"""Verifier-side analysis of a frontier run from its sealed sidecar journal.

Replays the journal with the hidden seed (evaluation only; the agent never had it) and:
  * per race: points, Apex results, events, replacements, grid drops, pit/compound actions
  * per race decision: expected Apex points (exact retirement expectation) of the agent's
    action, of the best public-information alternative and of the baseline's action, each
    played now with a fixed continuation afterwards (the public baseline, or with
    --agent-policy the agent's own written policy) over public futures conditioned only on
    what the agent had observed. The best action is selected on one future set and all
    values are re-estimated on an independent set; a paired standard error is reported.
  * Track A isolation: the agent's component plan vs rule/greedy/do-nothing component plans,
    all with the public baseline race play, expected over public CRN paths (same engine).
  * Seed-specific baselines on the hidden seed (realized), labelled as single-seed numbers.

Usage: python3 analysis/frontier_trace.py <evidence_dir> <out.json> [--futures 48] [--workers 10]
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
TASK = HERE.parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(TASK / "solution"))

import track_a_solver as ts  # noqa: E402
from f1pitwall import engine  # noqa: E402
from f1pitwall.championship_contract import ChampionshipSession  # noqa: E402
from f1pitwall.journal import parse_journal, verify_chain  # noqa: E402

SEED = json.loads((TASK / "tests" / "hidden_seed.json").read_text())["base_seed"]
FUTURES = 48


def replay_decisions(entries):
    """Yield (entry, session-before) for every accepted entry, replaying from the hidden seed."""
    session = ChampionshipSession(base_seed=SEED)
    for entry in entries:
        if entry["kind"] != "accepted":
            continue
        before = copy.deepcopy(session)
        session.submit(copy.deepcopy(entry["action"]))
        yield entry, before, session


CONTINUATION = None  # None -> public baseline; otherwise a callable(race observation) -> action


def continuation(node):
    obs = engine.observation(node)
    if CONTINUATION is None:
        return ts.baseline_race_action(obs)
    action = CONTINUATION({"race_progress": obs})
    return {"driver_a": action["driver_a"], "driver_b": action["driver_b"]}


def load_agent_policy(path):
    """The agent's own race policy (e.g. a script it wrote), used as the continuation."""
    import importlib.util
    spec = importlib.util.spec_from_file_location("agent_policy", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.decide_strategy


def q_eval(node, keys, futures):
    out = {}
    for key in keys:
        a, b = key.split("/")
        vals = []
        for future in futures:
            child = ts._copy_race(node)
            engine.step(child, {"driver_a": a, "driver_b": b})
            child["events"][child["step"]:] = future
            while child["step"] < len(child["events"]):
                engine.step(child, continuation(child))
            vals.append(ts.expected_apex_points_at_finish(child))
        out[key] = vals
    return out


def decision_job(args):
    node, agent_key, meta, futures_n, policy_path = args
    global CONTINUATION
    CONTINUATION = load_agent_policy(policy_path) if policy_path else None
    legal = engine.legal_actions(node)
    keys = [f"{a}/{b}" for a in legal for b in legal]
    select = ts.public_futures(node, futures_n, "select")
    qs = {k: st.mean(v) for k, v in q_eval(node, keys, select).items()}
    best = max(qs, key=qs.get)
    base = ts.baseline_race_action(engine.observation(node))
    base_key = f"{base['driver_a']}/{base['driver_b']}"
    evaluate = ts.public_futures(node, futures_n, "evaluate")
    ev = q_eval(node, {best, agent_key, base_key, "STAY/STAY"}, evaluate)
    diff = [x - y for x, y in zip(ev[best], ev[agent_key])]
    se = st.pstdev(diff) / math.sqrt(len(diff)) if len(diff) > 1 else 0.0
    return {**meta, "agent": agent_key, "best": best, "baseline": base_key,
            "q_agent": st.mean(ev[agent_key]), "q_best": st.mean(ev[best]), "q_baseline": st.mean(ev[base_key]),
            "q_stay": st.mean(ev["STAY/STAY"]), "loss_vs_best": st.mean(diff), "loss_se": se,
            "baseline_minus_agent": st.mean(ev[base_key]) - st.mean(ev[agent_key]),
            "selection_spread": max(qs.values()) - min(qs.values())}


def season_with_components(component_options, coeffs=None):
    """Expected season points (public CRN race values) of a component plan with baseline race play."""
    from f1pitwall import coefficients as coef
    from f1pitwall.championship import new_championship_state
    from f1pitwall.championship_transition import initial_inventory
    coeffs = coeffs or coef.DEFAULT
    solver = ts.Solver(coeffs)
    state = new_championship_state(resource_inventory=initial_inventory(coeffs))
    per_race = []
    for option in component_options:
        option = option(state, solver) if callable(option) else option
        prepared = ts.prepare(state, option, coeffs)
        per_race.append(solver.race_value(prepared))
        state = ts.after_race(prepared, coeffs)
    return per_race


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("evidence")
    parser.add_argument("out")
    parser.add_argument("--futures", type=int, default=FUTURES)
    parser.add_argument("--workers", type=int, default=10)
    parser.add_argument("--agent-policy", default=None,
                        help="python file with decide_strategy(obs): use the agent's own policy as continuation")
    parser.add_argument("--decisions-only", action="store_true")
    args = parser.parse_args()
    raw = (Path(args.evidence) / "journal.jsonl").read_text()
    entries = parse_journal(raw)
    verify_chain(entries)
    rejected = [e for e in entries if e["kind"] == "rejected"]

    races, jobs, components = [], [], []
    current = None
    for entry, before, after in replay_decisions(entries):
        if entry["decision_type"] == "COMPONENT_DECISION":
            obs = before.observation()
            option = tuple((d["driver"], d["component"], d["action"]) for d in entry["action"]["decisions"])
            full = tuple((d, c, dict(((x[0], x[1]), x[2]) for x in option).get((d, c), "USE"))
                         for d in ts.APEX for c in ts.COMPONENTS)
            components.append(full)
            current = {"race_index": obs["championship"]["race_index"], "track": obs["current_track"],
                       "replacements": [f"{d}:{c}" for d, c, a in full if a == "REPLACE"],
                       "free_units_before": obs["resource_inventory"].get("component_spares"),
                       "grid_drops": dict(after.state.grid_penalties) if after.state.race_prepared else None,
                       "decisions": [], "t": entry["t_received"]}
            races.append(current)
            continue
        node = ts._copy_race(before._active_race.race_state)
        obs = engine.observation(node)
        key = f"{entry['action']['driver_a']}/{entry['action']['driver_b']}"
        status = node["events"][node["step"]]
        prev = node["events"][node["step"] - 1] if node["step"] > 0 else "GREEN"
        category = "replanning" if status != "GREEN" or prev != "GREEN" else "in_race"
        meta = {"race_index": current["race_index"], "decision": node["step"] + 1, "lap": obs["lap"],
                "status": status, "category": category, "seq": entry["seq"],
                "drivers": {k: [v["position"], v["compound"], v["tyre_age"], v.get("compounds_used")]
                            for k, v in obs["drivers"].items()},
                "latency_since_previous_sec": None}
        current["decisions"].append({"action": key, "status": status, "lap": obs["lap"]})
        jobs.append((node, key, meta, args.futures, args.agent_policy))
        if after.state.race_index != before.state.race_index:  # race finished with this decision
            last = after.trace()[-1]["state_transition"]
            current["classification"] = last.get("classification")
            current["awarded_points"] = last.get("awarded_points")
            current["apex_points"] = sum(v for k, v in last["awarded_points"].items() if k.startswith("Apex"))

    accepted = [e for e in entries if e["kind"] == "accepted"]
    gaps = [b["t_received"] - a["t_done"] for a, b in zip(accepted, accepted[1:])]
    with mp.Pool(args.workers) as pool:
        decisions = pool.map(decision_job, jobs)

    from f1pitwall import coefficients as coef
    if args.decisions_only:
        Path(args.out).write_text(json.dumps({"continuation": args.agent_policy or "baseline",
                                              "decisions": decisions}, indent=1, default=str))
        return
    seasons = {"agent_components": season_with_components(components)}
    for rule in ("always_use", "rival_rule", "greedy"):
        seasons[f"{rule}_components"] = season_with_components([lambda s, sv, r=rule: sv.choose(s, r)] * len(components))
    out = {"accepted": len(accepted), "rejected": len(rejected),
           "rejected_codes": sorted({e["error_code"] for e in rejected}),
           "complete": len(races) == 8 and all("apex_points" in r for r in races),
           "races": races, "decisions": decisions,
           "track_a_expected_points_with_baseline_race_play": {k: {"per_race": v, "total": sum(v)} for k, v in seasons.items()},
           "timing": {"first": accepted[0]["t_received"] if accepted else None,
                      "last": accepted[-1]["t_done"] if accepted else None,
                      "mean_gap_sec": st.mean(gaps) if gaps else None,
                      "median_gap_sec": st.median(gaps) if gaps else None,
                      "max_gap_sec": max(gaps) if gaps else None}}
    Path(args.out).write_text(json.dumps(out, indent=1, default=str))
    print(json.dumps({k: out[k] for k in ("accepted", "rejected", "complete", "timing")}, indent=1))


if __name__ == "__main__":
    main()
