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
LEGACY_ACTIONS = ("PIT", "STAY")
COMPOUND_ACTIONS = ("STAY", "PIT_SOFT", "PIT_MEDIUM", "PIT_HARD")
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


LEGACY_EVENT_PROBS = {"GREEN": 0.60, "VSC": 0.25, "SC": 0.15}


def _event_schedule(seed: int, count: int = len(DECISION_LAPS),
                    probs: dict[str, float] | None = None) -> list[str]:
    """Seeded per-decision track status; independent of every action (common random numbers)."""
    probs = probs or LEGACY_EVENT_PROBS
    green, vsc = probs["GREEN"], probs["GREEN"] + probs["VSC"]
    rng = random.Random(seed)
    schedule = []
    for _ in range(count):
        value = rng.random()
        schedule.append("GREEN" if value < green else "VSC" if value < vsc else "SC")
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
    scale = float(config.get("grid_gap_scale", 1.0))
    start_age = config.get("start_tyre_age")
    for slot, name in zip(GRID_ELAPSED_SLOTS, grid):
        by_name[name]["elapsed"] = GRID_ELAPSED_SLOTS[0] + (slot - GRID_ELAPSED_SLOTS[0]) * scale
        by_name[name]["base_pace"] = float(config["pace"][name])
        if start_age is not None:
            by_name[name]["tyre_age"] = int(start_age)
    decision_laps = list(config.get("decision_laps", DECISION_LAPS))
    event_probs = dict(config.get("event_probs") or LEGACY_EVENT_PROBS)
    events = (list(config["events"]) if config.get("events") is not None
              else _event_schedule(seed, len(decision_laps), event_probs))
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
        "segment_laps": int(config.get("segment_laps", SEGMENT_LENGTH)),
        "event_probs": event_probs,
        "tyres": config.get("tyres"),
        "pit": config.get("pit"),
    }
    if clean_config["tyres"] is not None:
        for car in cars:
            car["compounds_used"] = [car["compound"]]
    return {"seed": seed, "step": 0, "cars": [by_name[name] for name in grid], "events": events,
            "actions": [], "complete": False, "config": clean_config}


def _pit(state: dict[str, Any]) -> dict[str, Any] | None:
    return state["config"].get("pit") if "config" in state else None


def pit_loss(state: dict[str, Any], status: str) -> float:
    """Pit-lane time loss at this track under this status (legacy constants without a pit model)."""
    pit = _pit(state)
    return PIT_LOSS[status] if pit is None else pit["loss_sec"][status]


def _tyres(state: dict[str, Any]) -> dict[str, Any] | None:
    return state.get("config", {}).get("tyres") if "config" in state else None


def legal_actions(state: dict[str, Any]) -> list[str]:
    """Per-driver legal race actions for this race."""
    tyres = _tyres(state)
    if tyres is None:
        return list(LEGACY_ACTIONS)
    if not tyres["compound_choice"]:
        return ["STAY", "PIT_MEDIUM"]
    return list(COMPOUND_ACTIONS)


def pit_compound(choice: str) -> str | None:
    """Compound fitted by an action, or None for STAY. Legacy PIT fits MEDIUM."""
    if choice == "STAY":
        return None
    if choice == "PIT":
        return "MEDIUM"
    return choice[len("PIT_"):]


def segment_laps(state: dict[str, Any]) -> int:
    return state["config"]["segment_laps"] if "config" in state else SEGMENT_LENGTH


def event_probabilities(state: dict[str, Any]) -> dict[str, float]:
    """Published per-decision SC/VSC/GREEN probabilities for this race."""
    return dict(state["config"]["event_probs"]) if "config" in state else dict(LEGACY_EVENT_PROBS)


def laps_total(state: dict[str, Any]) -> int:
    return _decision_laps(state)[-1] + segment_laps(state)


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


def validate_action(action: Any, state: dict[str, Any] | None = None) -> dict[str, str]:
    if not isinstance(action, dict) or set(action) != {"driver_a", "driver_b"}:
        raise ValueError("action must contain exactly driver_a and driver_b")
    legal = legal_actions(state) if state is not None else list(LEGACY_ACTIONS)
    clean: dict[str, str] = {}
    for driver in ("driver_a", "driver_b"):
        choice = action[driver]
        if choice not in legal:
            raise ValueError(f"{driver} must be one of {'|'.join(legal)}")
        clean[driver] = choice
    return clean


def _classification(cars: list[dict[str, Any]]) -> list[dict[str, Any]]:
    ordered = sorted(cars, key=lambda car: (car["elapsed"], car["name"]))
    return [{"position": index + 1, "driver": car["name"], "team": car["team"],
             "elapsed": round(car["elapsed"], 3), "compound": car["compound"],
             "tyre_age": car["tyre_age"]}
            for index, car in enumerate(ordered)]


def _rival_action(car: dict[str, Any], status: str, step_index: int,
                  decision_count: int = len(DECISION_LAPS), tyres: dict[str, Any] | None = None,
                  laps_remaining: int | None = None) -> str:
    if tyres is None:
        if status == "SC" and car["tyre_age"] >= 7:
            return "PIT"
        if status == "VSC" and car["tyre_age"] >= 10:
            return "PIT"
        limits = {"SOFT": 10, "MEDIUM": 14, "HARD": 18}
        if car["tyre_age"] >= limits[car["compound"]] and step_index < decision_count - 1:
            return "PIT"
        return "STAY"
    life = tyres["compounds"][car["compound"]]["life_laps"]
    needs_second = tyres["two_compound_rule"] and len(set(car["compounds_used"])) < 2
    pit = ((status == "SC" and car["tyre_age"] >= 7) or (status == "VSC" and car["tyre_age"] >= 10)
           or (car["tyre_age"] >= life and step_index < decision_count - 1)
           or (needs_second and step_index == decision_count - 1))
    if not pit:
        return "STAY"
    return "PIT_" + rival_compound(car, laps_remaining, tyres)


def rival_compound(car: dict[str, Any], laps_remaining: int, tyres: dict[str, Any]) -> str:
    """Public rival compound rule (see track_a_coefficients.json: tyres.rival_compound_policy)."""
    if not tyres["compound_choice"]:
        return "MEDIUM"
    if laps_remaining <= tyres["rival_soft_max_laps"]:
        choice = "SOFT"
    elif laps_remaining <= tyres["rival_medium_max_laps"]:
        choice = "MEDIUM"
    else:
        choice = "HARD"
    if tyres["two_compound_rule"] and set(car["compounds_used"]) == {choice}:
        choice = {"SOFT": "MEDIUM", "HARD": "MEDIUM",
                  "MEDIUM": "SOFT" if laps_remaining <= 10 else "HARD"}[choice]
    return choice


def observation(state: dict[str, Any]) -> dict[str, Any]:
    if state["complete"]:
        return result(state)
    classification = _classification(state["cars"])
    positions = {entry["driver"]: entry["position"] for entry in classification}
    apex = {}
    tyres = _tyres(state)
    for key, name in (("driver_a", "Apex A"), ("driver_b", "Apex B")):
        car = next(car for car in state["cars"] if car["name"] == name)
        apex[key] = {"position": positions[name], "compound": car["compound"],
                     "tyre_age": car["tyre_age"], "elapsed": round(car["elapsed"], 3)}
        if tyres is not None:
            apex[key]["compounds_used"] = sorted(set(car["compounds_used"]))
    index = state["step"]
    laps = _decision_laps(state)
    out = {"race": "Harbor Grand Prix", "lap": laps[index], "laps_total": laps_total(state),
           "decision_index": index + 1, "decision_count": len(laps),
           "track_status": state["events"][index], "drivers": apex,
           "classification": classification, "legal_actions": legal_actions(state),
           "future_track_status": "hidden", "submitted_actions": len(state["actions"])}
    pit = _pit(state)
    if pit is not None:
        a, b = (next(c for c in state["cars"] if c["name"] == n) for n in ("Apex A", "Apex B"))
        first = "driver_a" if (a["elapsed"], a["name"]) <= (b["elapsed"], b["name"]) else "driver_b"
        out["pit"] = {"loss_sec": dict(pit["loss_sec"]), "double_stack_queue_sec": pit["double_stack_queue_sec"],
                      "out_lap_warmup_sec": dict(pit["out_lap_warmup_sec"]),
                      "if_both_pit_serviced_first": first}
    out["event_probabilities_per_decision"] = event_probabilities(state)
    out["segment_laps"] = segment_laps(state)
    if tyres is not None:
        out["tyre_life_laps"] = {name: spec["life_laps"] for name, spec in tyres["compounds"].items()}
        out["laps_remaining"] = laps_total(state) - laps[index]
        for entry in classification:
            car = next(c for c in state["cars"] if c["name"] == entry["driver"])
            entry["compounds_used"] = sorted(set(car["compounds_used"]))
    return out


def _segment_time(car: dict[str, Any], position: int, deg_multiplier: float = 1.0,
                  traffic: float | None = None, tyres: dict[str, Any] | None = None,
                  laps: int = SEGMENT_LENGTH) -> float:
    """Legacy traffic is positional; configured races pass a gap-based dirty-air loss.

    With a B1 tyre model, laps beyond a compound's life add a cliff term that grows
    linearly with every extra lap (scaled by the track degradation multiplier)."""
    tyre = (tyres["compounds"] if tyres is not None else COMPOUNDS)[car["compound"]]
    if traffic is None:
        traffic = min(0.70, 0.10 * (position - 1))
    degradation = tyre["degradation"] * deg_multiplier
    cliff = tyres["cliff_sec_per_lap_per_lap"] * deg_multiplier if tyres is not None else 0.0
    life = tyre.get("life_laps", 10**6)
    return sum(car["base_pace"] + tyre["offset"] + degradation * (car["tyre_age"] + offset)
               + cliff * max(0, car["tyre_age"] + offset - life) + traffic
               for offset in range(laps))


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
    clean = validate_action(action, state)
    status, index = state["events"][state["step"]], state["step"]
    config = state.get("config")
    tyres = _tyres(state)
    decision_count = len(_decision_laps(state))
    remaining = laps_total(state) - _decision_laps(state)[index]
    apex_actions = {"Apex A": clean["driver_a"], "Apex B": clean["driver_b"]}
    pit_actions = {car["name"]: (apex_actions[car["name"]] if car["team"] == "Apex"
                                 else _rival_action(car, status, index, decision_count, tyres, remaining))
                   for car in state["cars"]}
    pit = _pit(state)
    pitting = [car for car in sorted(state["cars"], key=lambda c: (c["elapsed"], c["name"]))
               if pit_compound(pit_actions[car["name"]]) is not None]
    if pit is not None:
        # Shared crew: the second car of a team to arrive (road order) waits for the first.
        seen_teams = set()
        for car in pitting:
            if car["team"] in seen_teams:
                car["elapsed"] += pit["double_stack_queue_sec"]
            seen_teams.add(car["team"])
    for car in pitting:
        compound = pit_compound(pit_actions[car["name"]])
        car["elapsed"] += pit_loss(state, status)
        car["compound"], car["tyre_age"] = compound, 0
        if tyres is not None:
            car["compounds_used"].append(compound)
        if pit is not None:
            car["out_lap"] = True
    if pit is None and pit_compound(clean["driver_a"]) and pit_compound(clean["driver_b"]):
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
    warmup = pit["out_lap_warmup_sec"] if pit is not None else {}
    seg = segment_laps(state)
    finish = {car["name"]: car["elapsed"] + _segment_time(car, positions[car["name"]], deg, traffic[car["name"]], tyres, seg)
              + (warmup.get(car["compound"], 0.0) if car.pop("out_lap", False) else 0.0)
              for car in state["cars"]}
    if config and config["overtaking"] is not None:
        _apply_overtaking(order, finish, config["overtaking"], config["overtaking_difficulty"])
    for car in state["cars"]:
        car["elapsed"] = finish[car["name"]]
        car["tyre_age"] += seg
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
    tyres = _tyres(state)
    penalty = {car["name"]: finish_penalty(state, car) for car in state["cars"]}
    running = [car for car in state["cars"] if car["name"] not in retired]
    out = [car for car in state["cars"] if car["name"] in retired]
    ordered = (sorted(running, key=lambda car: (car["elapsed"] + penalty[car["name"]], car["name"]))
               + sorted(out, key=lambda car: car["name"]))
    classification = []
    for index, car in enumerate(ordered):
        finished = car["name"] not in retired
        entry = {
            "position": index + 1, "driver": car["name"], "team": car["team"],
            "elapsed": round(car["elapsed"] + penalty[car["name"]], 3), "compound": car["compound"],
            "tyre_age": car["tyre_age"], "status": "FINISHED" if finished else "DNF",
            "points": POINTS[index] if finished else 0,
        }
        if tyres is not None:
            entry["compounds_used"] = sorted(set(car["compounds_used"]))
            entry["penalty_sec"] = penalty[car["name"]]
        classification.append(entry)
    return {"complete": True, "seed": state["seed"], "actions": state["actions"],
            "event_history": state["events"], "classification": classification,
            "constructors_points": sum(e["points"] for e in classification if e["team"] == "Apex")}


def finish_penalty(state: dict[str, Any], car: dict[str, Any]) -> float:
    """Time penalty added at the finish (two-compound rule, B1)."""
    tyres = _tyres(state)
    if tyres is not None and tyres["two_compound_rule"] and len(set(car["compounds_used"])) < 2:
        return tyres["two_compound_penalty_sec"]
    return 0.0


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
