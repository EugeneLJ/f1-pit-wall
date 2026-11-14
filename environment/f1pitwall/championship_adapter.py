"""Adapter between persistent championship state and the legacy race engine."""

from __future__ import annotations

import copy
from dataclasses import dataclass
from typing import Any, Callable

from . import engine
from .championship import ChampionshipState
from .championship_transition import (
    RaceStartConditions,
    complete_race,
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
    starting_grid: list[str]
    start_conditions: RaceStartConditions
    race_result: dict[str, Any]
    awarded_points: dict[str, int]


def run_championship_race(
    state: ChampionshipState,
    component_decisions: Any,
    race_actions: Any,
    seed: int,
) -> ChampionshipRaceResult:
    """Run one legacy-engine race and commit its result atomically to the season."""
    state.validate()
    clean_actions = _validate_race_actions(race_actions)
    if isinstance(seed, bool) or not isinstance(seed, int):
        raise ValueError("race seed must be an integer")

    working = copy.deepcopy(state)
    prepared = prepare_race(working, component_decisions)
    race_state = engine.new_state(seed)
    starting_grid = _apply_grid_penalties(race_state, prepared)
    applied = mark_grid_penalties_applied(working)

    for action in clean_actions:
        engine.step(race_state, action)
    raw_result = engine.result(race_state)
    mapped_result = _map_race_result(raw_result)
    awarded_points = _points_from_classification(mapped_result["classification"])
    race_index = working.race_index
    race_name = working.calendar[race_index].name
    complete_race(working, awarded_points)
    _commit_state(state, working)
    return ChampionshipRaceResult(
        race_index=race_index,
        race_name=race_name,
        seed=seed,
        starting_grid=starting_grid,
        start_conditions=applied,
        race_result=mapped_result,
        awarded_points=awarded_points,
    )


def run_championship(
    state: ChampionshipState,
    component_policy: Callable[[ChampionshipState], Any],
    race_policy: Callable[[ChampionshipState], Any],
    base_seed: int = engine.SEED,
    race_count: int | None = None,
) -> list[ChampionshipRaceResult]:
    """Run a deterministic sequence without exposing future event schedules to policies."""
    remaining = len(state.calendar) - state.race_index
    count = remaining if race_count is None else race_count
    if isinstance(count, bool) or not isinstance(count, int) or not 0 <= count <= remaining:
        raise ValueError("race_count must fit within the remaining calendar")
    results = []
    for _ in range(count):
        index = state.race_index
        results.append(run_championship_race(
            state,
            component_policy(copy.deepcopy(state)),
            race_policy(copy.deepcopy(state)),
            base_seed + index,
        ))
    return results


def stay_race_policy(_: ChampionshipState) -> list[dict[str, str]]:
    """Non-privileged smoke policy: both Apex cars stay at every decision."""
    return [{"driver_a": "STAY", "driver_b": "STAY"}
            for _ in engine.DECISION_LAPS]


def _apply_grid_penalties(
    race_state: dict[str, Any], start: RaceStartConditions,
) -> list[str]:
    baseline = [car["name"] for car in sorted(race_state["cars"],
                                               key=lambda car: (car["elapsed"], car["name"]))]
    grid = list(baseline)
    for engine_driver in baseline:
        championship_driver = ENGINE_TO_CHAMPIONSHIP_DRIVER[engine_driver]
        drop = start.grid_drop_positions[championship_driver]
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
    return [ENGINE_TO_CHAMPIONSHIP_DRIVER[name] for name in grid]


def _validate_race_actions(value: Any) -> list[dict[str, str]]:
    if not isinstance(value, list) or len(value) != len(engine.DECISION_LAPS):
        raise ValueError(f"exactly {len(engine.DECISION_LAPS)} race actions are required")
    return [engine.validate_action(action) for action in value]


def _map_race_result(value: dict[str, Any]) -> dict[str, Any]:
    mapped = copy.deepcopy(value)
    for entry in mapped["classification"]:
        entry["driver"] = ENGINE_TO_CHAMPIONSHIP_DRIVER[entry["driver"]]
    return mapped


def _points_from_classification(classification: list[dict[str, Any]]) -> dict[str, int]:
    points = {driver: 0 for driver in CHAMPIONSHIP_TO_ENGINE_DRIVER}
    for entry in classification:
        points[entry["driver"]] = engine.POINTS[entry["position"] - 1]
    return points


def _commit_state(target: ChampionshipState, source: ChampionshipState) -> None:
    target.__dict__.clear()
    target.__dict__.update(copy.deepcopy(source.__dict__))
