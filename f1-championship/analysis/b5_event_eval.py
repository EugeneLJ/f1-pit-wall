#!/usr/bin/env python3
"""B5-P1: value of SC/VSC information, decision reversals, and Gemini-policy attribution.

Scenarios: 24 generated calendars x races 1, 4, 7 (public-rule history, replacement-rule
components), each a race-start state built through the real ChampionshipSession (so agent
policies receive the exact agent-visible observation). For every state:
  natural paths      NATURAL paths drawn from the TRUE published SC/VSC process (eval seeds)
  event paths        EVENT paths drawn the same way, conditioned on >= 1 SC/VSC (rejection)
Every policy plays every path; planners only ever see statuses up to the current decision.
Evaluation seeds are separate from planner sampling, and decision-level values are re-estimated
on a third, independent set of futures ("evaluate") to avoid best-action selection bias.

Usage: scripts/py312 analysis/b5_event_eval.py [--scenarios 24] [--natural 3] [--event 3] [--workers 10]
Writes analysis/results/b5_event_eval.json
"""

from __future__ import annotations

import argparse
import contextlib
import importlib.util
import io
import json
import math
import multiprocessing as mp
import random
import statistics as st
import sys
import time
from importlib.machinery import SourceFileLoader
from pathlib import Path

HERE = Path(__file__).resolve().parent
TASK = HERE.parent
sys.path.insert(0, str(HERE))

import event_policies as ep  # noqa: E402
import frontier_trace as ft  # noqa: E402
import track_a_solver as ts  # noqa: E402
from f1pitwall import coefficients as coef  # noqa: E402
from f1pitwall import engine  # noqa: E402
from f1pitwall.championship import new_championship_state  # noqa: E402
from f1pitwall.championship_contract import ChampionshipSession  # noqa: E402
from f1pitwall.championship_transition import initial_inventory  # noqa: E402

RACE_INDICES = (0, 3, 6)
EVAL_FUTURES = 48
GREEN_SAMPLE = 0.15
SIGNIFICANT, NEAR_TIE = 1.0, 0.25
RUNS = HERE / "results" / "rep_runs"
GEMINI = {  # agent-written race policies, unchanged (component part not used: in-race replay only)
    "r0": (RUNS / "r0" / "scripts" / "app_pitwall_bot.py.txt", "decide_strategy"),
    "r1": (RUNS / "r1" / "scripts" / "app_champion.py.txt", "choose_race_strategy"),
    "r2": (RUNS / "r2" / "scripts" / "app_run_championship.py.txt", "evaluate_best_race_action"),
    "r3": (RUNS / "r3" / "scripts" / "app_run_championship.py.txt", "decide_race_strategy"),
}
_MODULES = {}


def gemini_fn(name):
    if name not in _MODULES:
        path, fn = GEMINI[name]
        spec = importlib.util.spec_from_file_location(f"agent_{name}", str(path),
                                                      loader=SourceFileLoader(f"agent_{name}", str(path)))
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        _MODULES[name] = getattr(module, fn)
    fn = _MODULES[name]

    def policy(node):
        with contextlib.redirect_stdout(io.StringIO()):
            action = fn(ft.session_like_observation(node))
        return {"driver_a": action["driver_a"], "driver_b": action["driver_b"]}
    return policy


# Candidate filters of the agent policies, transcribed from their source (see report). True = the
# policy is able to propose a stop for this car in this state.
def can_propose_stop(name, car, status, laps_remaining, life):
    age, comp, used = car["tyre_age"], car["compound"], set(car.get("compounds_used", []))
    if name == "r0":
        if age < 4:
            return False
        if status != "GREEN":
            return (age >= {"SOFT": 5, "MEDIUM": 8, "HARD": 12}[comp] or len(used) < 2) and laps_remaining >= 6
        return (age >= life[comp] and laps_remaining > 3) or (comp == "SOFT" and age >= 9) or \
            (comp == "MEDIUM" and age >= 15 and laps_remaining <= 30) or \
            (comp == "HARD" and age >= 18 and laps_remaining >= 15 and len(used) >= 2)
    if name == "r1":
        return True
    if name == "r2":
        return not (status == "GREEN" and age < 5)
    if name == "r3":
        if status != "GREEN":
            return age >= 6 or (age >= 3 and len(used) < 2)
        return (comp == "SOFT" and age >= 9) or (comp == "MEDIUM" and age >= 15) or \
            (comp == "HARD" and age >= 21) or (laps_remaining <= 6 and len(used) < 2)
    return True


def scenario(spec, index):
    coeffs = coef.DEFAULT
    solver = ts.Solver(coeffs)
    state = new_championship_state(calendar=spec["calendar"], resource_inventory=initial_inventory(coeffs))
    for _ in range(index):
        state = ts.after_race(ts.prepare(state, solver.choose(state, "rival_rule"), coeffs), coeffs)
    option = solver.choose(state, "rival_rule")
    session = ChampionshipSession(state=state, base_seed=0, coeffs=coeffs)
    session.submit({"type": "COMPONENT_DECISION",
                    "decisions": [{"driver": d, "component": c, "action": a} for d, c, a in option]})
    race = ts._copy_race(session._active_race.race_state)
    race["config"] = ft.public_context(race["config"], session.observation())
    return race


def eval_paths(race, key, natural, event):
    n, model = len(race["events"]), race["config"]["neutralization"]
    paths = []
    for k in range(natural):
        paths.append(("natural", engine._continue_schedule(random.Random(f"b5-eval|natural|{key}|{k}"), [], n, model)))
    rng = random.Random(f"b5-eval|event|{key}")
    while sum(1 for kind, _ in paths if kind == "event") < event:
        path = engine._continue_schedule(rng, [], n, model)
        if any(s != "GREEN" for s in path):
            paths.append(("event", path))
    return paths


def policy_fn(name, path):
    if name in ep.FAIR_MODES or name in ep.DIAGNOSTIC_MODES:
        return lambda node: ep.plan_action(node, name, true_events=path)[0]
    if name == "baseline":
        return lambda node: ts.baseline_race_action(engine.observation(node))
    return gemini_fn(name)


POLICIES = list(ep.FAIR_MODES) + list(ep.DIAGNOSTIC_MODES) + ["baseline"] + list(GEMINI)
ANALYSED = ["green_only", "reactive", "prob_aware", "full_long", "baseline"] + list(GEMINI)


def play(race, path, name):
    node = ts._copy_race(race)
    node["events"] = list(path)
    fn = policy_fn(name, path)
    actions = []
    while node["step"] < len(node["events"]):
        action = fn(node)
        actions.append(f"{action['driver_a']}/{action['driver_b']}")
        engine.step(node, action)
    return ts.expected_apex_points_at_finish(node), actions


def replay_to(race, path, actions, step):
    node = ts._copy_race(race)
    node["events"] = list(path)
    for a in actions[:step]:
        x, y = a.split("/")
        engine.step(node, {"driver_a": x, "driver_b": y})
    return node


def as_action(key):
    a, b = key.split("/")
    return {"driver_a": a, "driver_b": b}


def flipped(node, status):
    """Same history, current status replaced (counterfactual observation for attribution only)."""
    copy_node = ts._copy_race(node)
    copy_node["events"] = list(node["events"])
    copy_node["events"][node["step"]] = status
    return copy_node


def decision_analysis(race, path, name, actions, rng):
    out = []
    life = {"SOFT": 10, "MEDIUM": 16, "HARD": 24}
    for step, action in enumerate(actions):
        status = path[step]
        after_event = step > 0 and any(s != "GREEN" for s in path[max(0, step - 2):step])
        if status == "GREEN" and not after_event and rng.random() > GREEN_SAMPLE:
            continue
        node = replay_to(race, path, actions, step)
        full_action = f"{'/'.join(ep.plan_action(node, 'full')[0].values())}"
        green_action = f"{'/'.join(ep.plan_action(node, 'green_only')[0].values())}"
        futures = ep.planner_futures(node, "full", EVAL_FUTURES, tag="evaluate")
        q = ep.q_values(node, futures, [as_action(k) for k in {action, full_action, green_action, "STAY/STAY"}])
        diff = [x - y for x, y in zip(q[full_action], q[action])]
        se = st.pstdev(diff) / math.sqrt(len(diff)) if len(diff) > 1 else 0.0
        loss = st.mean(diff)
        obs = engine.observation(node)
        row = {"policy": name, "decision": step + 1, "lap": obs["lap"], "status": status,
               "segments_so_far": engine.segments_so_far(node["events"], step), "after_event": after_event,
               "action": action, "full": full_action, "green_only": green_action,
               "loss_vs_full": loss, "se": se, "q": {k: st.mean(v) for k, v in q.items()},
               "full_differs_from_green": full_action != green_action}
        if name in GEMINI and loss > SIGNIFICANT and loss > 2 * se:
            row["category"] = classify(name, node, obs, action, full_action, green_action, status, life)
        out.append(row)
    return out


def classify(name, node, obs, action, full_action, green_action, status, life):
    drivers = obs["drivers"]
    full_a, act_a = full_action.split("/"), action.split("/")
    for idx, key in enumerate(("driver_a", "driver_b")):
        if full_a[idx] != "STAY" and act_a[idx] == "STAY" and \
                not can_propose_stop(name, drivers[key], status, obs["laps_remaining"], life):
            return "candidate_pruning"
    if status != "GREEN":
        if action == green_action and green_action != full_action and engine.segments_so_far(node["events"], node["step"]) >= 1:
            return "model_based:optimistic_event_end"
        as_green = "/".join(gemini_fn(name)(flipped(node, "GREEN")).values())
        if as_green == action:
            return "replanning:no_adaptation_to_event"
        return "replanning:over_or_mis_reaction"
    if green_action != full_action and action == green_action:
        return "model_based:no_anticipation"
    return "action_regret"


def job(args):
    spec, index, natural, event = args
    race = scenario(spec, index)
    key = f"{spec['id']}|{index}"
    rows, decisions = [], []
    rng = random.Random(f"b5-analysis|{key}")
    for p_index, (kind, path) in enumerate(eval_paths(race, key, natural, event)):
        played = {}
        for name in POLICIES:
            value, actions = play(race, path, name)
            played[name] = actions
            rows.append({"scenario": spec["id"], "race_index": index, "path": p_index, "kind": kind,
                         "events": "".join({"GREEN": ".", "SC": "S", "VSC": "V"}[s] for s in path),
                         "policy": name, "points": value, "actions": actions})
        for name in ANALYSED:
            for d in decision_analysis(race, path, name, played[name], rng):
                d.update({"scenario": spec["id"], "race_index": index, "path": p_index, "kind": kind})
                decisions.append(d)
    return {"rows": rows, "decisions": decisions}


def main():
    import scenarios as sc
    parser = argparse.ArgumentParser()
    parser.add_argument("--scenarios", type=int, default=24)
    parser.add_argument("--natural", type=int, default=3)
    parser.add_argument("--event", type=int, default=3)
    parser.add_argument("--workers", type=int, default=10)
    args = parser.parse_args()
    specs = sc.generate_specs(args.scenarios)
    started = time.time()
    with mp.Pool(args.workers) as pool:
        parts = pool.map(job, [(s, i, args.natural, args.event) for s in specs for i in RACE_INDICES], chunksize=1)
    out = {"futures_plan": ep.FUTURES, "futures_eval": EVAL_FUTURES, "green_sample": GREEN_SAMPLE,
           "rows": [r for p in parts for r in p["rows"]], "decisions": [d for p in parts for d in p["decisions"]],
           "wall_seconds": round(time.time() - started, 1)}
    (HERE / "results" / "b5_event_eval.json").write_text(json.dumps(out))
    print(f"wall {out['wall_seconds']}s rows {len(out['rows'])} decisions {len(out['decisions'])}")


if __name__ == "__main__":
    from _runtime import require_runtime_python
    require_runtime_python()
    main()
