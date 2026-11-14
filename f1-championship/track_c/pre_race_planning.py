"""Synthetic Practice -> Qualifying planning environment for C5.

The module is independent of the authoritative race engine.  A trusted host samples
all latent conditions and potential test signals before the first action.  Public
observations contain beliefs and performed-test evidence, never latent truth or
unperformed potential outcomes.
"""

from __future__ import annotations

import copy
import hashlib
import json
import math
import random
from dataclasses import dataclass
from typing import Any

CONTRACT_VERSION = 1
MODEL_VERSION = "c5-synthetic-1"
PRACTICE, QUALIFYING, COMPLETE = "PRACTICE", "QUALIFYING", "COMPLETE"
TESTS = {
    "QUALIFYING_PACE_RUN": {"cost": 1, "factor": "qualifying_grip", "resource_cost": 0.010},
    "LONG_RUN_DEGRADATION": {"cost": 2, "factor": "tyre_degradation", "resource_cost": 0.025},
    "SETUP_COMPARISON": {"cost": 1, "factor": "driver_preference", "resource_cost": 0.012},
}
SETUPS = ("QUALIFYING_BIASED", "BALANCED", "RACE_BIASED")
DRIVERS = ("driver_a", "driver_b")
LEVELS = (-1, 0, 1)
LEVEL_NAMES = {-1: "LOW", 0: "NOMINAL", 1: "HIGH"}
PREFERENCE_NAMES = {-1: "RACE_BIASED", 0: "BALANCED", 1: "QUALIFYING_BIASED"}

TRACKS = {
    "STREET": {"qualifying_weight": 1.35, "race_weight": 0.85, "degradation_weight": 0.65},
    "BALANCED": {"qualifying_weight": 1.0, "race_weight": 1.0, "degradation_weight": 1.0},
    "HIGH_DEGRADATION": {"qualifying_weight": 0.70, "race_weight": 1.15, "degradation_weight": 1.45},
}


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _hash(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode()).hexdigest()


def _seed_id(seed: int) -> str:
    return hashlib.sha256(f"c5-pre-race:{seed}".encode()).hexdigest()[:16]


@dataclass(frozen=True)
class PreRaceConfig:
    track_archetype: str = "BALANCED"
    practice_budget: int = 3
    test_accuracy: float = 0.75

    def validate(self) -> None:
        if self.track_archetype not in TRACKS:
            raise ValueError("unknown track archetype")
        if isinstance(self.practice_budget, bool) or not 1 <= self.practice_budget <= 5:
            raise ValueError("practice budget must be between 1 and 5")
        if not 0.5 < self.test_accuracy < 1.0:
            raise ValueError("test accuracy must be between 0.5 and 1")

    def as_dict(self) -> dict[str, Any]:
        return {"track_archetype": self.track_archetype, "practice_budget": self.practice_budget,
                "test_accuracy": self.test_accuracy, "data_status": "synthetic_placeholder_not_FIA_calibrated"}


class PreRaceSession:
    """Deterministic given config, seed, and action sequence."""

    def __init__(self, config: PreRaceConfig, seed: int) -> None:
        config.validate()
        if isinstance(seed, bool) or not isinstance(seed, int):
            raise ValueError("seed must be an integer")
        self.config = config
        self._seed = seed
        rng = random.Random(f"c5|{seed}|{_canonical(config.as_dict())}")
        # Sampled before any action.  These values never appear in public observations.
        self._truth = {
            "qualifying_grip": rng.choice(LEVELS),
            "tyre_degradation": rng.choice(LEVELS),
            "driver_preference": {driver: rng.choice(LEVELS) for driver in DRIVERS},
        }
        self._potential_signals = {
            (test, driver): self._draw_signal(rng, spec["factor"], driver)
            for test, spec in TESTS.items()
            for driver in (DRIVERS if test == "SETUP_COMPARISON" else (None,))
        }
        self.stage = PRACTICE
        self.remaining_budget = config.practice_budget
        self.performed: list[dict[str, Any]] = []
        self._performed_keys: set[tuple[str, str | None]] = set()
        self._beliefs = {
            "qualifying_grip": {level: 1 / 3 for level in LEVELS},
            "tyre_degradation": {level: 1 / 3 for level in LEVELS},
            "driver_preference": {driver: {level: 1 / 3 for level in LEVELS} for driver in DRIVERS},
        }
        self.resource_cost = 0.0
        self.qualifying_result: dict[str, Any] | None = None
        self.trace: list[dict[str, Any]] = []

    def _draw_signal(self, rng: random.Random, factor: str, driver: str | None) -> int:
        truth = self._truth[factor][driver] if factor == "driver_preference" else self._truth[factor]
        if rng.random() < self.config.test_accuracy:
            return truth
        return rng.choice([level for level in LEVELS if level != truth])

    def observation(self) -> dict[str, Any]:
        obs = {
            "contract_version": CONTRACT_VERSION, "model_version": MODEL_VERSION,
            "stage": self.stage,
            "track": {"archetype": self.config.track_archetype, **TRACKS[self.config.track_archetype],
                      "data_status": "synthetic_placeholder_not_FIA_calibrated"},
            "information_boundary": {
                "latent_conditions_visible": False, "unperformed_test_outcomes_visible": False,
                "future_race_events_visible": False,
            },
        }
        if self.stage == PRACTICE:
            obs.update({"remaining_testing_budget": self.remaining_budget,
                        "performed_tests": copy.deepcopy(self.performed),
                        "beliefs": self._public_beliefs(),
                        "available_tests": self._available_tests(),
                        "action_schema": {
                            "RUN_TEST": {"type": "RUN_TEST", "test": sorted(TESTS),
                                         "driver": "required only for SETUP_COMPARISON"},
                            "END_PRACTICE": {"type": "END_PRACTICE"},
                        }})
        elif self.stage == QUALIFYING:
            obs.update({"practice_summary": {"performed_tests": copy.deepcopy(self.performed),
                                               "resource_cost": round(self.resource_cost, 6)},
                        "beliefs": self._public_beliefs(),
                        "action_schema": {"type": "SELECT_SETUPS",
                                          "driver_a": list(SETUPS), "driver_b": list(SETUPS)},
                        "setup_tradeoffs": setup_tradeoffs(self.config.track_archetype)})
        else:
            obs.update({"qualifying": copy.deepcopy(self.qualifying_result), "action_schema": None})
        return obs

    def submit(self, action: dict[str, Any]) -> dict[str, Any]:
        before = self.observation()
        if self.stage == COMPLETE:
            raise ValueError("pre-race session is complete")
        if self.stage == PRACTICE:
            result = self._practice_action(action)
        else:
            result = self._qualifying_action(action)
        after = self.observation()
        self.trace.append({"seq": len(self.trace) + 1, "stage": before["stage"],
                           "observation_hash": _hash(before), "action": copy.deepcopy(action),
                           "action_hash": _hash(action), "result": copy.deepcopy(result),
                           "next_observation_hash": _hash(after)})
        return result

    def _practice_action(self, action: Any) -> dict[str, Any]:
        if not isinstance(action, dict) or action.get("type") not in {"RUN_TEST", "END_PRACTICE"}:
            raise ValueError("invalid Practice action")
        if action["type"] == "END_PRACTICE":
            if set(action) != {"type"}:
                raise ValueError("END_PRACTICE has no additional fields")
            self.stage = QUALIFYING
            return {"status": "PRACTICE_COMPLETE"}
        if set(action) - {"type", "test", "driver"}:
            raise ValueError("RUN_TEST has unknown fields")
        test = action.get("test")
        if test not in TESTS:
            raise ValueError("unknown Practice test")
        driver = action.get("driver")
        if test == "SETUP_COMPARISON" and driver not in DRIVERS:
            raise ValueError("SETUP_COMPARISON requires driver_a or driver_b")
        if test != "SETUP_COMPARISON" and driver is not None:
            raise ValueError("driver is only valid for SETUP_COMPARISON")
        key = (test, driver)
        if key in self._performed_keys:
            raise ValueError("Practice test already performed")
        cost = TESTS[test]["cost"]
        if cost > self.remaining_budget:
            raise ValueError("insufficient Practice testing budget")
        signal = self._potential_signals[key]
        factor = TESTS[test]["factor"]
        belief = self._beliefs[factor][driver] if factor == "driver_preference" else self._beliefs[factor]
        if factor == "driver_preference":
            self._beliefs[factor][driver] = _bayes_update(belief, signal, self.config.test_accuracy)
        else:
            self._beliefs[factor] = _bayes_update(belief, signal, self.config.test_accuracy)
        self.remaining_budget -= cost
        self.resource_cost += TESTS[test]["resource_cost"]
        public_signal = PREFERENCE_NAMES[signal] if factor == "driver_preference" else LEVEL_NAMES[signal]
        record = {"test": test, "driver": driver, "budget_cost": cost,
                  "race_resource_cost": TESTS[test]["resource_cost"], "signal": public_signal,
                  "measurement_accuracy": self.config.test_accuracy,
                  "calibration": "synthetic_placeholder"}
        self.performed.append(record)
        self._performed_keys.add(key)
        return copy.deepcopy(record)

    def _qualifying_action(self, action: Any) -> dict[str, Any]:
        if (not isinstance(action, dict) or set(action) != {"type", "driver_a", "driver_b"}
                or action.get("type") != "SELECT_SETUPS"
                or any(action.get(driver) not in SETUPS for driver in DRIVERS)):
            raise ValueError("invalid Qualifying setup action")
        result = qualifying_outcome(self.config, self._truth, action, self.resource_cost)
        self.qualifying_result = result
        self.stage = COMPLETE
        return copy.deepcopy(result)

    def _available_tests(self) -> list[dict[str, Any]]:
        rows = []
        for test, spec in TESTS.items():
            for driver in (DRIVERS if test == "SETUP_COMPARISON" else (None,)):
                key = (test, driver)
                if key not in self._performed_keys and spec["cost"] <= self.remaining_budget:
                    rows.append({"test": test, "driver": driver, "budget_cost": spec["cost"],
                                 "race_resource_cost": spec["resource_cost"],
                                 "measurement_accuracy": self.config.test_accuracy})
        return rows

    def _public_beliefs(self) -> dict[str, Any]:
        return {
            "qualifying_grip": _belief_summary(self._beliefs["qualifying_grip"], LEVEL_NAMES),
            "tyre_degradation": _belief_summary(self._beliefs["tyre_degradation"], LEVEL_NAMES),
            "driver_preference": {driver: _belief_summary(self._beliefs["driver_preference"][driver],
                                                            PREFERENCE_NAMES) for driver in DRIVERS},
        }

    def replay_metadata(self) -> dict[str, Any]:
        return {"replay_version": 1, "contract_version": CONTRACT_VERSION,
                "model_version": MODEL_VERSION, "config": self.config.as_dict(),
                "seed_id": _seed_id(self._seed), "trace": copy.deepcopy(self.trace),
                "trace_hash": _hash(self.trace)}


def _bayes_update(prior: dict[int, float], signal: int, accuracy: float) -> dict[int, float]:
    likelihood = {level: accuracy if level == signal else (1 - accuracy) / 2 for level in LEVELS}
    raw = {level: prior[level] * likelihood[level] for level in LEVELS}
    total = sum(raw.values())
    return {level: raw[level] / total for level in LEVELS}


def _belief_summary(belief: dict[int, float], names: dict[int, str]) -> dict[str, Any]:
    mean = sum(level * p for level, p in belief.items())
    variance = sum(p * (level - mean) ** 2 for level, p in belief.items())
    return {"probabilities": {names[level]: round(belief[level], 6) for level in LEVELS},
            "mean": round(mean, 6), "stddev": round(math.sqrt(variance), 6),
            "uncertainty_kind": "synthetic_discrete_posterior"}


def setup_tradeoffs(track: str) -> dict[str, Any]:
    profile = TRACKS[track]
    return {
        "QUALIFYING_BIASED": {"qualifying_lap_delta_s": round(-0.22 * profile["qualifying_weight"], 4),
                              "race_pace_delta_s_per_lap": round(0.12 * profile["race_weight"], 4),
                              "tyre_degradation_multiplier_delta": round(0.05 * profile["degradation_weight"], 4)},
        "BALANCED": {"qualifying_lap_delta_s": 0.0, "race_pace_delta_s_per_lap": 0.0,
                     "tyre_degradation_multiplier_delta": 0.0},
        "RACE_BIASED": {"qualifying_lap_delta_s": round(0.16 * profile["qualifying_weight"], 4),
                        "race_pace_delta_s_per_lap": round(-0.18 * profile["race_weight"], 4),
                        "tyre_degradation_multiplier_delta": round(-0.06 * profile["degradation_weight"], 4)},
    }


def qualifying_outcome(config: PreRaceConfig, truth: dict[str, Any], action: dict[str, Any],
                       resource_cost: float) -> dict[str, Any]:
    tradeoffs = setup_tradeoffs(config.track_archetype)
    base = {"driver_a": 90.10, "driver_b": 90.18}
    rival_times = {"Orion A": 90.00, "Orion B": 90.27, "Nova A": 90.42,
                   "Nova B": 90.63, "Vertex A": 90.81, "Vertex B": 91.00}
    times, modifiers = {}, {}
    for driver in DRIVERS:
        setup = action[driver]
        preference = truth["driver_preference"][driver]
        setup_level = {"RACE_BIASED": -1, "BALANCED": 0, "QUALIFYING_BIASED": 1}[setup]
        mismatch = abs(setup_level - preference)
        grip_interaction = -0.20 * truth["qualifying_grip"] * setup_level
        times[driver] = round(base[driver] + tradeoffs[setup]["qualifying_lap_delta_s"]
                              + 0.10 * mismatch + grip_interaction, 6)
        degradation = tradeoffs[setup]["tyre_degradation_multiplier_delta"]
        degradation += 0.22 * truth["tyre_degradation"] * setup_level
        modifiers[driver] = {
            "pace_seconds_per_lap": round(tradeoffs[setup]["race_pace_delta_s_per_lap"]
                                           + 0.10 * mismatch + resource_cost, 6),
            "tyre_degradation_multiplier": round(1.0 + degradation, 6),
            "reliability_risk_delta": round(resource_cost * 0.20, 6),
            "selected_setup": setup,
        }
    field = [("McLearn A", times["driver_a"]), ("McLearn B", times["driver_b"]), *rival_times.items()]
    grid = [name for name, _ in sorted(field, key=lambda item: (item[1], item[0]))]
    result = {"schema_version": 1, "track_archetype": config.track_archetype,
              "provisional_grid": grid,
              "qualifying_times": {"McLearn A": times["driver_a"], "McLearn B": times["driver_b"]},
              "race_setup_modifier": {"schema_version": 1, "model_version": MODEL_VERSION,
                                      "parc_ferme_locked": True,
                                      "driver_modifiers": modifiers,
                                      "practice_resource_cost": round(resource_cost, 6),
                                      "integration_status": "NOT_APPLIED_TO_AUTHORITATIVE_ENGINE"}}
    result["race_setup_modifier"]["source_hash"] = _hash({"grid": grid, "modifiers": modifiers})
    return result


def trusted_replay(config: PreRaceConfig, seed: int, actions: list[dict[str, Any]]) -> PreRaceSession:
    session = PreRaceSession(config, seed)
    for action in actions:
        session.submit(copy.deepcopy(action))
    return session
