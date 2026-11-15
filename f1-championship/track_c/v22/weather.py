"""Isolated opt-in M7 weather, forecasts, wet compounds, and reduced micro-race.

This is not an authoritative 2.1.0 engine patch. It exists to freeze mechanics and
replay evidence before the engine owner integrates them behind a new version flag.
"""

from __future__ import annotations

import copy
import json
import math
from pathlib import Path
import random
from typing import Any

from .common import categorical, finite, reject_public_secrets, uniform, validate_seed

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "v22_m7.json"
DRY_COMPOUNDS = ("SOFT", "MEDIUM", "HARD")
WET_COMPOUNDS = ("INTERMEDIATE", "WET")
COMPOUNDS = DRY_COMPOUNDS + WET_COMPOUNDS
ACTIONS = ("STAY",) + tuple(f"PIT_{compound}" for compound in COMPOUNDS)


def load_model() -> dict[str, Any]:
    model = json.loads(FIXTURE.read_text(encoding="utf-8"))
    if model.get("schema_version") != 1 or model.get("data_status") != "synthetic_only" or model["sources"]:
        raise ValueError("M7 requires an unsourced synthetic fixture")
    rain = model["rain"]
    states = rain["states"]
    if states != ["DRY", "DAMP", "WET"]:
        raise ValueError("M7 rain-state order is not stable")
    for state in states:
        row = rain["transition"][state]
        if len(row) != len(states) or any(value <= 0 for value in row) or not math.isclose(sum(row), 1.0):
            raise ValueError("M7 Markov transition row is invalid")
    for compound in COMPOUNDS:
        spec = model["compounds"][compound]
        for name in ("offset_sec_at_wetness", "deg_per_lap_at_wetness"):
            if set(spec[name]) != {"0.0", "0.4", "0.7", "1.0", "provenance"}:
                raise ValueError("M7 compound interpolation nodes are incomplete")
        for metric in ("retire_probability_at_wetness", "spin_probability_at_wetness"):
            for wetness in ("0.0", "0.4", "0.7", "1.0"):
                p_ret = spec["retire_probability_at_wetness"][wetness]
                p_spin = spec["spin_probability_at_wetness"][wetness]
                if not 0 <= p_ret <= 1 or not 0 <= p_spin <= 1 or p_ret + p_spin > 1:
                    raise ValueError("M7 incident probabilities are invalid")
    return copy.deepcopy(model)


def _interp(table: dict[str, Any], wetness: float) -> float:
    wetness = finite(wetness, minimum=0.0, maximum=1.0)
    points = sorted((float(key), value) for key, value in table.items() if key != "provenance")
    for (left_x, left), (right_x, right) in zip(points, points[1:]):
        if left_x <= wetness <= right_x:
            fraction = (wetness - left_x) / (right_x - left_x)
            return left + fraction * (right - left)
    raise ValueError("wetness is outside interpolation nodes")


def tyre_offset(compound: str, wetness: float, model: dict[str, Any] | None = None) -> float:
    model = model or load_model()
    _validate_compound(compound, model)
    return _interp(model["compounds"][compound]["offset_sec_at_wetness"], wetness)


def tyre_degradation(compound: str, wetness: float, model: dict[str, Any] | None = None) -> float:
    model = model or load_model()
    _validate_compound(compound, model)
    return _interp(model["compounds"][compound]["deg_per_lap_at_wetness"], wetness)


def incident_probabilities(compound: str, wetness: float,
                           model: dict[str, Any] | None = None) -> tuple[float, float]:
    model = model or load_model()
    _validate_compound(compound, model)
    spec = model["compounds"][compound]
    return (_interp(spec["retire_probability_at_wetness"], wetness),
            _interp(spec["spin_probability_at_wetness"], wetness))


def _validate_compound(compound: str, model: dict[str, Any]) -> None:
    if compound not in COMPOUNDS or compound not in model["compounds"]:
        raise ValueError(f"unknown compound: {compound}")


def legal_actions(wetness: float | None = None) -> tuple[str, ...]:
    """Weather must not hide action legality; only outcomes differ by condition."""
    if wetness is not None:
        finite(wetness, minimum=0.0, maximum=1.0)
    return ACTIONS


def _classify_weather(wetness: float) -> str:
    if wetness >= 0.62:
        return "WET"
    if wetness >= 0.24:
        return "DAMP"
    return "DRY"


def weather_schedule(race_seed: int, race_id: str, segments: int = 8,
                     model: dict[str, Any] | None = None) -> dict[str, Any]:
    """Private complete weather path; only an authorized simulator/replay may use it."""
    validate_seed(race_seed)
    model = model or load_model()
    if isinstance(segments, bool) or not isinstance(segments, int) or segments < 1:
        raise ValueError("weather segments must be positive")
    rain = []
    current = categorical(race_seed, tuple(model["rain"]["states"]),
                          tuple(model["rain"]["initial_distribution"][kind] for kind in model["rain"]["states"]),
                          model["stream_version"], "initial-rain", race_id)
    wetness = []
    current_wetness = 0.0
    for segment in range(segments):
        if segment:
            previous = current
            row = model["rain"]["transition"][previous]
            current = categorical(race_seed, tuple(model["rain"]["states"]), tuple(row),
                                  model["stream_version"], "transition", race_id, segment)
        current_wetness = (
            finite(model["rain"]["wetness_retention_per_segment"]) * current_wetness
            + finite(model["rain"]["wetness_target_weight"]) * model["rain"]["intensity"][current]
        )
        rain.append(current)
        wetness.append(current_wetness)
    return {"rain": rain, "wetness": wetness}


def _advance_distribution(current: str, steps: int, model: dict[str, Any]) -> list[float]:
    states = model["rain"]["states"]
    values = [1.0 if kind == current else 0.0 for kind in states]
    for _ in range(steps):
        values = [sum(values[index] * model["rain"]["transition"][states[index]][target]
                      for index in range(len(states))) for target in range(len(states))]
    return values


def _dirichlet(seed: int, means: list[float], concentration: float, *parts: Any) -> list[float]:
    # Each report key has a local PRNG; there is no mutable global or action stream.
    local = random.Random(int(uniform(seed, *parts) * 2**64))
    draws = [local.gammavariate(max(mean * concentration, 1e-9), 1.0) for mean in means]
    total = sum(draws)
    return [value / total for value in draws]


def forecast(race_seed: int, race_id: str, schedule: dict[str, Any], issue: int,
             model: dict[str, Any] | None = None) -> dict[str, Any]:
    """Public noisy Dirichlet reports; future actual rain is never consulted."""
    validate_seed(race_seed)
    model = model or load_model()
    segments = len(schedule["rain"])
    if isinstance(issue, bool) or not isinstance(issue, int) or not 0 <= issue < segments:
        raise ValueError("forecast issue segment is out of range")
    current = schedule["rain"][issue]
    states = model["rain"]["states"]
    reports = {}
    for target in range(issue + 1, segments):
        lead = target - issue
        means = _advance_distribution(current, lead, model)
        probabilities = _dirichlet(
            race_seed, means, finite(model["rain"]["forecast_concentration_base"]) * lead,
            model["stream_version"], "forecast", race_id, issue, target,
        )
        intensity = sum(probabilities[index] * model["rain"]["intensity"][kind]
                        for index, kind in enumerate(states))
        expected = (
            model["rain"]["intensity"][current] * finite(model["rain"]["wetness_retention_per_segment"]) ** lead
            + finite(model["rain"]["wetness_target_weight"]) * intensity
        )
        reports[str(target)] = {
            "lead_segments": lead,
            "rain_probabilities": {kind: probabilities[index] for index, kind in enumerate(states)},
            "expected_wetness_estimate": expected,
            "mean_concentration": finite(model["rain"]["forecast_concentration_base"]) * lead,
        }
    result = {
        "issue_segment": issue,
        "model": "public Markov means plus independent Dirichlet report noise; concentration grows with lead",
        "forecasts": reports,
        "interpretation": "probabilistic public reports, not a revealed future path or calibrated true-weather posterior",
    }
    reject_public_secrets(result)
    return result


def neutralisation_multiplier(rain_state: str, base_probabilities: dict[str, float],
                              model: dict[str, Any] | None = None) -> dict[str, float]:
    """Adapter for the existing process; preserve a valid probability simplex."""
    model = model or load_model()
    if rain_state not in model["rain"]["states"] or any(
            key not in ("SC", "VSC") for key in base_probabilities):
        raise ValueError("neutralisation state is invalid")
    scale = model["neutralisation"]["sc_vsc_multiplier"][rain_state]
    sc = base_probabilities.get("SC", 0.0) * scale
    vsc = base_probabilities.get("VSC", 0.0) * scale
    sc, vsc = finite(sc, minimum=0.0), finite(vsc, minimum=0.0)
    if sc + vsc > 1.0:
        sc, vsc = sc / (sc + vsc), vsc / (sc + vsc)
    return {"SC": sc, "VSC": vsc, "GREEN": 1.0 - sc - vsc}


def finish_penalty(compounds_raced: list[str]) -> float:
    """Wet-use exemption followed by the existing normal-finish +20 seconds rule."""
    if set(compounds_raced) & set(WET_COMPOUNDS):
        return 0.0
    if len(set(compounds_raced) & set(DRY_COMPOUNDS)) >= 2:
        return 0.0
    return 20.0


def _rival_bias(race_seed: int, race_id: str, car: str, model: dict[str, Any]) -> str:
    spec = model["rival_bias"]
    return categorical(race_seed, tuple(spec["labels"]), tuple(spec["weights"]),
                       model["stream_version"], "wet-bias", race_id, car)


def initial_state(race_seed: int, race_id: str = "m7-micro",
                  model: dict[str, Any] | None = None) -> dict[str, Any]:
    validate_seed(race_seed)
    model = model or load_model()
    segments = model["micro_race"]["segments"]["value"]
    schedule = weather_schedule(race_seed, race_id, segments, model)
    cars = {}
    for car, compound in (("Apex A", "SOFT"), ("Rival 1", "MEDIUM")):
        cars[car] = {
            "base_pace_sec": finite(model["micro_race"]["base_pace_sec"]),
            "elapsed": 0.0, "compound": compound, "tyre_age": 0,
            "compounds_raced": [], "retired": False, "laps": 0,
        }
    return {
        "format_version": 1,
        "private_seed": race_seed,
        "race_id": race_id,
        "model": model,
        "schedule": schedule,
        "private_biases": {car: _rival_bias(race_seed, race_id, car, model) for car in cars},
        "cars": cars,
        "boundary": 0,
        "complete": False,
        "history": [],
    }


def public_observation(state: dict[str, Any]) -> dict[str, Any]:
    if state["complete"]:
        raise ValueError("no observation follows complete M7 micro-race")
    index = state["boundary"]
    model = state["model"]
    observation = {
        "schema_version": 1,
        "m7_enabled": True,
        "boundary": index,
        "segments_total": state["model"]["micro_race"]["segments"]["value"],
        "observed_weather": state["schedule"]["rain"][index],
        "forecast": forecast(state["private_seed"], state["race_id"], state["schedule"], index, model),
        "cars": copy.deepcopy(state["cars"]),
        "visible_segment_history": copy.deepcopy(state["history"]),
        "legal_actions": ["STAY"] if state["cars"]["Apex A"]["retired"] else list(ACTIONS),
        "compound_rule": "wet use exempts two-dry requirement; otherwise two dry compounds or +20 s at normal finish",
        "published_coefficients": "synthetic_only",
        "information_access": "current weather, reports, public cars and resolved segment history only",
    }
    reject_public_secrets(observation)
    return observation


def _next_rival_action(state: dict[str, Any], car: str) -> str:
    model = state["model"]
    index = state["boundary"]
    wetness = state["schedule"]["wetness"][index]
    current = state["cars"][car]
    if current["retired"]:
        return "STAY"
    stay_compound = current["compound"]
    scores = {}
    for compound in COMPOUNDS:
        cost = sum(tyre_offset(compound, wetness, model) + lap * finite(model["micro_race"]["track_deg_multiplier"])
                   * tyre_degradation(compound, wetness, model) for lap in range(3))
        if compound != stay_compound:
            cost += finite(model["micro_race"]["pit_loss_sec"]) + model["compounds"][compound]["warmup_sec"]["value"]
        scores[compound] = cost
    best = min(scores, key=lambda compound: (scores[compound], compound))
    bias = state["private_biases"][car]
    if bias != "ON_TIME":
        shift = model["rival_bias"]["wetness_offset"]["value"]
        adjusted = min(1.0, wetness + shift) if bias == "EARLY" else max(0.0, wetness - shift)
        adjusted_scores = {}
        for compound in COMPOUNDS:
            cost = sum(tyre_offset(compound, adjusted, model) + lap * finite(model["micro_race"]["track_deg_multiplier"])
                       * tyre_degradation(compound, adjusted, model) for lap in range(3))
            if compound != stay_compound:
                cost += finite(model["micro_race"]["pit_loss_sec"]) + model["compounds"][compound]["warmup_sec"]["value"]
            adjusted_scores[compound] = cost
        biased_best = min(adjusted_scores, key=lambda compound: (adjusted_scores[compound], compound))
        wet_direction = (
            (stay_compound in DRY_COMPOUNDS and biased_best in WET_COMPOUNDS)
            or (stay_compound == "INTERMEDIATE" and biased_best == "WET")
        )
        if wet_direction:
            best = biased_best
            if adjusted_scores[best] >= adjusted_scores[stay_compound]:
                best = stay_compound
            scores = adjusted_scores
        elif (stay_compound in DRY_COMPOUNDS and best in WET_COMPOUNDS) or (
                stay_compound == "INTERMEDIATE" and best == "WET"):
            # A delayed choice must not retain a wet pit rejected at adjusted wetness.
            best = stay_compound
    if scores[best] >= scores[stay_compound]:
        best = stay_compound
    final = index == model["micro_race"]["segments"]["value"] - 1
    if final and finish_penalty(current["compounds_raced"] + [best]) == 20.0:
        alternatives = [compound for compound in DRY_COMPOUNDS if compound != stay_compound]
        best = min(alternatives, key=lambda compound: (scores[compound], compound))
    return "STAY" if best == stay_compound else f"PIT_{best}"


def _validate_controlled_action(action: Any) -> str:
    if action not in ACTIONS:
        raise ValueError(f"illegal M7 action: {action!r}")
    return action


def _lap(state: dict[str, Any], car: str, lap: int) -> dict[str, Any]:
    model = state["model"]
    index = state["boundary"]
    vehicle = state["cars"][car]
    wetness = state["schedule"]["wetness"][index]
    compound = vehicle["compound"]
    base = (vehicle["base_pace_sec"] + tyre_offset(compound, wetness, model)
            + vehicle["tyre_age"] * finite(model["micro_race"]["track_deg_multiplier"])
            * tyre_degradation(compound, wetness, model))
    vehicle["elapsed"] += base
    vehicle["tyre_age"] += 1
    vehicle["laps"] += 1
    if not vehicle["compounds_raced"] or vehicle["compounds_raced"][-1] != compound:
        vehicle["compounds_raced"].append(compound)
    p_retire, p_spin = incident_probabilities(compound, wetness, model)
    draw = uniform(state["private_seed"], model["stream_version"], "incident", state["race_id"], car, index, lap)
    event = "NONE"
    if draw < p_retire:
        event = "OFF_RETIRE"
        vehicle["retired"] = True
    elif draw < p_retire + p_spin:
        event = "SPIN"
        vehicle["elapsed"] += finite(model["micro_race"]["spin_loss_sec"])
    return {
        "car": car, "lap": lap, "lap_time": base + (finite(model["micro_race"]["spin_loss_sec"]) if event == "SPIN" else 0.0),
        "compound": compound, "incident": event,
    }


def step(state: dict[str, Any], controlled_action: str) -> dict[str, Any]:
    """Resolve one non-mutating simultaneous-action boundary exactly once."""
    if state["complete"]:
        raise ValueError("M7 micro-race is complete")
    action = _validate_controlled_action(controlled_action)
    if state["cars"]["Apex A"]["retired"] and action != "STAY":
        raise ValueError("a retired controlled car cannot pit")
    if not isinstance(state.get("private_biases"), dict):
        raise ValueError("M7 private state is missing rival initialization")
    next_state = copy.deepcopy(state)
    index = next_state["boundary"]
    model = next_state["model"]
    actions = {"Apex A": action, "Rival 1": _next_rival_action(state, "Rival 1")}
    records = []
    for car, selected in actions.items():
        if not selected.startswith("PIT_"):
            continue
        compound = selected.removeprefix("PIT_")
        _validate_compound(compound, model)
        vehicle = next_state["cars"][car]
        vehicle["compound"] = compound
        vehicle["tyre_age"] = 0
        vehicle["elapsed"] += finite(model["micro_race"]["pit_loss_sec"]) + model["compounds"][compound]["warmup_sec"]["value"]
    for lap in range(int(finite(model["micro_race"]["laps_per_segment"]))):
        for car in ("Apex A", "Rival 1"):
            if not next_state["cars"][car]["retired"]:
                records.append(_lap(next_state, car, lap))
    next_state["history"].append({
        "boundary": index, "observed_weather": next_state["schedule"]["rain"][index],
        "actions": actions, "laps": records,
    })
    next_state["boundary"] += 1
    next_state["complete"] = next_state["boundary"] == model["micro_race"]["segments"]["value"]
    return next_state


def classification(state: dict[str, Any]) -> list[dict[str, Any]]:
    if not state["complete"]:
        raise ValueError("classification requires a complete M7 micro-race")
    result = []
    for car, vehicle in state["cars"].items():
        penalty = finish_penalty(vehicle["compounds_raced"])
        result.append({
            "car": car,
            "status": "RETIRED" if vehicle["retired"] else "FINISHED",
            "elapsed": vehicle["elapsed"],
            "finish_penalty_sec": penalty,
            "official_micro_race_elapsed": vehicle["elapsed"] + penalty,
            "compounds_raced": list(vehicle["compounds_raced"]),
            "wet_exempt": bool(set(vehicle["compounds_raced"]) & set(WET_COMPOUNDS)),
        })
    result.sort(key=lambda row: (row["status"] == "RETIRED", row["official_micro_race_elapsed"], row["car"]))
    output = {
        "classification": result,
        "observations replayable": True,
        "sanction_note": "preserves existing +20 s normal-finish rule; no suspended/red-flag result modelled",
    }
    reject_public_secrets(output)
    return output


def replay(race_seed: int, actions: list[str], race_id: str = "m7-micro",
           model: dict[str, Any] | None = None) -> dict[str, Any]:
    state = initial_state(race_seed, race_id, model)
    observations = []
    for action in actions:
        if state["complete"]:
            raise ValueError("M7 replay has more actions than segments")
        observations.append(public_observation(state))
        state = step(state, action)
    if not state["complete"]:
        raise ValueError("M7 replay does not complete the micro-race")
    return {"state": state, "observations": observations, "result": classification(state)}


def _expected_lap_cost(compound: str, wetness: float, age: int,
                       model: dict[str, Any], warm_up: bool = False) -> float:
    cost = tyre_offset(compound, wetness, model) + age * finite(model["micro_race"]["track_deg_multiplier"]) * tyre_degradation(compound, wetness, model)
    retire, spin = incident_probabilities(compound, wetness, model)
    cost += retire * finite(model["micro_race"]["retirement_value_cost_sec"]) + spin * finite(model["micro_race"]["spin_loss_sec"])
    if warm_up:
        cost += model["compounds"][compound]["warmup_sec"]["value"]
    return cost


def action_values(observation: dict[str, Any]) -> dict[str, Any]:
    """Public forecast expectation for one future segment, without actual future weather."""
    if observation["cars"]["Apex A"]["retired"]:
        return {
            "classification": "SEPARATED", "chosen_action": "STAY", "runner_up_action": None,
            "estimated_margin_sec": None, "near_tie_threshold_sec": load_model()["micro_race"]["near_tie_threshold_sec"]["value"],
            "action_cost_estimates_sec": {"STAY": 0.0},
            "value_basis": "retired controlled car; only STAY is legal",
            "information_access": "public retirement status only",
        }
    index = observation["boundary"]
    model = load_model()
    if str(index + 1) in observation["forecast"]["forecasts"]:
        wetness = observation["forecast"]["forecasts"][str(index + 1)]["expected_wetness_estimate"]
        value_basis = "next-segment public forecast"
    else:
        # The final boundary has no future forecast; value current conditions only.
        wetness = model["rain"]["intensity"][observation["observed_weather"]]
        value_basis = "final-boundary current observed condition; no future forecast"
    vehicle = observation["cars"]["Apex A"]
    values = {}
    for action in observation["legal_actions"]:
        compound = vehicle["compound"] if action == "STAY" else action.removeprefix("PIT_")
        age = vehicle["tyre_age"] if action == "STAY" else 0
        cost = sum(_expected_lap_cost(compound, wetness, age + lap, model) for lap in range(3))
        if action != "STAY":
            cost += finite(model["micro_race"]["pit_loss_sec"]) + model["compounds"][compound]["warmup_sec"]["value"]
        values[action] = cost
    ranked = sorted(values, key=lambda action: (values[action], action))
    margin = values[ranked[1]] - values[ranked[0]]
    threshold = model["micro_race"]["near_tie_threshold_sec"]["value"]
    return {
        "classification": "NEAR_TIE" if margin <= threshold else "SEPARATED",
        "chosen_action": ranked[0], "runner_up_action": ranked[1],
        "estimated_margin_sec": margin,
        "near_tie_threshold_sec": threshold,
        "action_cost_estimates_sec": values,
        "value_basis": value_basis,
        "information_access": "public forecast/current condition and public car state only; realized future weather not used",
    }
