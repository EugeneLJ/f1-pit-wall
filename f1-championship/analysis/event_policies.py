"""B5-P1: in-race planners that differ ONLY in how they model future SC/VSC events.

Every planner uses the same action space (16 joint PIT/STAY/compound actions), the same public
baseline continuation, the same exact engine for rollouts, the same sample budget (FUTURES per
decision; deterministic modes need 1), and observes only events up to the current decision.

  green_only   future segments all GREEN; a current SC/VSC ends after this segment (r2's assumption)
  reactive     no new events; a current SC/VSC continues per the published duration law
  prob_aware   new events per the published start probabilities, but every event lasts 1 segment
               and a current one ends now (start model, no duration model)
  full         published start probabilities + duration law + conditioning on the current state
  full_long    diagnostic: as full, but every event (incl. the current one) lasts its maximum
  clairvoyant  diagnostic hindsight bound: rollouts use the TRUE remaining path (not fair)

Model access: these planners roll out the authoritative engine (the published rules executed
exactly). Agent-written policies had to build their own approximate model from the rules.
"""

from __future__ import annotations

import copy
import random
from typing import Any, Dict, List, Optional

import track_a_solver as ts
from f1pitwall import engine

FUTURES = 24
FAIR_MODES = ("green_only", "reactive", "prob_aware", "full")
DIAGNOSTIC_MODES = ("full_long", "clairvoyant")
MODE_FLAGS = {  # anticipate new events, persist current event, duration law
    "green_only": (False, False, "short"),
    "reactive": (False, True, "public"),
    "prob_aware": (True, False, "short"),
    "full": (True, True, "public"),
    "full_long": (True, True, "long"),
}


def _durations(model, law):
    if law == "public":
        return model["duration"]
    if law == "short":
        return {k: {1: 1.0} for k in model["duration"]}
    return {k: {max(v): 1.0} for k, v in model["duration"].items()}


def generate(rng: random.Random, history: List[str], n: int, model: Dict[str, Any], mode: str) -> List[str]:
    """Statuses for decisions len(history)..n-1 given the observed history, under `mode`'s assumptions."""
    anticipate, persist, law = MODE_FLAGS[mode]
    durations = _durations(model, law)
    out = list(history)
    remaining, cooldown, current = 0, 0, None
    if out and out[-1] != "GREEN":
        current = out[-1]
        elapsed = engine.segments_so_far(out, len(out) - 1)
        if persist:
            tail = {d: p for d, p in durations[current].items() if d >= elapsed}
            total = sum(tail.values())
            if total > 0:
                u, acc, duration = rng.random(), 0.0, max(tail)
                for d in sorted(tail):
                    acc += tail[d] / total
                    if u < acc:
                        duration = d
                        break
                remaining = duration - elapsed
        if remaining == 0:
            cooldown = model["cooldown"]
    elif out:
        last = max((i for i, e in enumerate(out) if e != "GREEN"), default=None)
        if last is not None:
            cooldown = max(0, model["cooldown"] - (len(out) - 1 - last))
    start = model["start"] if anticipate else {"SC": 0.0, "VSC": 0.0}
    while len(out) < n:
        if remaining > 0:
            out.append(current)
            remaining -= 1
            if remaining == 0:
                cooldown = model["cooldown"]
            continue
        if cooldown > 0:
            out.append("GREEN")
            cooldown -= 1
            continue
        u = rng.random()
        if u < start["SC"]:
            current = "SC"
        elif u < start["SC"] + start["VSC"]:
            current = "VSC"
        else:
            out.append("GREEN")
            continue
        u, acc, duration = rng.random(), 0.0, max(durations[current])
        for d in sorted(durations[current]):
            acc += durations[current][d]
            if u < acc:
                duration = d
                break
        out.append(current)
        remaining = duration - 1
        if remaining == 0:
            cooldown = model["cooldown"]
    return out[len(history):]


def planner_futures(node: Dict[str, Any], mode: str, samples: int = FUTURES, tag: str = "plan",
                    true_events: Optional[List[str]] = None) -> List[List[str]]:
    step, n = node["step"], len(node["events"])
    if mode == "clairvoyant":
        return [list(true_events[step + 1:])]
    history = node["events"][:step + 1]  # observed so far, including the current status
    model = node["config"]["neutralization"]
    rng = random.Random(f"{tag}|{mode}|{n}|{step}|{history}")
    deterministic = not MODE_FLAGS[mode][0] and (not MODE_FLAGS[mode][1] or history[-1] == "GREEN")
    count = 1 if deterministic or mode == "green_only" else samples
    return [generate(rng, history, n, model, mode) for _ in range(count)]


def joint_actions(node) -> List[Dict[str, str]]:
    legal = engine.legal_actions(node)
    return [{"driver_a": a, "driver_b": b} for a in legal for b in legal]


def q_values(node, futures, actions=None, continuation=None) -> Dict[str, List[float]]:
    """Per-action list of finishing expected Apex points, one per future (common futures)."""
    continuation = continuation or (lambda child: ts.baseline_race_action(engine.observation(child)))
    out = {}
    for action in actions or joint_actions(node):
        key = f"{action['driver_a']}/{action['driver_b']}"
        vals = []
        for future in futures:
            child = ts._copy_race(node)
            engine.step(child, action)
            child["events"][child["step"]:] = future
            while child["step"] < len(child["events"]):
                engine.step(child, continuation(child))
            vals.append(ts.expected_apex_points_at_finish(child))
        out[key] = vals
    return out


def plan_action(node, mode, true_events=None, samples=FUTURES):
    futures = planner_futures(node, mode, samples, true_events=true_events)
    q = q_values(node, futures)
    best = max(q, key=lambda k: sum(q[k]) / len(q[k]))  # first max in legal order (STAY first)
    a, b = best.split("/")
    return {"driver_a": a, "driver_b": b}, len(futures)
