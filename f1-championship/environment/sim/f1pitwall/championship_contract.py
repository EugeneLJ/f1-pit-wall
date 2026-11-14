"""Public observation/action contract for the deterministic championship."""

from __future__ import annotations

import copy
from typing import Any

from . import engine
from .championship import ChampionshipState, TEAM_DRIVERS, new_championship_state
from .championship_adapter import (
    ENGINE_TO_CHAMPIONSHIP_DRIVER,
    PreparedChampionshipRace,
    finish_prepared_race,
    start_prepared_race,
)
from .championship_transition import (
    available_component_actions,
    default_component_decisions,
    prepare_race,
)

COMPONENT_DECISION = "COMPONENT_DECISION"
RACE_STRATEGY = "RACE_STRATEGY"
CHAMPIONSHIP_COMPLETE = "CHAMPIONSHIP_COMPLETE"
CONTROLLED_DRIVERS = TEAM_DRIVERS["Apex"]


class ChampionshipSession:
    """Phase-ordered public API; hidden seeds and engine state never enter observations."""

    def __init__(self, state: ChampionshipState | None = None,
                 base_seed: int = engine.SEED) -> None:
        if isinstance(base_seed, bool) or not isinstance(base_seed, int):
            raise ValueError("base_seed must be an integer")
        self.state = copy.deepcopy(state if state is not None else new_championship_state())
        self.state.validate()
        if self.state.race_prepared:
            raise ValueError("session requires a state between races")
        self._base_seed = base_seed
        self._decision_type = (CHAMPIONSHIP_COMPLETE if self.state.race_index == len(self.state.calendar)
                               else COMPONENT_DECISION)
        self._active_race: PreparedChampionshipRace | None = None
        self._trace: list[dict[str, Any]] = []

    @property
    def decision_type(self) -> str:
        return self._decision_type

    def observation(self) -> dict[str, Any]:
        state = self.state
        team_standings = sorted(state.team_points.items(), key=lambda item: (-item[1], item[0]))
        driver_standings = sorted(state.driver_points.items(), key=lambda item: (-item[1], item[0]))
        common: dict[str, Any] = {
            "contract_version": 1,
            "decision_type": self._decision_type,
            "championship": {
                "race_index": state.race_index,
                "races_total": len(state.calendar),
                "team_standings": [{"team": team, "points": points}
                                   for team, points in team_standings],
                "driver_standings": [{"driver": driver, "points": points}
                                     for driver, points in driver_standings],
                "remaining_calendar": [
                    {"name": race.name, "archetype": race.archetype}
                    for race in state.calendar[state.race_index:]
                ],
            },
        }
        if self._decision_type == CHAMPIONSHIP_COMPLETE:
            common["race_progress"] = {"status": "CHAMPIONSHIP_COMPLETE"}
            common["action_schema"] = None
            return common

        track = state.calendar[state.race_index]
        common["current_track"] = {
            "name": track.name,
            "archetype": track.archetype,
            "power_unit_stress": track.power_unit_stress,
            "overtaking_difficulty": track.overtaking_difficulty,
            "tyre_degradation": track.tyre_degradation,
            "data_status": "synthetic_placeholder",
        }
        common["controlled_drivers"] = {
            driver: {
                "components": {
                    name: {
                        "wear": component.wear,
                        "replacements": component.replacements,
                        "legal_actions": available_component_actions(state, driver)[name],
                    }
                    for name, component in state.power_units[driver].items()
                }
            }
            for driver in CONTROLLED_DRIVERS
        }
        common["resource_inventory"] = copy.deepcopy(state.resource_inventory["Apex"])

        if self._decision_type == COMPONENT_DECISION:
            common["race_progress"] = {"status": "PRE_RACE", "completed_decisions": 0}
            common["action_schema"] = {
                "type": COMPONENT_DECISION,
                "decisions": "exactly one USE or REPLACE for each Apex driver/component pair",
            }
        else:
            if self._active_race is None:
                raise RuntimeError("race strategy phase has no active race")
            race_observation = _public_race_observation(self._active_race.race_state, track.name)
            common["race_progress"] = race_observation
            common["starting_grid"] = list(self._active_race.starting_grid)
            common["action_schema"] = {
                "type": RACE_STRATEGY,
                "driver_a": "PIT|STAY",
                "driver_b": "PIT|STAY",
            }
        return common

    def submit(self, action: Any) -> dict[str, Any]:
        before = self.observation()
        phase = self._decision_type
        race_before = self.state.race_index
        try:
            if phase == COMPONENT_DECISION:
                self._submit_component(action)
                result = None
            elif phase == RACE_STRATEGY:
                result = self._submit_race_strategy(action)
            else:
                raise ValueError("championship is already complete")
        except ValueError as exc:
            self._trace.append({
                "sequence": len(self._trace) + 1,
                "decision_type": phase,
                "observation": before,
                "action": copy.deepcopy(action),
                "validation": {"valid": False, "error": str(exc)},
                "state_transition": None,
            })
            raise

        after = self.observation()
        transition: dict[str, Any] = {
            "race_index_before": race_before,
            "race_index_after": self.state.race_index,
            "decision_type_before": phase,
            "decision_type_after": self._decision_type,
        }
        if result is not None:
            transition["awarded_points"] = copy.deepcopy(result.awarded_points)
            transition["classification"] = copy.deepcopy(result.race_result["classification"])
        self._trace.append({
            "sequence": len(self._trace) + 1,
            "decision_type": phase,
            "observation": before,
            "action": copy.deepcopy(action),
            "validation": {"valid": True},
            "state_transition": transition,
            "next_observation": after,
        })
        return after

    def trace(self) -> list[dict[str, Any]]:
        return copy.deepcopy(self._trace)

    def _submit_component(self, action: Any) -> None:
        decisions = _validate_public_component_action(self.state, action)
        working = copy.deepcopy(self.state)
        full_decisions = default_component_decisions(working)
        requested = {(item["driver"], item["component"]): item["action"] for item in decisions}
        for item in full_decisions:
            key = (item["driver"], item["component"])
            if key in requested:
                item["action"] = requested[key]
        prepare_race(working, full_decisions)
        active = start_prepared_race(working, self._base_seed + working.race_index)
        self.state = working
        self._active_race = active
        self._decision_type = RACE_STRATEGY

    def _submit_race_strategy(self, action: Any):
        if not isinstance(action, dict) or set(action) != {"type", "driver_a", "driver_b"}:
            raise ValueError("race strategy action must contain type and both drivers")
        if action["type"] != RACE_STRATEGY:
            raise ValueError("action type does not match current decision")
        clean = engine.validate_action({"driver_a": action["driver_a"],
                                        "driver_b": action["driver_b"]})
        if self._active_race is None:
            raise ValueError("no active race")
        engine.step(self._active_race.race_state, clean)
        if not self._active_race.race_state["complete"]:
            return None
        result = finish_prepared_race(self.state, self._active_race)
        self._active_race = None
        self._decision_type = (CHAMPIONSHIP_COMPLETE
                               if self.state.race_index == len(self.state.calendar)
                               else COMPONENT_DECISION)
        return result


def _validate_public_component_action(
    state: ChampionshipState, action: Any,
) -> list[dict[str, str]]:
    if not isinstance(action, dict) or set(action) != {"type", "decisions"}:
        raise ValueError("component action must contain only type and decisions")
    if action["type"] != COMPONENT_DECISION:
        raise ValueError("action type does not match current decision")
    if not isinstance(action["decisions"], list):
        raise ValueError("component decisions must be a list")
    expected = {(driver, component) for driver in CONTROLLED_DRIVERS
                for component in state.power_units[driver]}
    seen = set()
    clean = []
    for item in action["decisions"]:
        if not isinstance(item, dict) or set(item) != {"driver", "component", "action"}:
            raise ValueError("each component decision requires driver, component, and action")
        key = (item["driver"], item["component"])
        if key not in expected:
            raise ValueError("component decision is not controllable or does not exist")
        if key in seen:
            raise ValueError("duplicate component decision")
        if item["action"] not in available_component_actions(state, item["driver"])[item["component"]]:
            raise ValueError("component action is not currently legal")
        seen.add(key)
        clean.append(dict(item))
    if seen != expected:
        raise ValueError("every Apex driver/component pair requires exactly one decision")
    return clean


def _public_race_observation(race_state: dict[str, Any], race_name: str) -> dict[str, Any]:
    value = copy.deepcopy(engine.observation(race_state))
    value["race"] = race_name
    value.pop("future_track_status", None)
    for entry in value.get("classification", []):
        entry["driver"] = ENGINE_TO_CHAMPIONSHIP_DRIVER[entry["driver"]]
    return value
