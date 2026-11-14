"""Sequential two-car race strategy simulator with seeded SC/VSC events."""

from __future__ import annotations

import copy
import random
from itertools import product
from typing import Any

SEED = 20261114
DECISION_LAPS = (8, 12, 16)
SEGMENT_LENGTH = 4
POINTS = (25, 18, 15, 12, 10, 8, 6, 4)
PIT_LOSS = {"GREEN": 18.0, "VSC": 10.0, "SC": 5.0}
DOUBLE_STACK_DELAY = 6.0
COMPOUNDS = {
    "SOFT": {"offset": -0.55, "degradation": 0.35},
    "MEDIUM": {"offset": 0.00, "degradation": 0.14},
    "HARD": {"offset": 0.28, "degradation": 0.055},
}
RULES = {
    "objective": "maximize Apex A plus Apex B constructors points",
    "decision_laps": list(DECISION_LAPS),
    "segment_length_laps": SEGMENT_LENGTH,
    "legal_actions": ["PIT", "STAY"],
    "pit_effect": "PIT changes to a new MEDIUM tyre before the next segment",
    "pit_loss_seconds": PIT_LOSS,
    "double_stack": {"condition": "both Apex drivers PIT at the same decision",
                     "second_car": "driver_b", "extra_seconds": DOUBLE_STACK_DELAY},
    "tyre_model": COMPOUNDS,
    "traffic_penalty": "0.10 seconds/lap per position behind P1, capped at 0.70",
    "event_generation": {"seeded": True,
                         "probabilities_each_decision": {"GREEN": 0.60, "VSC": 0.25, "SC": 0.15},
                         "future_events_hidden": True},
    "points_by_position": list(POINTS),
    "rivals": "six deterministic cars using the same tyre and pit-loss mechanics",
}


def _car(name: str, team: str, elapsed: float, base_pace: float,
         compound: str, tyre_age: int) -> dict[str, Any]:
    return {"name": name, "team": team, "elapsed": elapsed, "base_pace": base_pace,
            "compound": compound, "tyre_age": tyre_age}


def _event_schedule(seed: int) -> list[str]:
    rng = random.Random(seed)
    schedule = []
    for _ in DECISION_LAPS:
        value = rng.random()
        schedule.append("GREEN" if value < 0.60 else "VSC" if value < 0.85 else "SC")
    return schedule


def new_state(seed: int = SEED) -> dict[str, Any]:
    cars = [
        _car("Rival 1", "Orion", 720.0, 89.55, "MEDIUM", 8),
        _car("Apex A", "Apex", 721.8, 89.65, "SOFT", 8),
        _car("Rival 2", "Nova", 723.0, 89.75, "SOFT", 8),
        _car("Apex B", "Apex", 724.0, 89.85, "MEDIUM", 8),
        _car("Rival 3", "Orion", 725.2, 89.90, "HARD", 5),
        _car("Rival 4", "Nova", 727.0, 90.00, "MEDIUM", 7),
        _car("Rival 5", "Vertex", 729.0, 90.05, "HARD", 3),
        _car("Rival 6", "Vertex", 731.0, 90.15, "MEDIUM", 6),
    ]
    return {"seed": seed, "step": 0, "cars": cars, "events": _event_schedule(seed),
            "actions": [], "complete": False}


def validate_action(action: Any) -> dict[str, str]:
    if not isinstance(action, dict) or set(action) != {"driver_a", "driver_b"}:
        raise ValueError("action must contain exactly driver_a and driver_b")
    clean: dict[str, str] = {}
    for driver in ("driver_a", "driver_b"):
        choice = action[driver]
        if choice not in ("PIT", "STAY"):
            raise ValueError(f"{driver} must be PIT or STAY")
        clean[driver] = choice
    return clean


def _classification(cars: list[dict[str, Any]]) -> list[dict[str, Any]]:
    ordered = sorted(cars, key=lambda car: (car["elapsed"], car["name"]))
    return [{"position": index + 1, "driver": car["name"], "team": car["team"],
             "elapsed": round(car["elapsed"], 3), "compound": car["compound"],
             "tyre_age": car["tyre_age"]}
            for index, car in enumerate(ordered)]


def _rival_action(car: dict[str, Any], status: str, step_index: int) -> str:
    if status == "SC" and car["tyre_age"] >= 7:
        return "PIT"
    if status == "VSC" and car["tyre_age"] >= 10:
        return "PIT"
    limits = {"SOFT": 10, "MEDIUM": 14, "HARD": 18}
    if car["tyre_age"] >= limits[car["compound"]] and step_index < 2:
        return "PIT"
    return "STAY"


def observation(state: dict[str, Any]) -> dict[str, Any]:
    if state["complete"]:
        return result(state)
    classification = _classification(state["cars"])
    positions = {entry["driver"]: entry["position"] for entry in classification}
    apex = {}
    for key, name in (("driver_a", "Apex A"), ("driver_b", "Apex B")):
        car = next(car for car in state["cars"] if car["name"] == name)
        apex[key] = {"position": positions[name], "compound": car["compound"],
                     "tyre_age": car["tyre_age"], "elapsed": round(car["elapsed"], 3)}
    index = state["step"]
    return {"race": "Harbor Grand Prix", "lap": DECISION_LAPS[index], "laps_total": 20,
            "decision_index": index + 1, "decision_count": len(DECISION_LAPS),
            "track_status": state["events"][index], "drivers": apex,
            "classification": classification, "legal_actions": ["PIT", "STAY"],
            "future_track_status": "hidden", "submitted_actions": len(state["actions"])}


def _segment_time(car: dict[str, Any], position: int) -> float:
    tyre = COMPOUNDS[car["compound"]]
    traffic = min(0.70, 0.10 * (position - 1))
    return sum(car["base_pace"] + tyre["offset"] + tyre["degradation"] * (car["tyre_age"] + offset)
               + traffic for offset in range(SEGMENT_LENGTH))


def step(state: dict[str, Any], action: Any) -> dict[str, Any]:
    if state["complete"]:
        raise ValueError("race is already complete")
    clean = validate_action(action)
    status, index = state["events"][state["step"]], state["step"]
    apex_actions = {"Apex A": clean["driver_a"], "Apex B": clean["driver_b"]}
    pit_actions = {car["name"]: (apex_actions[car["name"]] if car["team"] == "Apex"
                                 else _rival_action(car, status, index)) for car in state["cars"]}
    for car in state["cars"]:
        if pit_actions[car["name"]] == "PIT":
            car["elapsed"] += PIT_LOSS[status]
            car["compound"], car["tyre_age"] = "MEDIUM", 0
    if clean["driver_a"] == clean["driver_b"] == "PIT":
        next(car for car in state["cars"] if car["name"] == "Apex B")["elapsed"] += DOUBLE_STACK_DELAY
    positions = {entry["driver"]: entry["position"] for entry in _classification(state["cars"])}
    for car in state["cars"]:
        car["elapsed"] += _segment_time(car, positions[car["name"]])
        car["tyre_age"] += SEGMENT_LENGTH
    state["actions"].append(clean)
    state["step"] += 1
    state["complete"] = state["step"] == len(DECISION_LAPS)
    return state


def result(state: dict[str, Any]) -> dict[str, Any]:
    if not state["complete"]:
        raise ValueError("race is incomplete")
    classification = _classification(state["cars"])
    constructors_points = sum(POINTS[entry["position"] - 1]
                               for entry in classification if entry["team"] == "Apex")
    return {"complete": True, "seed": state["seed"], "actions": state["actions"],
            "event_history": state["events"], "classification": classification,
            "constructors_points": constructors_points}


def run_episode(actions: Any, seed: int = SEED) -> dict[str, Any]:
    if not isinstance(actions, list) or len(actions) != len(DECISION_LAPS):
        raise ValueError(f"exactly {len(DECISION_LAPS)} actions are required")
    state = new_state(seed)
    for action in actions:
        step(state, action)
    return result(state)


def enumerate_strategies(seed: int = SEED) -> list[dict[str, Any]]:
    pairs = [{"driver_a": a, "driver_b": b}
             for a, b in product(("PIT", "STAY"), repeat=2)]
    outcomes = []
    for sequence in product(pairs, repeat=len(DECISION_LAPS)):
        actions = [copy.deepcopy(action) for action in sequence]
        outcomes.append({"actions": actions, "result": run_episode(actions, seed)})
    return outcomes
