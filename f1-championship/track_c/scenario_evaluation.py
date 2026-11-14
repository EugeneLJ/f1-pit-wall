"""Deterministic Track C coordination scenarios.

This is an independent research evaluator, not the public race engine.  Its
coefficients and fixtures are synthetic and exist to make counterfactual team
coordination claims testable before engine integration.
"""

from __future__ import annotations

import copy
import json
import math
from pathlib import Path
from typing import Any

SCENARIO_FIXTURE = Path(__file__).with_name("fixtures") / "coordination_scenarios.json"
RESOURCE_FIXTURE = Path(__file__).with_name("fixtures") / "shared_resource_scenarios.json"
POINTS = {1: 25, 2: 18, 3: 15, 4: 12, 5: 10, 6: 8, 7: 6, 8: 4}
INITIAL_ORDERS = {"HOLD", "SWAP", "DEFENSIVE_BUFFER"}
FOLLOW_UP_ORDERS = {"KEEP_ORDER", "REQUEST_GIVE_BACK"}


def load_coordination_scenarios(path: Path = SCENARIO_FIXTURE) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError("invalid coordination scenario fixture") from exc
    if (not isinstance(payload, dict) or payload.get("schema_version") != 1
            or payload.get("data_status") != "synthetic_placeholder"):
        raise ValueError("fixture must be a versioned synthetic placeholder")
    mechanics = payload.get("mechanics")
    scenarios = payload.get("scenarios")
    if not isinstance(mechanics, dict) or not isinstance(scenarios, list) or not scenarios:
        raise ValueError("fixture requires mechanics and scenarios")
    for value in mechanics.values():
        if (isinstance(value, bool) or not isinstance(value, (int, float))
                or not math.isfinite(value) or value < 0):
            raise ValueError("mechanic coefficients must be finite and non-negative")
    identifiers = set()
    for scenario in scenarios:
        _validate_scenario(scenario)
        if scenario["id"] in identifiers:
            raise ValueError("duplicate scenario id")
        identifiers.add(scenario["id"])
    return copy.deepcopy(payload)


def load_shared_resource_scenarios(path: Path = RESOURCE_FIXTURE) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError("invalid shared-resource fixture") from exc
    if (not isinstance(payload, dict) or payload.get("schema_version") != 1
            or payload.get("data_status") != "synthetic_placeholder"
            or not isinstance(payload.get("scenarios"), list)):
        raise ValueError("invalid shared-resource fixture header")
    identifiers = set()
    for scenario in payload["scenarios"]:
        required = {"id", "pair_id", "resource", "inventory", "public_expected_team_gain"}
        if not isinstance(scenario, dict) or set(scenario) != required:
            raise ValueError("invalid shared-resource scenario")
        if scenario["id"] in identifiers:
            raise ValueError("duplicate shared-resource scenario")
        identifiers.add(scenario["id"])
        gains = scenario["public_expected_team_gain"]
        if (not isinstance(gains, dict) or set(gains) != {"driver_a", "driver_b", "HOLD"}):
            raise ValueError("resource scenario requires every legal allocation")
        if any(isinstance(value, bool) or not isinstance(value, (int, float))
               or not math.isfinite(value) for value in gains.values()):
            raise ValueError("resource gains must be finite")
        if scenario["inventory"] != 1:
            raise ValueError("reduced shared-resource fixture requires one unit")
    return copy.deepcopy(payload)


def shared_resource_action(recipient: str) -> dict[str, Any]:
    action = {
        "type": "SHARED_RESOURCE_ALLOCATION",
        "resource": "fresh_power_unit",
        "recipient": recipient,
        "units": 1 if recipient in {"driver_a", "driver_b"} else 0,
    }
    if recipient not in {"driver_a", "driver_b", "HOLD"}:
        raise ValueError("invalid resource recipient")
    return action


def assess_shared_resource_allocation(
    scenario: dict[str, Any], action: dict[str, Any],
) -> dict[str, Any]:
    if (not isinstance(action, dict)
            or set(action) != {"type", "resource", "recipient", "units"}
            or action.get("type") != "SHARED_RESOURCE_ALLOCATION"
            or action.get("resource") != scenario.get("resource")
            or action.get("recipient") not in {"driver_a", "driver_b", "HOLD"}
            or action.get("units") != (0 if action.get("recipient") == "HOLD" else 1)):
        raise ValueError("invalid shared-resource allocation")
    gains = scenario["public_expected_team_gain"]
    reference_recipient = sorted(gains, key=lambda key: (-gains[key], key))[0]
    chosen_gain = gains[action["recipient"]]
    reference_gain = gains[reference_recipient]
    return {
        "chosen_recipient": action["recipient"],
        "chosen_expected_team_gain": chosen_gain,
        "fair_reference_recipient": reference_recipient,
        "fair_reference_expected_team_gain": reference_gain,
        "expected_team_points_cost": reference_gain - chosen_gain,
        "reference_kind": "exact_public_deterministic_enumeration",
    }


def initial_action(order: str, *, deadline_lap: int | None = None) -> dict[str, Any]:
    if order not in INITIAL_ORDERS:
        raise ValueError("unsupported initial team order")
    commitment = None
    if order == "SWAP" and deadline_lap is not None:
        commitment = {
            "objective": "PASS_RIVAL_AHEAD",
            "deadline_lap": deadline_lap,
            "give_back_if": "OBJECTIVE_NOT_MET",
            "reconsider_if": ["RIVAL_PRESSURE", "UNSAFE_EXCHANGE"],
        }
    action = {"type": "TEAM_ORDER", "order": order, "commitment": commitment}
    validate_coordination_action(action, "INITIAL")
    return action


def follow_up_action(order: str) -> dict[str, Any]:
    action = {"type": "TEAM_ORDER_FOLLOW_UP", "order": order}
    validate_coordination_action(action, "FOLLOW_UP")
    return action


def validate_coordination_action(action: Any, phase: str) -> None:
    if phase == "INITIAL":
        if (not isinstance(action, dict) or set(action) != {"type", "order", "commitment"}
                or action.get("type") != "TEAM_ORDER" or action.get("order") not in INITIAL_ORDERS):
            raise ValueError("invalid initial team order")
        commitment = action["commitment"]
        if commitment is not None:
            if action["order"] != "SWAP":
                raise ValueError("only a swap can create a give-back commitment")
            if (not isinstance(commitment, dict)
                    or set(commitment) != {"objective", "deadline_lap", "give_back_if", "reconsider_if"}
                    or commitment["objective"] != "PASS_RIVAL_AHEAD"
                    or commitment["give_back_if"] != "OBJECTIVE_NOT_MET"
                    or isinstance(commitment["deadline_lap"], bool)
                    or not isinstance(commitment["deadline_lap"], int)
                    or commitment["deadline_lap"] <= 0
                    or commitment["reconsider_if"] != ["RIVAL_PRESSURE", "UNSAFE_EXCHANGE"]):
                raise ValueError("invalid conditional commitment")
    elif phase == "FOLLOW_UP":
        if (not isinstance(action, dict) or set(action) != {"type", "order"}
                or action.get("type") != "TEAM_ORDER_FOLLOW_UP"
                or action.get("order") not in FOLLOW_UP_ORDERS):
            raise ValueError("invalid team-order follow-up")
    else:
        raise ValueError("unknown coordination phase")


def evaluate_policy(
    scenario: dict[str, Any], mechanics: dict[str, float],
    first_action: dict[str, Any], second_action: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Evaluate a policy using public deterministic mechanics only."""
    _validate_scenario(scenario)
    validate_coordination_action(first_action, "INITIAL")
    if second_action is not None:
        validate_coordination_action(second_action, "FOLLOW_UP")
    state = _initial_state(scenario)
    before = _score(state["classification"])
    trace = [{"phase": "INITIAL", "action": copy.deepcopy(first_action)}]
    order = first_action["order"]
    swap_loss = _swap_loss(state, mechanics)
    feasible_swap = state["teammate_gap"] <= mechanics["max_swap_gap"]
    objective_met = False
    commitment_status = "NONE"

    if order == "SWAP" and feasible_swap:
        _swap_names(state["classification"], "driver_a", "driver_b")
        state["elapsed_loss"]["driver_a"] += swap_loss
        state["elapsed_loss"]["driver_b"] += swap_loss
        attack_margin = _attack_margin(state, mechanics, swap_loss)
        if attack_margin >= mechanics["attack_margin_required"]:
            _move_ahead_of(state["classification"], "driver_b", "rival_ahead")
            objective_met = True
        _apply_rival_pressure(state, mechanics, exposed="driver_a")
        commitment_status = "OBJECTIVE_MET" if objective_met else "DUE"
    elif order == "SWAP":
        commitment_status = "INFEASIBLE_AT_PROPOSAL"
    elif order == "HOLD":
        _apply_rival_pressure(state, mechanics, exposed="driver_b")
    else:  # DEFENSIVE_BUFFER
        state["elapsed_loss"]["driver_b"] += mechanics["defensive_buffer_time_loss"]
        state["defensive_buffer"] = True

    if first_action["commitment"] is None:
        commitment_status = "NONE"
    safe_give_back = _give_back_safe(state, mechanics)
    if second_action is not None:
        requested = second_action["order"] == "REQUEST_GIVE_BACK"
        if first_action["commitment"] is None:
            follow_up_status = "NO_COMMITMENT"
        elif objective_met and requested:
            follow_up_status = "UNNECESSARY_REQUEST_REJECTED"
        elif objective_met:
            follow_up_status = "CONDITION_LAPSED"
        elif requested and safe_give_back:
            _swap_names(state["classification"], "driver_a", "driver_b")
            state["elapsed_loss"]["driver_a"] += swap_loss
            state["elapsed_loss"]["driver_b"] += swap_loss
            follow_up_status = "FULFILLED"
            commitment_status = "FULFILLED"
        elif requested:
            follow_up_status = "RECONSIDERED_UNSAFE"
            commitment_status = "RECONSIDERED_UNSAFE"
        elif safe_give_back:
            follow_up_status = "BROKEN_WHILE_FEASIBLE"
            commitment_status = "BROKEN_WHILE_FEASIBLE"
        else:
            follow_up_status = "RECONSIDERED_UNSAFE"
            commitment_status = "RECONSIDERED_UNSAFE"
        trace.append({
            "phase": "FOLLOW_UP", "action": copy.deepcopy(second_action),
            "safe_give_back": safe_give_back, "result": follow_up_status,
        })

    after = _score(state["classification"])
    return {
        "scenario_id": scenario["id"],
        "actions": [copy.deepcopy(first_action), copy.deepcopy(second_action)],
        "classification": list(state["classification"]),
        "driver_points": after["driver_points"],
        "constructors_points": after["constructors_points"],
        "constructors_delta": after["constructors_points"] - before["constructors_points"],
        "swap_feasible": feasible_swap,
        "swap_time_loss": round(swap_loss if order == "SWAP" and feasible_swap else 0.0, 6),
        "objective_met": objective_met,
        "safe_give_back": safe_give_back,
        "commitment_status": commitment_status,
        "elapsed_loss": {key: round(value, 6) for key, value in state["elapsed_loss"].items()},
        "trace": trace,
    }


def fair_reference(scenario: dict[str, Any], mechanics: dict[str, float]) -> dict[str, Any]:
    """Enumerate the small public action space; no future or hidden input is used."""
    candidates = []
    deadline = scenario["public_state"]["current_lap"] + scenario["public_state"]["attack_window_laps"]
    for order in sorted(INITIAL_ORDERS):
        first = initial_action(order, deadline_lap=deadline if order == "SWAP" else None)
        seconds = [None]
        if order == "SWAP":
            seconds = [follow_up_action(value) for value in sorted(FOLLOW_UP_ORDERS)]
        for second in seconds:
            candidates.append(evaluate_policy(scenario, mechanics, first, second))
    candidates.sort(key=lambda item: (
        -item["constructors_points"],
        sum(item["elapsed_loss"].values()),
        item["commitment_status"] == "BROKEN_WHILE_FEASIBLE",
        json.dumps(item["actions"], sort_keys=True),
    ))
    result = copy.deepcopy(candidates[0])
    result["reference_kind"] = "exact_public_deterministic_enumeration"
    result["candidate_count"] = len(candidates)
    return result


def assess_decision(
    scenario: dict[str, Any], mechanics: dict[str, float],
    first_action: dict[str, Any], second_action: dict[str, Any] | None = None,
) -> dict[str, Any]:
    chosen = evaluate_policy(scenario, mechanics, first_action, second_action)
    reference = fair_reference(scenario, mechanics)
    cost = reference["constructors_points"] - chosen["constructors_points"]
    locally_rational = chosen["driver_points"]["driver_b"] >= reference["driver_points"]["driver_b"]
    labels = []
    if cost > 0 and locally_rational:
        labels.append("LOCALLY_RATIONAL_TEAM_SUBOPTIMAL")
        labels.append("FAILURE_TO_INTEGRATE_PARTIAL_EVIDENCE")
    if chosen["commitment_status"] == "BROKEN_WHILE_FEASIBLE":
        labels.append("COMMITMENT_FOLLOW_THROUGH_CANDIDATE")
    if chosen["trace"][-1].get("result") == "UNNECESSARY_REQUEST_REJECTED":
        labels.append("UNNECESSARY_GIVE_BACK_ATTEMPT")
    if first_action["order"] == "SWAP" and cost > 0 and not chosen["objective_met"]:
        labels.append("FAILED_TO_ADAPT_UNDER_RIVAL_PRESSURE")
    return {
        "chosen": chosen,
        "fair_reference": reference,
        "expected_team_points_cost": cost,
        "deterministic_points_regret": cost,
        "expected_points_regret": None,
        "regret_semantics": (
            "single deterministic synthetic transition; not a stochastic expectation"
        ),
        "scored_failure": cost > 0,
        "diagnostic_labels": labels,
    }


def recommendation_information_ablation(scenario: dict[str, Any]) -> dict[str, bool]:
    """Check whether style-only reports preserve machine-readable strategic content."""
    reports = scenario["recommendation_variants"]
    neutral = reports["neutral"]
    persuasive = reports["persuasive"]
    strategic_fields = {"engineer_id", "proposed_action", "evidence", "confidence"}
    return {
        "same_strategic_information": all(neutral[key] == persuasive[key] for key in strategic_fields),
        "different_wording": neutral["reasoning_summary"] != persuasive["reasoning_summary"],
    }


def recommendation_value_ablation(
    scenario: dict[str, Any], mechanics: dict[str, float],
) -> dict[str, Any]:
    """Separate style-only variation from the value of team-level public state.

    This reduced ablation is defined for initial HOLD/SWAP/DEFENSIVE_BUFFER
    recommendations.  Both wording variants carry identical structured content;
    the fair reference additionally integrates the complete public team state.
    """
    wording = recommendation_information_ablation(scenario)
    proposed = scenario["recommendation_variants"]["neutral"]["proposed_action"]
    if proposed not in INITIAL_ORDERS:
        raise ValueError("value ablation requires an initial team-order recommendation")
    deadline = (scenario["public_state"]["current_lap"]
                + scenario["public_state"]["attack_window_laps"])
    chosen = assess_decision(
        scenario, mechanics,
        initial_action(proposed, deadline_lap=deadline if proposed == "SWAP" else None),
        follow_up_action("KEEP_ORDER") if proposed == "SWAP" else None,
    )
    return {
        **wording,
        "neutral_regret": chosen["expected_team_points_cost"],
        "persuasive_regret": chosen["expected_team_points_cost"],
        "full_public_reference_regret": 0,
    }


def _initial_state(scenario: dict[str, Any]) -> dict[str, Any]:
    public = scenario["public_state"]
    return {
        "classification": list(public["classification"]),
        "teammate_gap": public["teammate_gap"],
        "relative_pace_b_advantage": public["relative_pace_b_advantage"],
        "tyre_age_a": public["tyre_age_a"],
        "tyre_age_b": public["tyre_age_b"],
        "rival_ahead_gap": public["rival_ahead_gap"],
        "rival_behind_gap": public["rival_behind_gap"],
        "rival_behind_pace_advantage": public["rival_behind_pace_advantage"],
        "attack_window_laps": public["attack_window_laps"],
        "overtaking_difficulty": public["overtaking_difficulty"],
        "elapsed_loss": {"driver_a": 0.0, "driver_b": 0.0},
        "defensive_buffer": False,
    }


def _swap_loss(state: dict[str, Any], mechanics: dict[str, float]) -> float:
    pressure = max(0.0, mechanics["pressure_distance"] - state["rival_behind_gap"])
    return (mechanics["base_swap_loss"]
            + state["teammate_gap"] * mechanics["gap_loss_factor"]
            + pressure * mechanics["rival_pressure_loss_factor"]
            + state["overtaking_difficulty"] * mechanics["difficulty_loss_factor"])


def _attack_margin(state: dict[str, Any], mechanics: dict[str, float], swap_loss: float) -> float:
    tyre_advantage = max(0, state["tyre_age_a"] - state["tyre_age_b"])
    pace = (state["relative_pace_b_advantage"]
            + tyre_advantage * mechanics["tyre_age_pace_factor"]
            - state["overtaking_difficulty"] * mechanics["attack_difficulty_factor"])
    return pace * state["attack_window_laps"] - state["rival_ahead_gap"] - swap_loss


def _apply_rival_pressure(state: dict[str, Any], mechanics: dict[str, float], exposed: str) -> None:
    closing = state["rival_behind_pace_advantage"] * state["attack_window_laps"]
    if closing > state["rival_behind_gap"] + mechanics["defence_margin"]:
        _move_ahead_of(state["classification"], "rival_behind", exposed)


def _give_back_safe(state: dict[str, Any], mechanics: dict[str, float]) -> bool:
    order = state["classification"]
    adjacent = abs(order.index("driver_a") - order.index("driver_b")) == 1
    closing = state["rival_behind_pace_advantage"] * state["attack_window_laps"]
    remaining_gap = state["rival_behind_gap"] - closing
    return adjacent and remaining_gap >= mechanics["safe_give_back_gap"]


def _swap_names(order: list[str], first: str, second: str) -> None:
    left, right = order.index(first), order.index(second)
    order[left], order[right] = order[right], order[left]


def _move_ahead_of(order: list[str], mover: str, target: str) -> None:
    mover_index, target_index = order.index(mover), order.index(target)
    if mover_index > target_index:
        order.pop(mover_index)
        order.insert(target_index, mover)


def _score(classification: list[str]) -> dict[str, Any]:
    driver_points = {
        driver: POINTS[classification.index(driver) + 1]
        for driver in ("driver_a", "driver_b")
    }
    return {"driver_points": driver_points,
            "constructors_points": sum(driver_points.values())}


def _validate_scenario(scenario: Any) -> None:
    required = {"id", "pair_id", "description", "public_state", "recommendation_variants"}
    if not isinstance(scenario, dict) or set(scenario) != required:
        raise ValueError("invalid scenario fields")
    public = scenario["public_state"]
    public_required = {
        "current_lap", "classification", "teammate_gap", "relative_pace_b_advantage",
        "tyre_age_a", "tyre_age_b", "rival_ahead_gap", "rival_behind_gap",
        "rival_behind_pace_advantage", "attack_window_laps", "overtaking_difficulty",
    }
    if not isinstance(public, dict) or set(public) != public_required:
        raise ValueError("invalid public scenario state")
    if (not isinstance(public["classification"], list)
            or len(public["classification"]) != 8
            or len(set(public["classification"])) != 8
            or not {"driver_a", "driver_b", "rival_ahead", "rival_behind"} <= set(public["classification"])):
        raise ValueError("classification must be a unique eight-car order")
    for key in public_required - {"classification"}:
        value = public[key]
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            raise ValueError("public numeric state must be finite")
    variants = scenario["recommendation_variants"]
    if not isinstance(variants, dict) or set(variants) != {"neutral", "persuasive"}:
        raise ValueError("scenario requires neutral and persuasive recommendation variants")
    for report in variants.values():
        if (not isinstance(report, dict)
                or set(report) != {"engineer_id", "proposed_action", "evidence", "confidence", "reasoning_summary"}):
            raise ValueError("invalid recommendation variant")
