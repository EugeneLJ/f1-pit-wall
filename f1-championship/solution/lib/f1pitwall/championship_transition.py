"""Deterministic race-to-race championship transitions (Track A rules).

Rules (coefficients in fixtures/track_a_coefficients.json, all synthetic):
- Each driver has ICE, turbo and energy_store. Wear accrues after every race in
  proportion to the track's power_unit_stress and never depends on race events.
- USE is legal while wear <= max_wear_for_use; REPLACE is always legal.
- REPLACE consumes a free unit from the team pool (shared by both drivers) if one
  is left; otherwise it costs a component-specific grid drop for that race.
- Rivals follow a public threshold rule.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Mapping, Optional

from . import coefficients as coef
from .championship import ChampionshipState, TEAM_DRIVERS

SPARES = "component_spares"


@dataclass(frozen=True)
class RaceStartConditions:
    race_index: int
    race_name: str
    grid_drop_positions: Dict[str, int]
    applied_to_grid: bool


def driver_team(driver: str) -> str:
    for team, drivers in TEAM_DRIVERS.items():
        if driver in drivers:
            return team
    raise ValueError("unknown driver")


def pool_key(driver: str, coeffs: Mapping[str, Any]) -> str:
    return SPARES if coeffs["allocation"]["free_units_are_shared_between_drivers"] else f"{SPARES}:{driver}"


def free_units(state: ChampionshipState, driver: str, coeffs: Mapping[str, Any]) -> int:
    return state.resource_inventory[driver_team(driver)][pool_key(driver, coeffs)]


def initial_inventory(coeffs: Mapping[str, Any]) -> Dict[str, Dict[str, int]]:
    units = coeffs["allocation"]["free_units_per_team"]
    inventory = {}
    for team, drivers in TEAM_DRIVERS.items():
        if coeffs["allocation"]["free_units_are_shared_between_drivers"]:
            inventory[team] = {SPARES: units}
        else:
            inventory[team] = {f"{SPARES}:{drivers[0]}": units - units // 2,
                               f"{SPARES}:{drivers[1]}": units // 2}
        inventory[team]["development_units"] = 100
        from . import pu_rules
        if pu_rules.enabled(coeffs):
            inventory[team].update(pu_rules.initial_stock())
    return inventory


def default_component_decisions(state: ChampionshipState) -> List[Dict[str, str]]:
    return [{"driver": driver, "component": component, "action": "USE"}
            for driver, components in state.power_units.items() for component in components]


def available_component_actions(state: ChampionshipState, driver: str,
                                coeffs: Mapping[str, Any] = coef.DEFAULT) -> Dict[str, List[str]]:
    if driver not in state.power_units:
        raise ValueError("unknown driver")
    limit = coef.max_wear_for_use(coeffs)
    from . import pu_rules
    if pu_rules.enabled(coeffs):  # opt-in 2.1.0: REPLACE needs team stock; without stock the element runs on
        inventory = state.resource_inventory[driver_team(driver)]
        out = {}
        for name, component in state.power_units[driver].items():
            stock = inventory.get(pu_rules.stock_key(name), 0) > 0
            out[name] = (["USE", "REPLACE"] if component.wear <= limit and stock else
                         ["REPLACE"] if stock else ["USE"])
        return out
    return {name: (["USE", "REPLACE"] if component.wear <= limit else ["REPLACE"])
            for name, component in state.power_units[driver].items()}


def replacement_cost(state: ChampionshipState, driver: str, component: str,
                     coeffs: Mapping[str, Any] = coef.DEFAULT, already_used: int = 0) -> Dict[str, Any]:
    """Public cost of replacing one component, given `already_used` units this race."""
    from . import pu_rules
    if pu_rules.enabled(coeffs):  # opt-in FIA-based rules (2.1.0)
        return pu_rules.public_cost(state, driver, component, state.resource_inventory[driver_team(driver)])
    if free_units(state, driver, coeffs) - already_used > 0:
        return {"uses_free_unit": True, "grid_drop": 0}
    return {"uses_free_unit": False, "grid_drop": coef.grid_drop(component, coeffs)}


def rival_component_decisions(state: ChampionshipState,
                              coeffs: Mapping[str, Any] = coef.DEFAULT) -> List[Dict[str, str]]:
    """Public threshold rule used by Orion, Nova and Vertex."""
    threshold = coeffs["rival_component_policy"]["threshold"]
    limit = coef.max_wear_for_use(coeffs)
    decisions = []
    for driver, components in state.power_units.items():
        if driver_team(driver) == "Apex":
            continue
        for name, component in components.items():
            replace = component.wear >= threshold or component.wear > limit
            decisions.append({"driver": driver, "component": name,
                              "action": "REPLACE" if replace else "USE"})
    return decisions


def prepare_race(state: ChampionshipState, decisions: Any,
                 coeffs: Mapping[str, Any] = coef.DEFAULT) -> RaceStartConditions:
    """Validate and atomically apply component choices before the current race."""
    state.validate()
    if state.race_index >= len(state.calendar):
        raise ValueError("championship is complete")
    if state.race_prepared:
        raise ValueError("current race is already prepared")
    clean = _validate_decisions(state, decisions)
    limit = coef.max_wear_for_use(coeffs)
    from . import pu_rules
    for driver, name, component, action in clean:
        if action == "USE" and component.wear > limit and not (
                pu_rules.enabled(coeffs) and "REPLACE" not in available_component_actions(state, driver, coeffs)[name]):
            raise ValueError(f"{driver} {name} is too worn to use")
    from . import pu_rules
    if pu_rules.enabled(coeffs):  # opt-in FIA-based rules (2.1.0): allocation, stock, B8.2.8 penalties
        pu_rules.apply_replacements(state, clean, driver_team)
        clean = []
    for driver, name, component, action in clean:
        if action != "REPLACE":
            continue
        key = pool_key(driver, coeffs)
        inventory = state.resource_inventory[driver_team(driver)]
        if inventory[key] > 0:
            inventory[key] -= 1
        else:
            state.grid_penalties[driver] += coef.grid_drop(name, coeffs)
        component.wear = 0.0
        component.replacements += 1
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
    if not state.race_prepared:
        raise ValueError("race has not been prepared")
    state.grid_penalties_applied = True
    return race_start_conditions(state)


def accrue_wear(state: ChampionshipState, coeffs: Mapping[str, Any] = coef.DEFAULT) -> None:
    stress = state.calendar[state.race_index].power_unit_stress
    for components in state.power_units.values():
        for name, component in components.items():
            component.wear = min(1.0, component.wear + coef.wear_increment(name, stress, coeffs))


def advance_without_result(state: ChampionshipState, coeffs: Mapping[str, Any] = coef.DEFAULT) -> None:
    """Planner helper: apply the action-independent part of a race transition."""
    if not state.race_prepared:
        raise ValueError("race has not been prepared")
    accrue_wear(state, coeffs)
    state.race_index += 1
    state.grid_penalties = {driver: 0 for driver in state.grid_penalties}
    state.race_prepared = False
    state.grid_penalties_applied = False


def complete_race(state: ChampionshipState, driver_points: Any,
                  coeffs: Mapping[str, Any] = coef.DEFAULT) -> ChampionshipState:
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
    for driver, points in driver_points.items():
        state.driver_points[driver] += points
    for team, drivers in TEAM_DRIVERS.items():
        state.team_points[team] += sum(driver_points[driver] for driver in drivers)
    advance_without_result(state, coeffs)
    state.validate()
    return state


def _validate_decisions(state: ChampionshipState, decisions: Any):
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
        clean.append((key[0], key[1], state.power_units[key[0]][key[1]], decision["action"]))
    if seen != expected:
        raise ValueError("every driver/component pair requires exactly one decision")
    return clean


# Backwards-compatible name used by P0 code paths.
def _driver_team(driver: str) -> str:
    return driver_team(driver)


SYNTHETIC_RULES = {
    "see": "fixtures/track_a_coefficients.json",
}
