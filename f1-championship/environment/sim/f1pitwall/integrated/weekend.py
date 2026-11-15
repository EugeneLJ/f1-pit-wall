"""C5 race weekend for the integrated session (opt-in benchmark 2.2.0, `IntegratedConfig.c5_weekend`).

Per race, after the component decision:

    COMPONENT_DECISION -> PRACTICE (session 1) -> PRACTICE (session 2) -> QUALIFYING -> RACE_STRATEGY x 14

The mechanics are the Track C C5 module (`track_c.c5`, contract docs/C5_INTERFACE_CONTRACT.md) used
unchanged. This file only owns what the contract assigns to the engine owner:

* the private weekend key, derived from the base seed and race index (never in any observation);
* one public C5 state per controlled team (public history only; replay recomputes every draw);
* sealed simultaneous PRACTICE / QUALIFYING actions with a published fallback;
* turning the qualifying order and the frozen parc-ferme setups into the race start:
  the provisional grid (then the existing grid-penalty rule), per-car long-run pace offsets and
  per-car degradation factors.

The true setup effects stay inside the trusted session: observations show only C5's public
estimates, the qualifying order and times, and each team's own frozen setups.
"""

from __future__ import annotations

import copy
import hashlib
from typing import Any, Dict, List, Optional

from ..championship import TEAM_DRIVERS
from ..championship_adapter import CHAMPIONSHIP_TO_ENGINE_DRIVER, car_performance
from ..championship_transition import driver_team

PRACTICE = "PRACTICE"
QUALIFYING = "QUALIFYING"
KEY_DOMAIN = "c5-weekend-key-v1"


def _c5():
    from track_c import c5  # Track C module; imported lazily so 2.0.1/2.1.0 never load it
    return c5


def weekend_key(base_seed: int, race_index: int) -> int:
    """Private per-race key for C5 draws (sha256, < 2**256). Never exposed."""
    return int.from_bytes(hashlib.sha256(f"{KEY_DOMAIN}|{base_seed}|{race_index}".encode()).digest(), "big")


def _seat(driver: str) -> str:
    return "driver_a" if driver.endswith(" A") else "driver_b"


class Weekend:
    """Owned by one IntegratedSession; holds the C5 state of the current race weekend."""

    def __init__(self, session: Any) -> None:
        self.s = session
        self.states: Dict[str, Dict[str, Any]] = {}
        self.history: List[Dict[str, Any]] = []  # one entry per completed weekend (public parts only)
        self._key: Optional[int] = None
        self.qualifying_result: Optional[Dict[str, Any]] = None
        self.setups: Dict[str, Dict[str, str]] = {}

    # ---------------------------------------------------------------- lifecycle
    def begin(self) -> None:
        """Called after the component decision of a race has been applied (race prepared, not started)."""
        c5, s = _c5(), self.s
        state = s.state
        track = state.calendar[state.race_index]
        self.weekend_id = f"r{state.race_index + 1}:{track.name}"
        self.archetype = track.archetype
        self._key = weekend_key(s._base_seed, state.race_index)
        model = c5.load_model(track.archetype)
        field = {d: {"team": driver_team(d), "driver_key": _seat(d),
                     "base_pace_sec": round(car_performance(state, d, s.coeffs)["pace"], 6)}
                 for d in state.power_units}
        self.states = {}
        for label, slot in s.slot_of.items():
            cars = {_seat(d): d for d in TEAM_DRIVERS[slot]}
            self.states[label] = c5.initial_public_state(model, weekend_id=self.weekend_id, team=slot,
                                                         car_ids=cars, field=field)
        self.qualifying_result, self.setups = None, {}

    def phase(self) -> str:
        phases = {st["phase"] for st in self.states.values()}
        if len(phases) != 1:
            raise RuntimeError("controlled teams are in different weekend phases")
        return phases.pop()

    # ---------------------------------------------------------------- actions
    def fallback_action(self, label: str, decision_type: str) -> Dict[str, Any]:
        """Published fallback: no practice laps; the neutral default setup, one qualifying run."""
        default = self.states[label]["model"]["default_setup_id"]
        if decision_type == PRACTICE:
            item = {"program": "SETUP_TEST", "setup_id": default, "laps": 0}
            return {"type": PRACTICE, "driver_a": dict(item), "driver_b": dict(item)}
        item = {"setup_id": default, "run_plan": "ONE_RUN"}
        return {"type": QUALIFYING, "driver_a": dict(item), "driver_b": dict(item)}

    def validate(self, label: str, decision_type: str, action: Dict[str, Any]) -> Dict[str, Any]:
        """Validate exactly as C5 does (on copies); return the clean action. Raises ValueError."""
        c5 = _c5()
        body = {k: copy.deepcopy(v) for k, v in action.items() if k != "consumed_reports"}
        if decision_type == PRACTICE:
            c5.simulate_practice(copy.deepcopy(self.states[label]), body, self._key)  # raises if illegal
        else:
            c5.core._clean_qualifying_action(self.states[label]["model"], body)
        return body

    def resolve(self, decision_type: str, actions: Dict[str, Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        """Apply one sealed tick. Returns the race-start weekend dict after QUALIFYING, else None."""
        c5, s = _c5(), self.s
        if decision_type == PRACTICE:
            for label in sorted(actions):
                self.states[label] = c5.simulate_practice(self.states[label], actions[label], self._key)["state"]
            return None
        by_team = {s.slot_of[label]: actions[label] for label in actions}
        any_state = self.states[sorted(self.states)[0]]
        result = c5.qualifying(any_state, by_team, self._key)
        self.qualifying_result = result
        pace_offset, deg_factor = {}, {}
        for label, slot in s.slot_of.items():
            choice = {d: actions[label][_seat(d)]["setup_id"] for d in TEAM_DRIVERS[slot]}
            self.setups[label] = {_seat(d): setup for d, setup in choice.items()}
            sealed = c5.make_parc_ferme_choice(choice, rng_key=self._key, weekend_id=self.weekend_id,
                                               archetype=self.archetype, team=slot)
            for driver, mod in c5.race_modifiers(sealed).items():
                engine_name = CHAMPIONSHIP_TO_ENGINE_DRIVER[driver]
                pace_offset[engine_name] = mod["pace_offset_sec_per_lap"]
                deg_factor[engine_name] = mod["deg_multiplier_factor"]
        self.history.append({"weekend_id": self.weekend_id, "qualifying_order": list(result["order"]),
                             "setups": copy.deepcopy(self.setups)})
        return {"grid": [CHAMPIONSHIP_TO_ENGINE_DRIVER[d] for d in result["order"]],
                "pace_offset": pace_offset, "deg_factor": deg_factor}

    # ---------------------------------------------------------------- observations
    def observation(self, label: str, decision_type: str) -> Dict[str, Any]:
        """Public C5 view for PRACTICE/QUALIFYING ticks, with public driver names."""
        c5, s = _c5(), self.s
        state = self.states[label]
        view = c5.public_observation(state)
        view["base_pace_sec"] = {s.public_driver(d): v for d, v in view["base_pace_sec"].items()}
        view["practice_history"] = [
            {"session_index": h["session_index"],
             "measurements": [{**m, "driver": m["driver"]} for m in h["measurements"]]}
            for h in state["practice"]["history"]]
        model = state["model"]
        setups = sorted(model["setups"])
        programs = sorted(model["noise_model"]["programs"])
        if decision_type == PRACTICE:
            budget = state["practice"]["laps_budget_remaining"]
            schema = {"type": PRACTICE,
                      "driver_a": {"program": "|".join(programs), "setup_id": "|".join(setups),
                                   "laps": f"integer 0..{budget['driver_a']}"},
                      "driver_b": {"program": "|".join(programs), "setup_id": "|".join(setups),
                                   "laps": f"integer 0..{budget['driver_b']}"},
                      "programs": {p: f"measures {model['noise_model']['programs'][p]['metric']}" for p in programs},
                      "format_example": {"type": PRACTICE,
                                         "driver_a": {"program": "QUALI_SIM", "setup_id": setups[0], "laps": 6},
                                         "driver_b": {"program": "LONG_RUN", "setup_id": setups[0], "laps": 6}}}
        else:
            schema = {"type": QUALIFYING,
                      "driver_a": {"setup_id": "|".join(setups), "run_plan": "ONE_RUN|TWO_RUN"},
                      "driver_b": {"setup_id": "|".join(setups), "run_plan": "ONE_RUN|TWO_RUN"},
                      "parc_ferme": "the qualifying setup of each car is fixed for the race",
                      "format_example": {"type": QUALIFYING,
                                         "driver_a": {"setup_id": setups[0], "run_plan": "TWO_RUN"},
                                         "driver_b": {"setup_id": setups[0], "run_plan": "ONE_RUN"}}}
        return {"weekend": view, "action_schema": schema}

    def race_observation(self, label: str) -> Optional[Dict[str, Any]]:
        """Public qualifying outcome shown during the race (no true setup effects)."""
        if self.qualifying_result is None:
            return None
        s = self.s
        return {"qualifying_order": [s.public_driver(d) for d in self.qualifying_result["order"]],
                "qualifying_times": {s.public_driver(d): t for d, t in self.qualifying_result["times"].items()},
                "own_parc_ferme_setups": copy.deepcopy(self.setups.get(label, {}))}
