"""Public-information counterfactuals for the C5 pre-race planning module."""

from __future__ import annotations

import copy
import itertools
import math
from typing import Any

from .pre_race_planning import (DRIVERS, LEVELS, LEVEL_NAMES, PREFERENCE_NAMES, SETUPS, TESTS,
                                PreRaceConfig, _bayes_update, _seed_id, qualifying_outcome)


def _decode(summary: dict[str, Any], names: dict[int, str]) -> dict[int, float]:
    probabilities = summary.get("probabilities", {})
    decoded = {level: float(probabilities.get(names[level], 0.0)) for level in LEVELS}
    if any(not math.isfinite(value) or value < 0 for value in decoded.values()):
        raise ValueError("invalid public belief")
    total = sum(decoded.values())
    if not math.isclose(total, 1.0, abs_tol=2e-5):
        raise ValueError("public belief probabilities must sum to one")
    return {key: value / total for key, value in decoded.items()}


def public_beliefs(observation: dict[str, Any]) -> dict[str, Any]:
    beliefs = observation["beliefs"]
    return {
        "qualifying_grip": _decode(beliefs["qualifying_grip"], LEVEL_NAMES),
        "tyre_degradation": _decode(beliefs["tyre_degradation"], LEVEL_NAMES),
        "driver_preference": {driver: _decode(beliefs["driver_preference"][driver], PREFERENCE_NAMES)
                              for driver in DRIVERS},
    }


def _worlds(beliefs: dict[str, Any]):
    for grip, degradation, pref_a, pref_b in itertools.product(LEVELS, repeat=4):
        probability = (beliefs["qualifying_grip"][grip] * beliefs["tyre_degradation"][degradation]
                       * beliefs["driver_preference"]["driver_a"][pref_a]
                       * beliefs["driver_preference"]["driver_b"][pref_b])
        yield probability, {"qualifying_grip": grip, "tyre_degradation": degradation,
                            "driver_preference": {"driver_a": pref_a, "driver_b": pref_b}}


def _team_points_proxy(outcome: dict[str, Any]) -> float:
    """Published smooth expected-points proxy against a fixed rival field."""
    grid = outcome["provisional_grid"]
    track = outcome["track_archetype"]
    grid_weight = {"STREET": 1.45, "BALANCED": 0.65, "HIGH_DEGRADATION": 0.20}[track]
    effective_laps = {"STREET": 8, "BALANCED": 14, "HIGH_DEGRADATION": 20}[track]
    metric = {name: grid.index(name) * grid_weight for name in grid}
    for public, driver in (("McLearn A", "driver_a"), ("McLearn B", "driver_b")):
        modifier = outcome["race_setup_modifier"]["driver_modifiers"][driver]
        metric[public] += (effective_laps * modifier["pace_seconds_per_lap"]
                           + 8 * (modifier["tyre_degradation_multiplier"] - 1.0)
                           + 5 * modifier["reliability_risk_delta"])
    # Logistic pairwise win probabilities represent unresolved race variation.  This is a
    # declared synthetic expectation, not a realized finish or hidden future event.
    scale = 0.55
    points = (25, 18, 15, 12, 10, 8, 6, 4, 0)
    total = 0.0
    for name in ("McLearn A", "McLearn B"):
        expected_position = 1.0 + sum(
            1.0 / (1.0 + math.exp(-(metric[name] - metric[other]) / scale))
            for other in metric if other != name
        )
        lower = min(8, max(1, int(math.floor(expected_position))))
        upper = min(9, lower + 1)
        fraction = expected_position - lower
        total += points[lower - 1] * (1 - fraction) + points[upper - 1] * fraction
    return total


def setup_action_values(observation: dict[str, Any]) -> dict[str, float]:
    """Exact expectation under the public posterior; no realized hidden condition is read."""
    config = PreRaceConfig(observation["track"]["archetype"])
    resource_cost = observation.get("practice_summary", {}).get("resource_cost", 0.0)
    beliefs = public_beliefs(observation)
    values = {}
    for setup_a, setup_b in itertools.product(SETUPS, repeat=2):
        action = {"type": "SELECT_SETUPS", "driver_a": setup_a, "driver_b": setup_b}
        value = sum(probability * _team_points_proxy(qualifying_outcome(config, world, action, resource_cost))
                    for probability, world in _worlds(beliefs))
        values[f"{setup_a}/{setup_b}"] = round(value, 8)
    return values


def qualifying_reference(observation: dict[str, Any], chosen_action: dict[str, Any],
                         near_tie_threshold: float = 0.05) -> dict[str, Any]:
    values = setup_action_values(observation)
    chosen_key = f"{chosen_action['driver_a']}/{chosen_action['driver_b']}"
    if chosen_key not in values:
        raise ValueError("chosen Qualifying action is not legal")
    best_key = max(sorted(values), key=values.get)
    regret = values[best_key] - values[chosen_key]
    best_a, best_b = best_key.split("/")
    return {"reference_kind": "SYNTHETIC_PUBLIC_POSTERIOR_EXACT_ENUMERATION",
            "uses_hidden_truth": False, "uses_future_realization": False,
            "chosen_action": copy.deepcopy(chosen_action),
            "reference_action": {"type": "SELECT_SETUPS", "driver_a": best_a, "driver_b": best_b},
            "chosen_expected_team_points_proxy": values[chosen_key],
            "reference_expected_team_points_proxy": values[best_key],
            "expected_regret": round(regret, 8), "confidence_interval": None,
            "decision_sensitivity": "NEAR_TIE" if regret <= near_tie_threshold else "SEPARATED",
            "near_tie_threshold": near_tie_threshold, "all_action_values": values,
            "calibration": "synthetic_not_FIA_or_historical_points",
            "c4_equal_information_reference": {
                "reference_action": {"type": "SELECT_SETUPS", "driver_a": best_a, "driver_b": best_b},
                "chosen_expected_team_points": values[chosen_key],
                "reference_expected_team_points": values[best_key],
                "regret_ci": {"low": round(regret, 8), "mean": round(regret, 8),
                              "high": round(regret, 8)},
                "source": "SYNTHETIC_PUBLIC_POSTERIOR_EXACT_ENUMERATION",
                "uses_future_realization": False,
                "sensitivity": {"near_tie_threshold_points": near_tie_threshold},
            }}


def practice_test_information_value(observation: dict[str, Any], test: str,
                                    driver: str | None = None) -> dict[str, Any]:
    """Expected value of sample information, including the test's race-resource cost."""
    if observation.get("stage") != "PRACTICE" or test not in TESTS:
        raise ValueError("Practice observation and known test required")
    if test == "SETUP_COMPARISON" and driver not in DRIVERS:
        raise ValueError("SETUP_COMPARISON requires a driver")
    if test != "SETUP_COMPARISON" and driver is not None:
        raise ValueError("driver only applies to SETUP_COMPARISON")
    available = {(row["test"], row.get("driver")) for row in observation["available_tests"]}
    if (test, driver) not in available:
        raise ValueError("test is not currently available")
    beliefs = public_beliefs(observation)
    current = _best_value_from_beliefs(observation, beliefs,
                                       observation.get("practice_summary", {}).get("resource_cost", 0.0))
    factor = TESTS[test]["factor"]
    prior = beliefs[factor][driver] if factor == "driver_preference" else beliefs[factor]
    accuracy = next(row["measurement_accuracy"] for row in observation["available_tests"]
                    if row["test"] == test and row.get("driver") == driver)
    expected_after = 0.0
    signal_probabilities = {}
    for signal in LEVELS:
        probability = sum(prior[truth] * (accuracy if truth == signal else (1 - accuracy) / 2)
                          for truth in LEVELS)
        updated = _bayes_update(prior, signal, accuracy)
        next_beliefs = copy.deepcopy(beliefs)
        if factor == "driver_preference":
            next_beliefs[factor][driver] = updated
        else:
            next_beliefs[factor] = updated
        value = _best_value_from_beliefs(observation, next_beliefs,
                                         TESTS[test]["resource_cost"])
        expected_after += probability * value
        signal_probabilities[str(signal)] = round(probability, 8)
    return {"test": test, "driver": driver, "current_best_value": round(current, 8),
            "expected_best_value_after_test": round(expected_after, 8),
            "expected_value_of_sample_information_net_cost": round(expected_after - current, 8),
            "signal_probabilities": signal_probabilities,
            "uses_hidden_truth": False, "calibration": "synthetic_points_proxy"}


def _best_value_from_beliefs(observation: dict[str, Any], beliefs: dict[str, Any],
                             additional_resource_cost: float) -> float:
    config = PreRaceConfig(observation["track"]["archetype"])
    prior_cost = sum(float(row.get("race_resource_cost", 0.0)) for row in observation["performed_tests"])
    best = -math.inf
    for setup_a, setup_b in itertools.product(SETUPS, repeat=2):
        action = {"type": "SELECT_SETUPS", "driver_a": setup_a, "driver_b": setup_b}
        value = sum(probability * _team_points_proxy(
            qualifying_outcome(config, world, action, prior_cost + additional_resource_cost))
                    for probability, world in _worlds(beliefs))
        best = max(best, value)
    return best


def paired_reversal(config: PreRaceConfig, seed: int, test_action: dict[str, Any]) -> dict[str, Any]:
    """Agent-independent case construction: compare public reference before/after one test."""
    from .pre_race_planning import PreRaceSession
    session = PreRaceSession(config, seed)
    before_practice = session.observation()
    session.submit(test_action)
    after_practice = session.observation()
    session.submit({"type": "END_PRACTICE"})
    after = session.observation()
    blank = PreRaceSession(config, seed)
    blank.submit({"type": "END_PRACTICE"})
    before = blank.observation()
    before_values, after_values = setup_action_values(before), setup_action_values(after)
    best_before = max(sorted(before_values), key=before_values.get)
    best_after = max(sorted(after_values), key=after_values.get)
    return {"seed_id": _seed_id(seed), "test_action": copy.deepcopy(test_action),
            "signal": after_practice["performed_tests"][-1]["signal"],
            "best_before": best_before, "best_after": best_after,
            "reversal": best_before != best_after,
            "control_or_reversal": "DECISION_REVERSAL" if best_before != best_after else "NO_CHANGE_CONTROL",
            "uses_agent_output_to_generate_case": False}
