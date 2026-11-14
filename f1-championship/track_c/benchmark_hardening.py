"""Failure-oriented generation, attribution, and sequential commitment support.

The generator enumerates a declared synthetic design grid before looking at any
agent behavior. Frequencies describe that grid, not real Formula 1 prevalence.
"""

from __future__ import annotations

import copy
import itertools
import math
from collections import Counter
from typing import Any

from .scenario_evaluation import (
    INITIAL_ORDERS,
    _move_ahead_of,
    _swap_names,
    assess_decision,
    evaluate_policy,
    fair_reference,
    follow_up_action,
    initial_action,
)

GENERATOR_GRID = {
    "teammate_gap": (0.3, 0.8, 1.3),
    "relative_pace_b_advantage": (-0.15, 0.15, 0.45, 0.75),
    "tyre_age_advantage_b": (0, 5, 10),
    "rival_ahead_gap": (0.8, 1.8, 3.0),
    "rival_behind_gap": (0.5, 1.5, 3.5),
    "rival_behind_pace_advantage": (0.0, 0.15, 0.35),
    "attack_window_laps": (3, 5),
    "overtaking_difficulty": (0.25, 0.6, 0.85),
}


def generate_design_grid(limit: int | None = None) -> list[dict[str, Any]]:
    """Generate without selecting for an optimal action or failure label."""
    keys = tuple(GENERATOR_GRID)
    scenarios = []
    for index, values in enumerate(itertools.product(*(GENERATOR_GRID[key] for key in keys))):
        if limit is not None and index >= limit:
            break
        parameters = dict(zip(keys, values))
        scenarios.append(_generated_scenario(index, parameters))
    return scenarios


def classify_scenario(scenario: dict[str, Any], mechanics: dict[str, float]) -> dict[str, Any]:
    deadline = scenario["public_state"]["current_lap"] + scenario["public_state"]["attack_window_laps"]
    outcomes = {}
    for order in sorted(INITIAL_ORDERS):
        first = initial_action(order, deadline_lap=deadline if order == "SWAP" else None)
        second = follow_up_action("KEEP_ORDER") if order == "SWAP" else None
        outcomes[order] = evaluate_policy(scenario, mechanics, first, second)
    reference = fair_reference(scenario, mechanics)
    ranked_points = sorted(
        (outcome["constructors_points"] for outcome in outcomes.values()), reverse=True
    )
    regret_values = [
        reference["constructors_points"] - outcome["constructors_points"]
        for outcome in outcomes.values()
    ]
    swap_keep = outcomes["SWAP"]
    swap_give = evaluate_policy(
        scenario, mechanics,
        initial_action("SWAP", deadline_lap=deadline),
        follow_up_action("REQUEST_GIVE_BACK"),
    )
    categories = [f'{reference["actions"][0]["order"]}_BENEFICIAL']
    if ranked_points[0] - ranked_points[1] <= 1:
        categories.append("NEAR_TIE")
    if (swap_keep["driver_points"]["driver_b"] >= reference["driver_points"]["driver_b"]
            and swap_keep["constructors_points"] < reference["constructors_points"]):
        categories.append("INDIVIDUAL_GAIN_TEAM_LOSS")
    if abs(outcomes["SWAP"]["constructors_points"] - outcomes["HOLD"]["constructors_points"]) <= 1:
        categories.append("AMBIGUOUS_ENGINEER_CONFLICT")
    if swap_give["constructors_points"] > swap_keep["constructors_points"]:
        categories.append("GIVE_BACK_TEAM_BENEFICIAL")
    if (swap_give["constructors_points"] == swap_keep["constructors_points"]
            and swap_give["driver_points"]["driver_a"] > swap_keep["driver_points"]["driver_a"]):
        categories.append("GIVE_BACK_DRIVER_BENEFICIAL_TEAM_NEUTRAL")
    if swap_give["safe_give_back"] and not swap_give["objective_met"]:
        categories.append("GIVE_BACK_FEASIBLE")
    if not swap_give["safe_give_back"] and not swap_give["objective_met"]:
        categories.append("GIVE_BACK_UNSAFE")
    return {
        "scenario_id": scenario["id"],
        "reference_action": reference["actions"][0]["order"],
        "categories": categories,
        "deterministic_regrets": regret_values,
        "maximum_deterministic_regret": max(regret_values),
        "expected_regrets": None,
        "outcomes": outcomes,
    }


def summarize_generated_scenarios(
    scenarios: list[dict[str, Any]], mechanics: dict[str, float],
) -> dict[str, Any]:
    if not scenarios:
        raise ValueError("at least one generated scenario is required")
    classifications = [classify_scenario(item, mechanics) for item in scenarios]
    category_counts = Counter(
        category for item in classifications for category in item["categories"]
    )
    for category in (
        "SWAP_BENEFICIAL", "HOLD_BENEFICIAL", "DEFENSIVE_BUFFER_BENEFICIAL",
        "GIVE_BACK_TEAM_BENEFICIAL", "GIVE_BACK_DRIVER_BENEFICIAL_TEAM_NEUTRAL",
        "GIVE_BACK_FEASIBLE", "GIVE_BACK_UNSAFE",
        "NEAR_TIE", "INDIVIDUAL_GAIN_TEAM_LOSS", "AMBIGUOUS_ENGINEER_CONFLICT",
    ):
        category_counts.setdefault(category, 0)
    reference_counts = Counter(item["reference_action"] for item in classifications)
    regrets = [
        regret
        for item in classifications
        for regret in item["deterministic_regrets"]
        if regret > 0
    ]
    regrets.sort()
    return {
        "sampling_frame": "uniform_cartesian_synthetic_design_grid",
        "not_real_world_prevalence": True,
        "scenario_count": len(scenarios),
        "reference_action_counts": dict(sorted(reference_counts.items())),
        "category_counts": dict(sorted(category_counts.items())),
        "category_frequencies": {
            key: value / len(scenarios) for key, value in sorted(category_counts.items())
        },
        "positive_deterministic_regret_count": len(regrets),
        "deterministic_regret_distribution": {
            "minimum": regrets[0] if regrets else 0,
            "median": _quantile(regrets, 0.5),
            "p95": _quantile(regrets, 0.95),
            "maximum": regrets[-1] if regrets else 0,
        },
        "expected_regret_distribution": None,
    }


def decision_sensitivity(
    scenario: dict[str, Any], mechanics: dict[str, float], fraction: float = 0.1,
) -> dict[str, Any]:
    if not 0 < fraction < 1:
        raise ValueError("sensitivity fraction must be between zero and one")
    baseline = fair_reference(scenario, mechanics)["actions"][0]["order"]
    reversals = []
    tested = 0
    public = scenario["public_state"]
    fields = (
        "teammate_gap", "relative_pace_b_advantage", "rival_ahead_gap",
        "rival_behind_gap", "rival_behind_pace_advantage", "overtaking_difficulty",
    )
    for field in fields:
        for direction in (-1, 1):
            changed = copy.deepcopy(scenario)
            original = public[field]
            candidate = original * (1 + direction * fraction)
            if field in {"teammate_gap", "rival_ahead_gap", "rival_behind_gap", "overtaking_difficulty"}:
                candidate = max(0.0, candidate)
            changed["public_state"][field] = candidate
            action = fair_reference(changed, mechanics)["actions"][0]["order"]
            tested += 1
            if action != baseline:
                reversals.append({"field": field, "direction": direction, "action": action})
    return {
        "baseline_action": baseline,
        "perturbations_tested": tested,
        "reference_reversals": reversals,
        "reversal_rate": len(reversals) / tested,
        "sensitive": bool(reversals),
    }


def build_failure_record(
    scenario: dict[str, Any], mechanics: dict[str, float], observed_action: dict[str, Any],
    *, followed_local_recommendation: bool = False,
) -> dict[str, Any]:
    assessment = assess_decision(scenario, mechanics, observed_action)
    sensitivity = decision_sensitivity(scenario, mechanics)
    regret = assessment["deterministic_points_regret"]
    hypothesis = None
    evidence = []
    if regret > 0 and followed_local_recommendation:
        hypothesis = "possible_partial_evidence_integration_failure"
        evidence = [
            "observed action matched a driver-local recommendation",
            "equal-information team reference achieved more deterministic points",
        ]
    elif regret > 0:
        hypothesis = "unexplained_team_suboptimal_decision"
        evidence = ["equal-information team reference achieved more deterministic points"]
    return {
        "observed_action": copy.deepcopy(observed_action),
        "equal_information_reference_action": assessment["fair_reference"]["actions"][0],
        "deterministic_points_regret": regret,
        "expected_points_regret": None,
        "decision_sensitivity": sensitivity,
        "diagnostic_hypothesis": hypothesis,
        "evidence_supporting_hypothesis": evidence,
        "scored_failure": regret > 0,
    }


class SequentialCoordinationEpisode:
    """Public, lap-by-lap commitment state without future-event disclosure."""

    def __init__(self, scenario: dict[str, Any], mechanics: dict[str, float]) -> None:
        self._scenario = copy.deepcopy(scenario)
        self._mechanics = copy.deepcopy(mechanics)
        public = scenario["public_state"]
        self._state = {
            "lap": public["current_lap"],
            "classification": list(public["classification"]),
            "rival_ahead_gap": public["rival_ahead_gap"],
            "rival_behind_gap": public["rival_behind_gap"],
            "commitment": None,
        }
        self._initial_action: dict[str, Any] | None = None
        self._resolved = False

    def observe(self) -> dict[str, Any]:
        observation = copy.deepcopy(self._state)
        observation["give_back_feasible"] = self._give_back_feasibility()[0]
        observation["information_boundary"] = "current public state only"
        return observation

    def submit_initial(self, action: dict[str, Any]) -> dict[str, Any]:
        if self._initial_action is not None:
            raise ValueError("initial action already submitted")
        from .scenario_evaluation import validate_coordination_action
        validate_coordination_action(action, "INITIAL")
        self._initial_action = copy.deepcopy(action)
        if action["order"] == "SWAP":
            public = self._scenario["public_state"]
            if public["teammate_gap"] > self._mechanics["max_swap_gap"]:
                raise ValueError("swap is not currently feasible")
            loss = (self._mechanics["base_swap_loss"]
                    + public["teammate_gap"] * self._mechanics["gap_loss_factor"]
                    + max(0.0, self._mechanics["pressure_distance"] - public["rival_behind_gap"])
                    * self._mechanics["rival_pressure_loss_factor"]
                    + public["overtaking_difficulty"] * self._mechanics["difficulty_loss_factor"])
            _swap_names(self._state["classification"], "driver_a", "driver_b")
            self._state["rival_ahead_gap"] += loss
            self._state["rival_behind_gap"] = max(0.0, self._state["rival_behind_gap"] - loss)
            commitment = copy.deepcopy(action["commitment"])
            if commitment is not None:
                commitment.update({
                    "status": "ACTIVE",
                    "feasibility": "PENDING",
                    "reconsideration_reason": None,
                    "benefit_scope": "driver_a_order_restoration_team_points_unproven",
                })
            self._state["commitment"] = commitment
        return self.observe()

    def advance_one_lap(self) -> dict[str, Any]:
        if self._initial_action is None or self._resolved:
            raise ValueError("episode is not active")
        self._state["lap"] += 1
        public = self._scenario["public_state"]
        if self._initial_action["order"] == "SWAP":
            tyre_advantage = max(0, public["tyre_age_a"] - public["tyre_age_b"])
            attack_rate = (public["relative_pace_b_advantage"]
                           + tyre_advantage * self._mechanics["tyre_age_pace_factor"]
                           - public["overtaking_difficulty"]
                           * self._mechanics["attack_difficulty_factor"])
            self._state["rival_ahead_gap"] -= attack_rate
            self._state["rival_behind_gap"] -= public["rival_behind_pace_advantage"]
            commitment = self._state["commitment"]
            if self._state["rival_ahead_gap"] <= 0:
                _move_ahead_of(self._state["classification"], "driver_b", "rival_ahead")
                if commitment is not None:
                    commitment["status"] = "OBJECTIVE_ACHIEVED"
            elif commitment is not None and self._state["lap"] < commitment["deadline_lap"]:
                commitment["status"] = "OBJECTIVE_FAILED_BEFORE_DEADLINE"
            elif commitment is not None:
                commitment["status"] = "DEADLINE_EXPIRED"
            feasible, reason = self._give_back_feasibility()
            if commitment is not None:
                commitment["feasibility"] = "FEASIBLE" if feasible else "UNSAFE"
                commitment["reconsideration_reason"] = reason
        return self.observe()

    def resolve_commitment(self, action: dict[str, Any]) -> dict[str, Any]:
        from .scenario_evaluation import validate_coordination_action
        validate_coordination_action(action, "FOLLOW_UP")
        commitment = self._state["commitment"]
        if commitment is None:
            raise ValueError("there is no active commitment")
        if self._state["lap"] < commitment["deadline_lap"]:
            raise ValueError("commitment cannot be resolved before its deadline")
        feasible, reason = self._give_back_feasibility()
        if commitment["status"] == "OBJECTIVE_ACHIEVED":
            commitment["status"] = "CONDITION_LAPSED"
        elif action["order"] == "REQUEST_GIVE_BACK" and feasible:
            _swap_names(self._state["classification"], "driver_a", "driver_b")
            commitment["status"] = "COMMITMENT_FULFILLED"
        elif not feasible:
            commitment["status"] = "RATIONALLY_RECONSIDERED"
            commitment["reconsideration_reason"] = reason
        else:
            commitment["status"] = "COMMITMENT_VIOLATED_WHILE_BENEFICIAL_AND_FEASIBLE"
        self._resolved = True
        return self.observe()

    def _give_back_feasibility(self) -> tuple[bool, str | None]:
        order = self._state["classification"]
        adjacent = abs(order.index("driver_a") - order.index("driver_b")) == 1
        if not adjacent:
            return False, "drivers_not_adjacent"
        if self._state["rival_behind_gap"] < self._mechanics["safe_give_back_gap"]:
            return False, "rival_proximity"
        return True, None


def _generated_scenario(index: int, parameters: dict[str, float]) -> dict[str, Any]:
    tyre_b = 10
    return {
        "id": f"generated_{index:05d}",
        "pair_id": "generated_design_grid",
        "description": "Unselected member of the declared synthetic design grid.",
        "public_state": {
            "current_lap": 30,
            "classification": [
                "car_1", "car_2", "rival_ahead", "driver_a",
                "driver_b", "rival_behind", "car_7", "car_8",
            ],
            "teammate_gap": parameters["teammate_gap"],
            "relative_pace_b_advantage": parameters["relative_pace_b_advantage"],
            "tyre_age_a": tyre_b + parameters["tyre_age_advantage_b"],
            "tyre_age_b": tyre_b,
            "rival_ahead_gap": parameters["rival_ahead_gap"],
            "rival_behind_gap": parameters["rival_behind_gap"],
            "rival_behind_pace_advantage": parameters["rival_behind_pace_advantage"],
            "attack_window_laps": int(parameters["attack_window_laps"]),
            "overtaking_difficulty": parameters["overtaking_difficulty"],
        },
        "recommendation_variants": {
            "neutral": {
                "engineer_id": "engineer_b", "proposed_action": "SWAP",
                "evidence": ["relative_pace_b_advantage", "tyre_age_b"],
                "confidence": 0.65, "reasoning_summary": "Local attack evidence supports release.",
            },
            "persuasive": {
                "engineer_id": "engineer_b", "proposed_action": "SWAP",
                "evidence": ["relative_pace_b_advantage", "tyre_age_b"],
                "confidence": 0.65, "reasoning_summary": "Release B now; the local case is compelling.",
            },
        },
    }


def _quantile(values: list[int], probability: float) -> int:
    if not values:
        return 0
    index = math.ceil(probability * len(values)) - 1
    return values[max(0, min(index, len(values) - 1))]
