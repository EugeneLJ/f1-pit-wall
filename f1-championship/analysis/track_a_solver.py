"""Exact Track A solver for short (e.g. final-3-race) seasons.

What is exact here:
  * Expected Apex points of a race are computed exactly over every SC/VSC/GREEN
    path (published probabilities) and every retirement outcome (independent,
    published per-car probabilities -> Poisson-binomial over cars ahead).
  * Season value is an exact dynamic program over Apex component decisions.
    Wear evolution never depends on race events, so the season transition is
    deterministic given the component plan and expectations add across races.

What is fixed: in-race PIT/STAY play uses one public baseline race policy for
every component policy compared, so differences isolate Track A decisions.

Information: the fair planner reads only public quantities: Apex state, the
public rival rule applied to public history, track parameters, published
probabilities and formulas. It never reads seeds or future events.

The hindsight oracle is a separate diagnostic: it knows the realized SC/VSC
schedule and retirement draws of a given seed and optimizes component AND race
decisions. Because retirement depends on wear, its outcomes are recomputed from
the same action-independent draws for every candidate action sequence.
"""

from __future__ import annotations

import copy
import itertools
import json
import sys
from functools import lru_cache
from pathlib import Path
from typing import Any, Callable, Dict, List, Mapping, Optional, Tuple

TASK = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TASK / "src"))
sys.path.insert(0, str(TASK / "solution"))

from f1pitwall import coefficients as coef  # noqa: E402
from f1pitwall import engine  # noqa: E402
from f1pitwall.championship import ChampionshipState, TEAM_DRIVERS  # noqa: E402
from f1pitwall.championship_adapter import start_prepared_race  # noqa: E402
from f1pitwall.championship_transition import (  # noqa: E402
    advance_without_result,
    available_component_actions,
    prepare_race,
    rival_component_decisions,
)
from play import race_action as _public_race_action  # noqa: E402

APEX = TEAM_DRIVERS["Apex"]
COMPONENTS = coef.COMPONENTS
EVENT_PROBS = (("GREEN", 0.60), ("VSC", 0.25), ("SC", 0.15))
RACE_ACTIONS = [{"driver_a": a, "driver_b": b} for a in ("PIT", "STAY") for b in ("PIT", "STAY")]  # legacy races only


def baseline_race_action(engine_observation: Dict[str, Any]) -> Dict[str, str]:
    """The public P0 heuristic (solution/play.py) applied to an engine observation."""
    action = _public_race_action({"race_progress": engine_observation})
    return {"driver_a": action["driver_a"], "driver_b": action["driver_b"]}


# ----------------------------------------------------------------- race level

def _copy_race(race: Dict[str, Any]) -> Dict[str, Any]:
    out = dict(race)
    out["cars"] = [{**car, "compounds_used": list(car["compounds_used"])} if "compounds_used" in car else dict(car)
                   for car in race["cars"]]
    out["events"] = list(race["events"])
    out["actions"] = list(race["actions"])
    return out


def expected_apex_points_at_finish(race: Dict[str, Any]) -> float:
    """Exact expectation over independent retirements given the running order."""
    order = sorted(race["cars"], key=lambda car: (car["elapsed"] + engine.finish_penalty(race, car), car["name"]))
    p_dnf = race["config"]["dnf_prob"]
    total = 0.0
    for index, car in enumerate(order):
        if car["team"] != "Apex":
            continue
        dist = [1.0]  # distribution of number of cars ahead that finish
        for ahead in order[:index]:
            q = 1.0 - p_dnf[ahead["name"]]
            nxt = [0.0] * (len(dist) + 1)
            for k, mass in enumerate(dist):
                nxt[k] += mass * (1.0 - q)
                nxt[k + 1] += mass * q
            dist = nxt
        total += (1.0 - p_dnf[car["name"]]) * sum(mass * engine.POINTS[k] for k, mass in enumerate(dist))
    return total


def realized_apex_points(race: Dict[str, Any]) -> int:
    return engine.result(race)["constructors_points"]


def prepared_race_state(prepared: ChampionshipState, coeffs, events: Optional[List[str]] = None,
                        seed: int = 0) -> Dict[str, Any]:
    working = copy.deepcopy(prepared)
    count = len(engine.DECISION_LAPS)
    active = start_prepared_race(working, seed, coeffs, events=events or ["GREEN"] * count)
    return active.race_state


def expected_race_value(race: Dict[str, Any],
                        race_policy: Callable[[Dict[str, Any]], Dict[str, str]] = baseline_race_action) -> float:
    """Exact expectation over the per-decision SC/VSC/GREEN tree under race_policy."""
    if race["step"] == len(race["events"]):
        return expected_apex_points_at_finish(race)
    total = 0.0
    for status, prob in EVENT_PROBS:
        branch = _copy_race(race)
        branch["events"][branch["step"]] = status
        engine.step(branch, race_policy(engine.observation(branch)))
        total += prob * expected_race_value(branch, race_policy)
    return total


def hindsight_race_value(race: Dict[str, Any]) -> Tuple[int, List[Dict[str, str]]]:
    """Best realized points over every PIT/STAY sequence for the known events and draws."""
    if race["step"] == len(race["events"]):
        return realized_apex_points(race), []
    best = (-1, [])
    legal = engine.legal_actions(race)
    for action in ({"driver_a": a, "driver_b": b} for a in legal for b in legal):
        branch = _copy_race(race)
        engine.step(branch, action)
        value, rest = hindsight_race_value(branch)
        if value > best[0]:
            best = (value, [action] + rest)
    return best


def realized_race_value(race: Dict[str, Any],
                        race_policy: Callable[[Dict[str, Any]], Dict[str, str]] = baseline_race_action) -> int:
    branch = _copy_race(race)
    while branch["step"] < len(branch["events"]):
        engine.step(branch, race_policy(engine.observation(branch)))
    return realized_apex_points(branch)


# --------------------------------------------------------------- season level

def apex_options(state: ChampionshipState, coeffs, prune: bool = True) -> List[Tuple[Tuple[str, str, str], ...]]:
    """All joint Apex component choices. REPLACE of an unworn part is pruned (weakly dominated)."""
    per_pair = []
    for driver in APEX:
        legal = available_component_actions(state, driver, coeffs)
        for name in COMPONENTS:
            actions = list(legal[name])
            if prune and state.power_units[driver][name].wear == 0.0 and "USE" in actions:
                actions = ["USE"]
            per_pair.append([(driver, name, action) for action in actions])
    return list(itertools.product(*per_pair))


def decisions_for(state: ChampionshipState, option, coeffs) -> List[Dict[str, str]]:
    apex = [{"driver": d, "component": c, "action": a} for d, c, a in option]
    return apex + rival_component_decisions(state, coeffs)


def prepare(state: ChampionshipState, option, coeffs) -> ChampionshipState:
    working = copy.deepcopy(state)
    prepare_race(working, decisions_for(state, option, coeffs), coeffs)
    return working


def after_race(prepared: ChampionshipState, coeffs) -> ChampionshipState:
    working = copy.deepcopy(prepared)
    advance_without_result(working, coeffs)
    return working


def state_key(state: ChampionshipState) -> str:
    return json.dumps({
        "race": state.race_index,
        "cal": [[r.archetype, r.power_unit_stress, r.overtaking_difficulty, r.tyre_degradation]
                for r in state.calendar],
        "wear": {d: {c: round(v.wear, 9) for c, v in comps.items()} for d, comps in state.power_units.items()},
        "inv": state.resource_inventory,
        "pen": state.grid_penalties,
        "prep": state.race_prepared,
    }, sort_keys=True)


def race_key(prepared: ChampionshipState) -> str:
    """A race's expected value depends only on the current track and the prepared car state."""
    track = prepared.calendar[prepared.race_index]
    return json.dumps({
        "track": [track.archetype, track.power_unit_stress, track.overtaking_difficulty, track.tyre_degradation],
        "wear": {d: {c: round(v.wear, 9) for c, v in comps.items()} for d, comps in prepared.power_units.items()},
        "pen": prepared.grid_penalties,
    }, sort_keys=True)


def option_label(option) -> str:
    replaced = [f"{d[-1]}:{c}" for d, c, a in option if a == "REPLACE"]
    return "+".join(replaced) if replaced else "USE-all"


class Solver:
    """Memoized exact expected values; one instance per coefficient set."""

    def __init__(self, coeffs: Mapping[str, Any] = coef.DEFAULT):
        self.coeffs = coeffs
        self._race_cache: Dict[str, float] = {}
        self._value_cache: Dict[str, Tuple[float, Any]] = {}
        self.race_evaluations = 0

    def race_value(self, prepared: ChampionshipState) -> float:
        key = race_key(prepared)
        if key not in self._race_cache:
            self.race_evaluations += 1
            self._race_cache[key] = expected_race_value(prepared_race_state(prepared, self.coeffs))
        return self._race_cache[key]

    def option_values(self, state: ChampionshipState) -> List[Tuple[float, float, Any]]:
        """(total value, this-race value, option) for every option at this state."""
        out = []
        for option in apex_options(state, self.coeffs):
            prepared = prepare(state, option, self.coeffs)
            now = self.race_value(prepared)
            out.append((now + self.optimal(after_race(prepared, self.coeffs))[0], now, option))
        return out

    def optimal(self, state: ChampionshipState) -> Tuple[float, Any]:
        """Max expected remaining Apex points and the best first option."""
        if state.race_index >= len(state.calendar):
            return 0.0, None
        key = state_key(state)
        if key not in self._value_cache:
            values = self.option_values(state)
            best = max(values, key=lambda item: (round(item[0], 9), -_replacements(item[2])))
            self._value_cache[key] = (best[0], best[2])
        return self._value_cache[key]

    # Fixed component policies, evaluated exactly with the same machinery.
    def evaluate(self, state: ChampionshipState, policy: str) -> float:
        if state.race_index >= len(state.calendar):
            return 0.0
        if policy == "optimal":
            return self.optimal(state)[0]
        option = self.choose(state, policy)
        prepared = prepare(state, option, self.coeffs)
        return self.race_value(prepared) + self.evaluate(after_race(prepared, self.coeffs), policy)

    def choose(self, state: ChampionshipState, policy: str):
        if policy == "optimal":
            return self.optimal(state)[1]
        if policy == "always_use":
            return tuple((d, c, "USE" if "USE" in available_component_actions(state, d, self.coeffs)[c]
                          else "REPLACE") for d in APEX for c in COMPONENTS)
        if policy == "rival_rule":
            threshold = self.coeffs["rival_component_policy"]["threshold"]
            limit = coef.max_wear_for_use(self.coeffs)
            return tuple((d, c, "REPLACE" if (state.power_units[d][c].wear >= threshold
                                              or state.power_units[d][c].wear > limit) else "USE")
                         for d in APEX for c in COMPONENTS)
        if policy == "greedy":
            scored = [(self.race_value(prepare(state, option, self.coeffs)), option)
                      for option in apex_options(state, self.coeffs)]
            return max(scored, key=lambda item: (round(item[0], 9), -_replacements(item[1])))[1]
        raise ValueError(policy)

    # Hindsight diagnostic for one seed.
    def hindsight(self, state: ChampionshipState, base_seed: int) -> float:
        if state.race_index >= len(state.calendar):
            return 0.0
        cache = self._value_cache
        key = f"H{base_seed}:{state_key(state)}"
        if key in cache:
            return cache[key][0]
        best = -1.0
        for option in apex_options(state, self.coeffs, prune=False):
            prepared = prepare(state, option, self.coeffs)
            race = self._seeded_race(prepared, base_seed)
            value = hindsight_race_value(race)[0] + self.hindsight(after_race(prepared, self.coeffs), base_seed)
            best = max(best, value)
        cache[key] = (best, None)
        return best

    def realized(self, state: ChampionshipState, policy: str, base_seed: int) -> int:
        """Realized points of a fair policy on one seed (same draws as the session)."""
        total = 0
        while state.race_index < len(state.calendar):
            prepared = prepare(state, self.choose(state, policy), self.coeffs)
            total += realized_race_value(self._seeded_race(prepared, base_seed))
            state = after_race(prepared, self.coeffs)
        return total

    def _seeded_race(self, prepared: ChampionshipState, base_seed: int) -> Dict[str, Any]:
        seed = base_seed + prepared.race_index
        events = engine._event_schedule(seed, len(engine.DECISION_LAPS))
        return prepared_race_state(prepared, self.coeffs, events=events, seed=seed)


def _replacements(option) -> int:
    return sum(1 for _, _, action in option if action == "REPLACE")
