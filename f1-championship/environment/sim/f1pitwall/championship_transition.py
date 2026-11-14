"""Deterministic synthetic race-to-race championship transitions."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .championship import ChampionshipState, TEAM_DRIVERS

# Synthetic placeholders, not measurements from real Formula 1 data.
SYNTHETIC_RULES = {
    "free_replacements_per_component": 1,
    "excess_replacement_grid_drop": 5,
    "maximum_wear_for_use": 0.85,
    "wear_factor": {"ICE": 0.16, "turbo": 0.13, "energy_store": 0.10},
}


@dataclass(frozen=True)
class RaceStartConditions:
    race_index: int
    race_name: str
    grid_drop_positions: dict[str, int]
    applied_to_grid: bool


def default_component_decisions(state: ChampionshipState) -> list[dict[str, str]]:
    """Return an explicit USE decision for every driver/component pair."""
    return [{"driver": driver, "component": component, "action": "USE"}
            for driver, components in state.power_units.items() for component in components]


def available_component_actions(state: ChampionshipState, driver: str) -> dict[str, list[str]]:
    state.validate()
    if driver not in state.power_units:
        raise ValueError("unknown driver")
    team = _driver_team(driver)
    spares = state.resource_inventory[team]["component_spares"]
    available = {}
    for name, component in state.power_units[driver].items():
        actions = []
        if component.wear <= SYNTHETIC_RULES["maximum_wear_for_use"]:
            actions.append("USE")
        if spares > 0:
            actions.append("REPLACE")
        available[name] = actions
    return available


def prepare_race(state: ChampionshipState, decisions: Any) -> RaceStartConditions:
    """Validate and atomically apply component choices before the current race."""
    state.validate()
    if state.race_index >= len(state.calendar):
        raise ValueError("championship is complete")
    if state.race_prepared:
        raise ValueError("current race is already prepared")
    clean = _validate_decisions(state, decisions)

    replacements_by_team = {team: 0 for team in TEAM_DRIVERS}
    for driver, component, action in clean:
        if action == "USE" and component.wear > SYNTHETIC_RULES["maximum_wear_for_use"]:
            raise ValueError(f"{driver} {component} is too worn to use")
        if action == "REPLACE":
            replacements_by_team[_driver_team(driver)] += 1
    for team, count in replacements_by_team.items():
        if count > state.resource_inventory[team]["component_spares"]:
            raise ValueError(f"{team} does not have enough component spares")

    for driver, component, action in clean:
        if action == "REPLACE":
            team = _driver_team(driver)
            if component.replacements >= SYNTHETIC_RULES["free_replacements_per_component"]:
                state.grid_penalties[driver] += SYNTHETIC_RULES["excess_replacement_grid_drop"]
            component.wear = 0.0
            component.replacements += 1
            state.resource_inventory[team]["component_spares"] -= 1
    state.race_prepared = True
    state.grid_penalties_applied = not any(state.grid_penalties.values())
    state.validate()
    return race_start_conditions(state)


def race_start_conditions(state: ChampionshipState) -> RaceStartConditions:
    if not state.race_prepared:
        raise ValueError("race has not been prepared")
    return RaceStartConditions(
        race_index=state.race_index,
        race_name=state.calendar[state.race_index].name,
        grid_drop_positions=dict(state.grid_penalties),
        applied_to_grid=state.grid_penalties_applied,
    )


def mark_grid_penalties_applied(state: ChampionshipState) -> RaceStartConditions:
    """Acknowledge that an external race engine applied the exposed grid drops."""
    if not state.race_prepared:
        raise ValueError("race has not been prepared")
    state.grid_penalties_applied = True
    return race_start_conditions(state)


def complete_race(state: ChampionshipState, driver_points: Any) -> ChampionshipState:
    """Apply points and deterministic wear, then advance to the next race."""
    state.validate()
    if not state.race_prepared:
        raise ValueError("race has not been prepared")
    if not state.grid_penalties_applied:
        raise ValueError("grid penalties remain unapplied")
    if not isinstance(driver_points, dict) or set(driver_points) != set(state.driver_points):
        raise ValueError("race points must contain every configured driver exactly once")
    for points in driver_points.values():
        if isinstance(points, bool) or not isinstance(points, int) or points < 0:
            raise ValueError("race points must be non-negative integers")

    stress = state.calendar[state.race_index].power_unit_stress
    for driver, points in driver_points.items():
        state.driver_points[driver] += points
    for team, drivers in TEAM_DRIVERS.items():
        state.team_points[team] += sum(driver_points[driver] for driver in drivers)
    for components in state.power_units.values():
        for name, component in components.items():
            component.wear = min(1.0, component.wear + stress * SYNTHETIC_RULES["wear_factor"][name])

    state.race_index += 1
    state.grid_penalties = {driver: 0 for driver in state.grid_penalties}
    state.race_prepared = False
    state.grid_penalties_applied = False
    state.validate()
    return state


def _validate_decisions(state: ChampionshipState, decisions: Any) -> list[tuple[str, Any, str]]:
    if not isinstance(decisions, list):
        raise ValueError("component decisions must be a list")
    expected = {(driver, name) for driver, components in state.power_units.items()
                for name in components}
    seen = set()
    clean = []
    for decision in decisions:
        if not isinstance(decision, dict) or set(decision) != {"driver", "component", "action"}:
            raise ValueError("each component decision must contain driver, component, and action")
        key = (decision["driver"], decision["component"])
        if key not in expected:
            raise ValueError("unknown driver or component")
        if key in seen:
            raise ValueError("duplicate component decision")
        if decision["action"] not in ("USE", "REPLACE"):
            raise ValueError("component action must be USE or REPLACE")
        seen.add(key)
        clean.append((key[0], state.power_units[key[0]][key[1]], decision["action"]))
    if seen != expected:
        raise ValueError("every driver/component pair requires exactly one decision")
    return clean


def _driver_team(driver: str) -> str:
    for team, drivers in TEAM_DRIVERS.items():
        if driver in drivers:
            return team
    raise ValueError("unknown driver")
