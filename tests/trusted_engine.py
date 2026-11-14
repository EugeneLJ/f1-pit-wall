"""Verifier-owned replay engine; never imported from the agent image."""

from __future__ import annotations

import random
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


def _car(name: str, team: str, elapsed: float, base_pace: float,
         compound: str, tyre_age: int) -> dict[str, Any]:
    return {"name": name, "team": team, "elapsed": elapsed, "base_pace": base_pace,
            "compound": compound, "tyre_age": tyre_age}


def _events(seed: int) -> list[str]:
    rng = random.Random(seed)
    schedule = []
    for _ in DECISION_LAPS:
        value = rng.random()
        schedule.append("GREEN" if value < 0.60 else "VSC" if value < 0.85 else "SC")
    return schedule


def _initial_cars() -> list[dict[str, Any]]:
    return [
        _car("Rival 1", "Orion", 720.0, 89.55, "MEDIUM", 8),
        _car("Apex A", "Apex", 721.8, 89.65, "SOFT", 8),
        _car("Rival 2", "Nova", 723.0, 89.75, "SOFT", 8),
        _car("Apex B", "Apex", 724.0, 89.85, "MEDIUM", 8),
        _car("Rival 3", "Orion", 725.2, 89.90, "HARD", 5),
        _car("Rival 4", "Nova", 727.0, 90.00, "MEDIUM", 7),
        _car("Rival 5", "Vertex", 729.0, 90.05, "HARD", 3),
        _car("Rival 6", "Vertex", 731.0, 90.15, "MEDIUM", 6),
    ]


def parse_submission(value: Any) -> list[dict[str, str]]:
    if not isinstance(value, dict) or set(value) != {"version", "actions"} or value["version"] != 2:
        raise ValueError("submission must contain only version=2 and actions")
    actions = value["actions"]
    if not isinstance(actions, list) or len(actions) != len(DECISION_LAPS):
        raise ValueError("race is incomplete")
    clean = []
    for action in actions:
        if not isinstance(action, dict) or set(action) != {"driver_a", "driver_b"}:
            raise ValueError("each action must contain exactly both drivers")
        if action["driver_a"] not in ("PIT", "STAY") or action["driver_b"] not in ("PIT", "STAY"):
            raise ValueError("invalid PIT/STAY action")
        clean.append(dict(action))
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
    return "PIT" if car["tyre_age"] >= limits[car["compound"]] and step_index < 2 else "STAY"


def _segment_time(car: dict[str, Any], position: int) -> float:
    tyre = COMPOUNDS[car["compound"]]
    traffic = min(0.70, 0.10 * (position - 1))
    return sum(car["base_pace"] + tyre["offset"] + tyre["degradation"] * (car["tyre_age"] + offset)
               + traffic for offset in range(SEGMENT_LENGTH))


def replay(actions: list[dict[str, str]], seed: int = SEED) -> dict[str, Any]:
    cars, events = _initial_cars(), _events(seed)
    for index, clean in enumerate(actions):
        status = events[index]
        apex_actions = {"Apex A": clean["driver_a"], "Apex B": clean["driver_b"]}
        pit_actions = {car["name"]: (apex_actions[car["name"]] if car["team"] == "Apex"
                                     else _rival_action(car, status, index)) for car in cars}
        for car in cars:
            if pit_actions[car["name"]] == "PIT":
                car["elapsed"] += PIT_LOSS[status]
                car["compound"], car["tyre_age"] = "MEDIUM", 0
        if clean["driver_a"] == clean["driver_b"] == "PIT":
            next(car for car in cars if car["name"] == "Apex B")["elapsed"] += DOUBLE_STACK_DELAY
        positions = {entry["driver"]: entry["position"] for entry in _classification(cars)}
        for car in cars:
            car["elapsed"] += _segment_time(car, positions[car["name"]])
            car["tyre_age"] += SEGMENT_LENGTH
    classification = _classification(cars)
    points = sum(POINTS[item["position"] - 1] for item in classification if item["team"] == "Apex")
    return {"seed": seed, "events": events, "classification": classification,
            "constructors_points": points}
