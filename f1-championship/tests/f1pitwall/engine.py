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


def _event_schedule(seed: int, count: int = len(DECISION_LAPS)) -> list[str]:
    """Seeded per-decision track status; independent of every action (common random numbers)."""
    rng = random.Random(seed)
    schedule = []
    for _ in range(count):
        value = rng.random()
        schedule.append("GREEN" if value < 0.60 else "VSC" if value < 0.85 else "SC")
    return schedule


GRID_ELAPSED_SLOTS = (720.0, 721.8, 723.0, 724.0, 725.2, 727.0, 729.0, 731.0)


def dnf_uniforms(seed: int) -> dict[str, float]:
    """One action-independent uniform draw per car per race (common random numbers)."""
    rng = random.Random(f"dnf:{seed}")
    return {name: rng.random() for name in sorted(LEGACY_CAR_NAMES)}


def new_state(seed: int = SEED, config: dict[str, Any] | None = None) -> dict[str, Any]:
    """Legacy race when config is None; otherwise a Track A configured race.

    config keys: grid (car names P1..P8), pace {car: base s/lap}, deg_multiplier,
    overtaking (model dict or None), dnf_prob {car: p}, decision_laps (optional),
    events (optional explicit schedule, planners/oracles only - never set by the
    championship session).
    """
    cars = _legacy_cars()
    if config is None:
        return {"seed": seed, "step": 0, "cars": cars, "events": _event_schedule(seed),
                "actions": [], "complete": False}
    by_name = {car["name"]: car for car in cars}
    grid = list(config["grid"])
    if sorted(grid) != sorted(by_name):
        raise ValueError("grid must be a permutation of the eight cars")
    for slot, name in zip(GRID_ELAPSED_SLOTS, grid):
        by_name[name]["elapsed"] = slot
        by_name[name]["base_pace"] = float(config["pace"][name])
    decision_laps = list(config.get("decision_laps", DECISION_LAPS))
    events = list(config["events"]) if config.get("events") is not None else _event_schedule(seed, len(decision_laps))
    if len(events) != len(decision_laps) or any(e not in PIT_LOSS for e in events):
        raise ValueError("invalid event schedule")
    clean_config = {
        "grid": grid,
        "pace": {name: float(config["pace"][name]) for name in by_name},
        "deg_multiplier": float(config.get("deg_multiplier", 1.0)),
        "overtaking": config.get("overtaking"),
        "overtaking_difficulty": float(config.get("overtaking_difficulty", 0.0)),
        "dnf_prob": {name: float(config.get("dnf_prob", {}).get(name, 0.0)) for name in by_name},
        "decision_laps": decision_laps,
    }
    return {"seed": seed, "step": 0, "cars": [by_name[name] for name in grid], "events": events,
            "actions": [], "complete": False, "config": clean_config}


def _decision_laps(state: dict[str, Any]) -> list[int]:
    return list(state["config"]["decision_laps"]) if "config" in state else list(DECISION_LAPS)


def _legacy_cars() -> list[dict[str, Any]]:
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


LEGACY_CAR_NAMES = ("Rival 1", "Apex A", "Rival 2", "Apex B", "Rival 3", "Rival 4", "Rival 5", "Rival 6")
LEGACY_BASE_PACE = {car["name"]: car["base_pace"] for car in _legacy_cars()}


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


def _rival_action(car: dict[str, Any], status: str, step_index: int,
                  decision_count: int = len(DECISION_LAPS)) -> str:
    if status == "SC" and car["tyre_age"] >= 7:
        return "PIT"
    if status == "VSC" and car["tyre_age"] >= 10:
        return "PIT"
    limits = {"SOFT": 10, "MEDIUM": 14, "HARD": 18}
    if car["tyre_age"] >= limits[car["compound"]] and step_index < decision_count - 1:
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
    laps = _decision_laps(state)
    return {"race": "Harbor Grand Prix", "lap": laps[index], "laps_total": laps[-1] + SEGMENT_LENGTH,
            "decision_index": index + 1, "decision_count": len(laps),
            "track_status": state["events"][index], "drivers": apex,
            "classification": classification, "legal_actions": ["PIT", "STAY"],
            "future_track_status": "hidden", "submitted_actions": len(state["actions"])}


def _segment_time(car: dict[str, Any], position: int, deg_multiplier: float = 1.0,
                  traffic: float | None = None) -> float:
    """Legacy traffic is positional; configured races pass a gap-based dirty-air loss."""
    tyre = COMPOUNDS[car["compound"]]
    if traffic is None:
        traffic = min(0.70, 0.10 * (position - 1))
    degradation = tyre["degradation"] * deg_multiplier
    return sum(car["base_pace"] + tyre["offset"] + degradation * (car["tyre_age"] + offset)
               + traffic for offset in range(SEGMENT_LENGTH))


def _apply_overtaking(order: list[dict[str, Any]], finish: dict[str, float],
                      model: dict[str, float], difficulty: float) -> None:
    """Hold a following car behind unless its pass margin beats the track's threshold."""
    required = model["pass_base_sec"] + difficulty * model["pass_scale_sec"]
    for index in range(1, len(order)):
        ahead, car = order[index - 1]["name"], order[index]["name"]
        if finish[car] < finish[ahead] + model["min_gap_sec"]:
            if finish[ahead] - finish[car] < required:
                finish[car] = finish[ahead] + model["min_gap_sec"]


def step(state: dict[str, Any], action: Any) -> dict[str, Any]:
    if state["complete"]:
        raise ValueError("race is already complete")
    clean = validate_action(action)
    status, index = state["events"][state["step"]], state["step"]
    config = state.get("config")
    decision_count = len(_decision_laps(state))
    apex_actions = {"Apex A": clean["driver_a"], "Apex B": clean["driver_b"]}
    pit_actions = {car["name"]: (apex_actions[car["name"]] if car["team"] == "Apex"
                                 else _rival_action(car, status, index, decision_count))
                   for car in state["cars"]}
    for car in state["cars"]:
        if pit_actions[car["name"]] == "PIT":
            car["elapsed"] += PIT_LOSS[status]
            car["compound"], car["tyre_age"] = "MEDIUM", 0
    if clean["driver_a"] == clean["driver_b"] == "PIT":
        next(car for car in state["cars"] if car["name"] == "Apex B")["elapsed"] += DOUBLE_STACK_DELAY
    order = sorted(state["cars"], key=lambda car: (car["elapsed"], car["name"]))
    positions = {car["name"]: index + 1 for index, car in enumerate(order)}
    deg = config["deg_multiplier"] if config else 1.0
    model = config["overtaking"] if config else None
    traffic = {car["name"]: None for car in state["cars"]}
    if model is not None:
        for index, car in enumerate(order):
            close = index > 0 and car["elapsed"] - order[index - 1]["elapsed"] < model["dirty_air_gap_sec"]
            traffic[car["name"]] = model["dirty_air_loss_sec_per_lap"] if close else 0.0
    finish = {car["name"]: car["elapsed"] + _segment_time(car, positions[car["name"]], deg, traffic[car["name"]])
              for car in state["cars"]}
    if config and config["overtaking"] is not None:
        _apply_overtaking(order, finish, config["overtaking"], config["overtaking_difficulty"])
    for car in state["cars"]:
        car["elapsed"] = finish[car["name"]]
        car["tyre_age"] += SEGMENT_LENGTH
    state["actions"].append(clean)
    state["step"] += 1
    state["complete"] = state["step"] == decision_count
    return state


def result(state: dict[str, Any]) -> dict[str, Any]:
    if not state["complete"]:
        raise ValueError("race is incomplete")
    if "config" not in state:
        classification = _classification(state["cars"])
        constructors_points = sum(POINTS[entry["position"] - 1]
                                   for entry in classification if entry["team"] == "Apex")
        return {"complete": True, "seed": state["seed"], "actions": state["actions"],
                "event_history": state["events"], "classification": classification,
                "constructors_points": constructors_points}
    draws = dnf_uniforms(state["seed"])
    retired = {name for name, p in state["config"]["dnf_prob"].items() if draws[name] < p}
    running = [car for car in state["cars"] if car["name"] not in retired]
    out = [car for car in state["cars"] if car["name"] in retired]
    ordered = (sorted(running, key=lambda car: (car["elapsed"], car["name"]))
               + sorted(out, key=lambda car: car["name"]))
    classification = []
    for index, car in enumerate(ordered):
        finished = car["name"] not in retired
        classification.append({
            "position": index + 1, "driver": car["name"], "team": car["team"],
            "elapsed": round(car["elapsed"], 3), "compound": car["compound"],
            "tyre_age": car["tyre_age"], "status": "FINISHED" if finished else "DNF",
            "points": POINTS[index] if finished else 0,
        })
    return {"complete": True, "seed": state["seed"], "actions": state["actions"],
            "event_history": state["events"], "classification": classification,
            "constructors_points": sum(e["points"] for e in classification if e["team"] == "Apex")}


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
