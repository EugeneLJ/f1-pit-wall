"""Opt-in FIA-2026-based power-unit penalty rules (benchmark 2.1.0, B8). Default rules unchanged.

Enabled only by `coeffs["pu_rules"] == "fia2026_scaled"` (see `with_fia_pu_rules`). Kept apart:
  regulatory allocation   per driver and element type (B8.2.2/B8.2.3, scaled to 8 races: SYNTHETIC)
  team physical stock     new elements a team can fit (SYNTHETIC logistics)
  replacement decision    USE / REPLACE per element (unchanged action space)
  penalty calculation     10 places for the first additional element of a type, 5 afterwards,
                          cumulative within the event (B8.2.8, verified)
  grid application        B2.5.4b: temporary slots for <= 15 places, back of grid above 15 (verified)
"""

from __future__ import annotations

import copy
import json
import math
from pathlib import Path
from typing import Any, Dict, List, Mapping

FIA_MODE = "fia2026_scaled"
FIXTURE = Path(__file__).with_name("fixtures") / "pu_rules_fia2026.json"
STOCK_PREFIX = "stock:"


def load() -> Dict[str, Any]:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


RULES = load()


def enabled(coeffs: Mapping[str, Any]) -> bool:
    return coeffs.get("pu_rules") == FIA_MODE


def with_fia_pu_rules(coeffs: Mapping[str, Any]) -> Dict[str, Any]:
    out = copy.deepcopy(dict(coeffs))
    out["pu_rules"] = FIA_MODE
    return out


def allocation(component: str) -> int:
    return RULES["synthetic"]["allocation_per_driver"][component]


def scaled_places_check() -> Dict[str, int]:
    v, f = RULES["verified_rules_used"], RULES["synthetic"]["field_size_scaling"]
    k = f["model_field"] / f["real_field"]
    return {"first_additional_element": round(v["first_additional_element_places"] * k),
            "subsequent_additional_element": round(v["subsequent_additional_element_places"] * k),
            "back_of_grid_above": round(v["back_of_grid_above_places"] * k)}


def scaled_allocation_check() -> Dict[str, int]:
    """Recompute the documented scaling (guards the fixture against silent edits)."""
    real = RULES["synthetic"]["real_2026_allocation_with_B8.2.3"]
    return {k: 1 + math.ceil((v - 1) * 8 / 24) for k, v in real.items()}


def elements_used(state, driver: str, component: str) -> int:
    """Elements of this type used so far this season (the starting element counts)."""
    return 1 + state.power_units[driver][component].replacements


def element_penalty(used_after: int, component: str) -> int:
    """Grid places for introducing element number `used_after` of this type (B8.2.8)."""
    extra = used_after - allocation(component)
    if extra <= 0:
        return 0
    v = RULES["synthetic"]["field_size_scaling"]["places"]  # FIA 10/5 scaled to the 8-car field
    return v["first_additional_element"] if extra == 1 else v["subsequent_additional_element"]


def penalty_for(state, driver: str, components: List[str]) -> int:
    """Cumulative places if `driver` replaces all of `components` at the current event."""
    total = 0
    for name in components:
        total += element_penalty(elements_used(state, driver, name) + 1, name)
    return total


def stock_key(component: str) -> str:
    return f"{STOCK_PREFIX}{component}"


def initial_stock() -> Dict[str, int]:
    return {stock_key(k): v for k, v in RULES["synthetic"]["team_physical_stock_per_type"].items()}


def public_cost(state, driver: str, component: str, team_inventory: Mapping[str, int]) -> Dict[str, Any]:
    used = elements_used(state, driver, component)
    return {"rules": FIA_MODE, "allocation_per_driver": allocation(component), "elements_used": used,
            "grid_places_if_replaced": element_penalty(used + 1, component),
            "team_stock_remaining": team_inventory.get(stock_key(component), 0),
            "note": "places from several replacements at one event add up; above 15 the driver starts behind all others"}


def check_team_stock(state, team: str, replacements: Mapping[str, int]) -> None:
    """Joint constraint: a team's REPLACE count per type at one event must not exceed its stock."""
    for name, count in replacements.items():
        if state.resource_inventory[team].get(stock_key(name), 0) < count:
            raise ValueError(f"{team} has only {state.resource_inventory[team].get(stock_key(name), 0)} "
                             f"{name} in stock for {count} replacements")


def apply_replacements(state, clean, team_of) -> None:
    """Penalty calculation + stock use for validated decisions (called by prepare_race)."""
    per_team = {}
    for driver, name, component, action in clean:
        if action == "REPLACE":
            per_team.setdefault((team_of(driver), name), 0)
            per_team[(team_of(driver), name)] += 1
    for (team, name), count in per_team.items():
        if state.resource_inventory[team].get(stock_key(name), 0) < count:
            raise ValueError(f"{team} has no {name} left in stock")
    for driver, name, component, action in clean:
        if action != "REPLACE":
            continue
        state.grid_penalties[driver] += element_penalty(elements_used(state, driver, name) + 1, name)
        state.resource_inventory[team_of(driver)][stock_key(name)] -= 1
        component.wear = 0.0
        component.replacements += 1


def fia_grid(qualifying: List[str], penalties: Mapping[str, int]) -> List[str]:
    """B2.5.4b grid formation for one race. `qualifying` is the order P1..Pn."""
    limit = RULES["synthetic"]["field_size_scaling"]["places"]["back_of_grid_above"]  # FIA 15, scaled
    qpos = {d: i + 1 for i, d in enumerate(qualifying)}
    small = [d for d in qualifying if 0 < penalties.get(d, 0) <= limit]
    big = [d for d in qualifying if penalties.get(d, 0) > limit]
    clean = [d for d in qualifying if penalties.get(d, 0) == 0]
    temp: Dict[int, str] = {}
    for d in sorted(small, key=lambda x: -qpos[x]):  # slowest keeps its slot; others go ahead
        slot = qpos[d] + penalties[d]
        while slot in temp:
            slot -= 1
        temp[slot] = d
    slots = dict(temp)
    free = (p for p in range(1, len(qualifying) + len(small) + 1) if p not in slots)
    for d in clean:  # unpenalised fill unoccupied slots in qualifying order
        slots[next(free)] = d
    order = [slots[p] for p in sorted(slots)]  # penalised move up to fill gaps
    return order + big  # > limit: behind all others, in qualifying order
