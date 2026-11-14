"""Adapter between persistent championship state and the race engine (Track A)."""

from __future__ import annotations

import copy
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Mapping, Optional

from . import coefficients as coef
from . import engine
from .championship import ChampionshipState
from .championship_transition import (
    RaceStartConditions,
    complete_race,
    driver_team,
    mark_grid_penalties_applied,
    prepare_race,
)

ENGINE_TO_CHAMPIONSHIP_DRIVER = {
    "Apex A": "Apex A",
    "Apex B": "Apex B",
    "Rival 1": "Orion A",
    "Rival 3": "Orion B",
    "Rival 2": "Nova A",
    "Rival 4": "Nova B",
    "Rival 5": "Vertex A",
    "Rival 6": "Vertex B",
}
CHAMPIONSHIP_TO_ENGINE_DRIVER = {value: key for key, value in ENGINE_TO_CHAMPIONSHIP_DRIVER.items()}


@dataclass(frozen=True)
class ChampionshipRaceResult:
    race_index: int
    race_name: str
    seed: int
    starting_grid: List[str]
    start_conditions: RaceStartConditions
    race_result: Dict[str, Any]
    awarded_points: Dict[str, int]


@dataclass
class PreparedChampionshipRace:
    race_index: int
    race_name: str
    seed: int
    starting_grid: List[str]
    start_conditions: RaceStartConditions
    race_state: Dict[str, Any]


def car_performance(state: ChampionshipState, driver: str,
                    coeffs: Mapping[str, Any] = coef.DEFAULT) -> Dict[str, float]:
    """Public performance model for one driver at the current track and current wear."""
    track = state.calendar[state.race_index]
    wears = {name: component.wear for name, component in state.power_units[driver].items()}
    engine_name = CHAMPIONSHIP_TO_ENGINE_DRIVER[driver]
    base = engine.LEGACY_BASE_PACE[engine_name]
    offset = coef.team_offset(driver_team(driver), track.archetype, coeffs)
    loss = coef.pace_loss(wears, track.power_unit_stress, coeffs)
    return {"published_base_pace": base, "track_offset": offset, "wear_pace_loss": loss,
            "pace": base + offset + loss,
            "dnf_probability": coef.dnf_probability(wears, track.power_unit_stress, coeffs)}


def race_config(state: ChampionshipState, coeffs: Mapping[str, Any] = coef.DEFAULT,
                events: Optional[List[str]] = None) -> Dict[str, Any]:
    """Qualifying order by pace (grid drops are applied afterwards)."""
    track = state.calendar[state.race_index]
    perf = {CHAMPIONSHIP_TO_ENGINE_DRIVER[d]: car_performance(state, d, coeffs)
            for d in CHAMPIONSHIP_TO_ENGINE_DRIVER}
    grid = sorted(perf, key=lambda name: (perf[name]["pace"], name))
    return {
        "grid": grid,
        "pace": {name: values["pace"] for name, values in perf.items()},
        "deg_multiplier": coef.degradation_multiplier(track.tyre_degradation, coeffs),
        "overtaking": coef.overtaking_model(coeffs),
        "overtaking_difficulty": coef.overtaking_difficulty(track.overtaking_difficulty, coeffs),
        "dnf_prob": {name: values["dnf_probability"] for name, values in perf.items()},
        "tyres": coef.tyre_model(coeffs),
        "pit": coef.pit_model(track.archetype, coeffs),
        **coef.race_format(coeffs),
        "events": events,
    }


def run_championship_race(state: ChampionshipState, component_decisions: Any, race_actions: Any,
                          seed: int, coeffs: Mapping[str, Any] = coef.DEFAULT) -> ChampionshipRaceResult:
    """Run one race and commit its result atomically to the season."""
    state.validate()
    if isinstance(seed, bool) or not isinstance(seed, int):
        raise ValueError("race seed must be an integer")
    working = copy.deepcopy(state)
    prepare_race(working, component_decisions, coeffs)
    active = start_prepared_race(working, seed, coeffs)
    actions = _validate_race_actions(race_actions, active.race_state)
    for action in actions:
        engine.step(active.race_state, action)
    result = finish_prepared_race(working, active, coeffs)
    _commit_state(state, working)
    return result


def start_prepared_race(state: ChampionshipState, seed: int,
                        coeffs: Mapping[str, Any] = coef.DEFAULT,
                        events: Optional[List[str]] = None) -> PreparedChampionshipRace:
    """Apply a prepared race's grid drops and initialize the race engine."""
    if not state.race_prepared:
        raise ValueError("championship race has not been prepared")
    if isinstance(seed, bool) or not isinstance(seed, int):
        raise ValueError("race seed must be an integer")
    race_index = state.race_index
    prepared = RaceStartConditions(
        race_index=race_index,
        race_name=state.calendar[race_index].name,
        grid_drop_positions=dict(state.grid_penalties),
        applied_to_grid=state.grid_penalties_applied,
    )
    race_state = engine.new_state(seed, race_config(state, coeffs, events))
    starting_grid = _apply_grid_penalties(race_state, prepared)
    applied = mark_grid_penalties_applied(state)
    return PreparedChampionshipRace(race_index=race_index, race_name=state.calendar[race_index].name,
                                    seed=seed, starting_grid=starting_grid, start_conditions=applied,
                                    race_state=race_state)


def finish_prepared_race(state: ChampionshipState, active: PreparedChampionshipRace,
                         coeffs: Mapping[str, Any] = coef.DEFAULT) -> ChampionshipRaceResult:
    if state.race_index != active.race_index or not active.race_state["complete"]:
        raise ValueError("prepared race is incomplete or does not match championship state")
    mapped_result = _map_race_result(engine.result(active.race_state))
    awarded_points = points_from_classification(mapped_result["classification"])
    complete_race(state, awarded_points, coeffs)
    return ChampionshipRaceResult(race_index=active.race_index, race_name=active.race_name,
                                  seed=active.seed, starting_grid=list(active.starting_grid),
                                  start_conditions=active.start_conditions, race_result=mapped_result,
                                  awarded_points=awarded_points)


def stay_race_policy(_: ChampionshipState) -> List[Dict[str, str]]:  # legacy smoke helper
    return [{"driver_a": "STAY", "driver_b": "STAY"} for _ in engine.DECISION_LAPS]  # legacy format only


def _apply_grid_penalties(race_state: Dict[str, Any], start: RaceStartConditions) -> List[str]:
    """Each penalised car drops N places from its qualifying slot; slots keep their gaps."""
    baseline = [car["name"] for car in sorted(race_state["cars"],
                                               key=lambda car: (car["elapsed"], car["name"]))]
    grid = list(baseline)
    for engine_driver in baseline:
        drop = start.grid_drop_positions[ENGINE_TO_CHAMPIONSHIP_DRIVER[engine_driver]]
        if drop:
            current = grid.index(engine_driver)
            grid.pop(current)
            grid.insert(min(current + drop, len(grid)), engine_driver)
    if len(grid) != 8 or set(grid) != set(baseline):
        raise ValueError("grid penalties did not produce a valid eight-car permutation")
    elapsed_slots = sorted(car["elapsed"] for car in race_state["cars"])
    cars = {car["name"]: car for car in race_state["cars"]}
    for elapsed, name in zip(elapsed_slots, grid):
        cars[name]["elapsed"] = elapsed
    if "config" in race_state:
        race_state["config"]["grid_after_penalties"] = list(grid)
    return [ENGINE_TO_CHAMPIONSHIP_DRIVER[name] for name in grid]


def _validate_race_actions(value: Any, race_state: Dict[str, Any]) -> List[Dict[str, str]]:
    count = len(engine._decision_laps(race_state))
    if not isinstance(value, list) or len(value) != count:
        raise ValueError(f"exactly {count} race actions are required")
    return [engine.validate_action(action, race_state) for action in value]


def _map_race_result(value: Dict[str, Any]) -> Dict[str, Any]:
    mapped = copy.deepcopy(value)
    for entry in mapped["classification"]:
        entry["driver"] = ENGINE_TO_CHAMPIONSHIP_DRIVER[entry["driver"]]
    return mapped


def points_from_classification(classification: List[Dict[str, Any]]) -> Dict[str, int]:
    points = {driver: 0 for driver in CHAMPIONSHIP_TO_ENGINE_DRIVER}
    for entry in classification:
        points[entry["driver"]] = entry.get("points", engine.POINTS[entry["position"] - 1])
    return points


def _commit_state(target: ChampionshipState, source: ChampionshipState) -> None:
    target.__dict__.clear()
    target.__dict__.update(copy.deepcopy(source.__dict__))
