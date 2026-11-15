"""Owner-side M7 weather/tyre adapter for the authoritative configured race engine.

Opt-in only. No M1–M6 state is created here. Disabled configurations never import or
evaluate this module's fixture, forecasts, draws or wet actions.
"""

from __future__ import annotations

import copy
from typing import Any

WEATHER_KEY = "v22_weather"
WET_COMPOUNDS = ("INTERMEDIATE", "WET")
DRY_COMPOUNDS = ("SOFT", "MEDIUM", "HARD")
COMPOUNDS = DRY_COMPOUNDS + WET_COMPOUNDS


def enabled(state: dict[str, Any]) -> bool:
    return WEATHER_KEY in state.get("config", {})


def create(race_seed: int, race_id: str, segment_count: int) -> dict[str, Any]:
    if isinstance(segment_count, bool) or not isinstance(segment_count, int) or segment_count < 1:
        raise ValueError("M7 needs at least one configured segment")
    from track_c.v22 import weather as micro
    model = micro.load_model()
    schedule = micro.weather_schedule(race_seed, race_id, segment_count, model)
    return {
        "seed": race_seed,
        "race_id": race_id,
        "segments_total": segment_count,
        "schedule": schedule,
        "model": model,
        "incident_log": [],
        "raced_wet_compounds": {car: [] for car in ("Apex A", "Apex B", "Rival 1", "Rival 2", "Rival 3", "Rival 4", "Rival 5", "Rival 6")},
    }


def context(state: dict[str, Any]) -> dict[str, Any]:
    if not enabled(state):
        raise ValueError("M7 weather is not enabled for this race")
    return state["config"][WEATHER_KEY]


def weather_observation(state: dict[str, Any]) -> dict[str, Any]:
    from . import engine
    ctx = context(state)
    from track_c.v22.common import reject_public_secrets
    from track_c.v22.weather import forecast
    rain = ctx["schedule"]["rain"][state["step"]]
    result = {
        "schema_version": 1,
        "m7_enabled": True,
        "observed_weather": rain,
        "forecast": forecast(ctx["seed"], ctx["race_id"], ctx["schedule"], state["step"], ctx["model"]),
        "public_weather_history": copy.deepcopy(ctx["incident_log"]),
        "compounds_used": {
            car["name"]: sorted(set(car.get("weather_raced", [])), key=lambda c: c)
            for car in state["cars"]},
        "wet_exemption": "INTERMEDIATE/WET raced car is exempt from the two-dry requirement",
        "legal_actions": engine.legal_actions(state),
        "data_status": "synthetic_only",
    }
    reject_public_secrets(result)
    return result


def _current(state: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any], float]:
    ctx = context(state)
    return ctx, ctx["model"], ctx["schedule"]["wetness"][state["step"]]


def legal_actions(base_actions: list[str], enabled_flag: bool) -> list[str]:
    if not enabled_flag:
        return base_actions
    return ["STAY", "PIT_SOFT", "PIT_MEDIUM", "PIT_HARD", "PIT_INTERMEDIATE", "PIT_WET"]


def warmup(compound: str, state: dict[str, Any], old_warmups: dict[str, float]) -> float:
    if not enabled(state):
        return old_warmups.get(compound, 0.0)
    return context(state)["model"]["compounds"][compound]["warmup_sec"]["value"]


def adopt_tyre_model(state: dict[str, Any]) -> None:
    """Add only the no-cliff/warmup metadata required by existing engine helpers."""
    if not enabled(state):
        return
    ctx = context(state)
    tyre_model = state["config"].get("tyres")
    if tyre_model is None:
        raise ValueError("M7 requires the configured Track B tyre model")
    for compound in WET_COMPOUNDS:
        # The contract supplies no calibrated cliff/lifetime for these compounds.
        tyre_model["compounds"].setdefault(compound, {"life_laps": 10**6, "offset": 0.0, "degradation": 0.0})
        if "pit" in state["config"]:
            state["config"]["pit"]["out_lap_warmup_sec"].setdefault(
                compound, ctx["model"]["compounds"][compound]["warmup_sec"]["value"])


def _race_compound(vehicle: dict[str, Any], compound: str) -> None:
    raced = vehicle.setdefault("weather_raced", [])
    if not raced or raced[-1] != compound:
        raced.append(compound)


def segment_time(state: dict[str, Any], car: dict[str, Any], position: int, deg: float,
                 traffic: float | None, tyres: dict[str, Any] | None, laps: int,
                 legacy_time: float | None = None) -> float:
    """Apply one lap at a time only when M7 is enabled; OFF uses the exact caller path."""
    if not enabled(state):
        return legacy_time
    return _segment(state, car, position, deg, traffic, tyres, laps)


def _wet_cliff(tyres: dict[str, Any] | None, compound: str) -> float:
    if compound in WET_COMPOUNDS:
        return 0.0
    return tyres["cliff_sec_per_lap_per_lap"] if tyres is not None else 0.0


def _segment(state: dict[str, Any], car: dict[str, Any], position: int, deg: float,
             traffic: float | None, tyres: dict[str, Any] | None, laps: int) -> float:
    # Kept in this module to make engine.step and integrated.race._green_segment
    # share exactly the same weather-aware timing/incident implementation.
    ctx, model, wetness = _current(state)
    from track_c.v22.weather import incident_probabilities, tyre_degradation, tyre_offset
    from track_c.v22.common import finite
    from . import engine
    if traffic is None:
        traffic = min(0.70, 0.10 * (position - 1))
    if car.get("weather_retired"):
        return 0.0
    elapsed = 0.0
    compound = car["compound"]
    if compound in DRY_COMPOUNDS and tyres is not None and wetness == 0.0:
        dry = tyres["compounds"][compound]
        offset = float(dry["offset"])
        deg_lap = dry["degradation"] * deg
        cliff = _wet_cliff(tyres, compound) * deg
        life = dry.get("life_laps", 10**6)
    else:
        offset = tyre_offset(compound, wetness, model)
        deg_lap = tyre_degradation(compound, wetness, model) * deg
        life = 10**6
        cliff = 0.0
    for offset_lap in range(laps):
        elapsed += (car["base_pace"] + offset + deg_lap * (car["tyre_age"] + offset_lap)
                    + cliff * max(0, car["tyre_age"] + offset_lap - life) + traffic)
        car.setdefault("_weather_lap_number", 0)
        car["_weather_lap_number"] += 1
        _race_compound(car, compound)
        retire, spin = incident_probabilities(compound, wetness, model)
        from track_c.v22.common import uniform
        draw = uniform(ctx["seed"], model["stream_version"], "authoritative-weather-incident",
                       ctx["race_id"], car["name"], car["_weather_lap_number"])
        if draw < retire:
            car["weather_retired"] = True
            event = "OFF_RETIRE"
        elif draw < retire + spin:
            elapsed += finite(model["micro_race"]["spin_loss_sec"])
            event = "SPIN"
        else:
            event = None
        if event is not None:
            ctx["incident_log"].append({"boundary": state["step"] + 1, "driver": car["name"],
                                        "event": event, "compound": compound})
        if car.get("weather_retired"):
            break
    return round(elapsed, 3)


def retire_exempt(compound_history: list[str]) -> bool:
    return bool(set(compound_history) & set(WET_COMPOUNDS))


def incident(state: dict[str, Any], car: dict[str, Any], laps: int) -> None:
    """Apply weather risks after neutralized segment running, not to retired cars."""
    ctx, model, wetness = _current(state)
    from track_c.v22.weather import incident_probabilities
    from track_c.v22.common import finite, uniform
    if car.get("weather_retired"):
        return
    compound = car["compound"]
    for _ in range(laps):
        car.setdefault("_weather_lap_number", 0)
        car["_weather_lap_number"] += 1
        _race_compound(car, compound)
        retire, spin = incident_probabilities(compound, wetness, model)
        draw = uniform(ctx["seed"], model["stream_version"], "authoritative-weather-incident",
                       ctx["race_id"], car["name"], car["_weather_lap_number"])
        if draw < retire:
            event = "OFF_RETIRE"
            car["weather_retired"] = True
        elif draw < retire + spin:
            car["elapsed"] += finite(model["micro_race"]["spin_loss_sec"])
            event = "SPIN"
        else:
            event = None
        if event is not None:
            ctx["incident_log"].append({"boundary": state["step"] + 1, "driver": car["name"],
                                        "event": event, "compound": compound})
        if car.get("weather_retired"):
            break


def rival_action(state: dict[str, Any], car: dict[str, Any], status: str, index: int,
                 decision_count: int, tyres: dict[str, Any] | None,
                 remaining: int) -> str:
    """Public current-wetness wet switch with a private early/late bias, or legacy STAY."""
    if not enabled(state) or car.get("weather_retired"):
        return "STAY"
    from . import engine
    from . import rival_policies
    from track_c.v22.common import finite
    ctx, model, wetness = _current(state)
    from track_c.v22.weather import tyre_offset, tyre_degradation
    if wetness < 0.24 and ctx["schedule"]["rain"][index] == "DRY":
        return engine._rival_action(car, status, index, decision_count, tyres, remaining)
    current = car["compound"]
    scores = {}
    for compound in COMPOUNDS:
        age = car["tyre_age"]
        score = 3 * (car["base_pace"] + tyre_offset(compound, wetness, model)
                     + age * tyre_degradation(compound, wetness, model)
                     + finite(ctx["model"]["micro_race"]["track_deg_multiplier"]) * tyre_degradation(compound, wetness, model))
        if compound != current:
            score += engine.pit_loss(state, status) + model["compounds"][compound]["warmup_sec"]["value"]
        scores[compound] = score
    best = min(scores, key=lambda candidate: (scores[candidate], candidate))
    from track_c.v22.weather import _rival_bias
    bias = _rival_bias(ctx["seed"], ctx["race_id"], car["name"], model)
    changed = best != current
    if changed and bias != "ON_TIME" and current in DRY_COMPOUNDS and best in WET_COMPOUNDS:
        shift = model["rival_bias"]["wetness_offset"]["value"]
        adjusted = min(1.0, wetness + shift) if bias == "EARLY" else max(0.0, wetness - shift)
        adjusted_scores = {}
        for compound in COMPOUNDS:
            score = 3 * (car["base_pace"] + tyre_offset(compound, adjusted, model)
                         + car["tyre_age"] * tyre_degradation(compound, adjusted, model)
                         + finite(ctx["model"]["micro_race"]["track_deg_multiplier"]) * tyre_degradation(compound, adjusted, model))
            if compound != current:
                score += engine.pit_loss(state, status) + model["compounds"][compound]["warmup_sec"]["value"]
            adjusted_scores[compound] = score
        biased_best = min(adjusted_scores, key=lambda candidate: (adjusted_scores[candidate], candidate))
        if biased_best in WET_COMPOUNDS or current == "INTERMEDIATE" and biased_best == "WET":
            best = biased_best
        if adjusted_scores[best] >= adjusted_scores[current]:
            best = current
    if index == decision_count - 1:
        from . import engine
        wet_use = retire_exempt(car.get("weather_raced", []) + ([] if best == current else [best]))
        if tyres is not None and tyres["two_compound_rule"] and not wet_use:
            used = set(car["compounds_used"])
            if len(used) < 2 and best == current:
                alternate = {"SOFT": "MEDIUM", "HARD": "MEDIUM", "MEDIUM": "SOFT" if remaining <= 10 else "HARD"}[current]
                best = alternate
    return "STAY" if best == current else f"PIT_{best}"


def retired_context(state: dict[str, Any], car_name: str) -> bool:
    return enabled(state) and any(car["name"] == car_name and car.get("weather_retired") for car in state["cars"])
