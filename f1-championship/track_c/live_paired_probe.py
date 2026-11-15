"""C7 live paired-probe contracts built on the frozen C6 evidence pipeline."""

from __future__ import annotations

import copy
import hashlib
import json
import math
from typing import Any

from f1pitwall.integrated.providers import CHIEF_PROMPT, PROMPT_TEMPLATE_VERSION, RULES_SUMMARY

from .adaptive_rival_evaluation import classify_adaptation
from .coordination_evaluation import EvaluationError

CONTRACT_VERSION = "c7-paired-probe-v1"
FORBIDDEN_OBSERVATION_KEYS = {
    "hidden_seed", "future_events", "realized_future", "rival_policy", "variant", "seed",
}


def canonical_hash(value: Any) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    return hashlib.sha256(encoded).hexdigest()


def nested_keys(value: Any) -> set[str]:
    if isinstance(value, dict):
        out = set(value)
        for item in value.values():
            out.update(nested_keys(item))
        return out
    if isinstance(value, list):
        out: set[str] = set()
        for item in value:
            out.update(nested_keys(item))
        return out
    return set()


def live_observation(public_observation: dict[str, Any], team: str = "Apex") -> dict[str, Any]:
    """Add only the provider contract; never add generator/policy metadata."""
    if FORBIDDEN_OBSERVATION_KEYS & nested_keys(public_observation):
        raise EvaluationError("public probe observation contains a forbidden hidden field")
    observation = copy.deepcopy(public_observation)
    if observation.get("decision_type") != "RACE_STRATEGY":
        raise EvaluationError("C7 supports race-strategy probes only")
    race = observation.get("race_progress") or {}
    legal = race.get("legal_actions")
    orders = (observation.get("team_orders") or {}).get("legal_team_orders")
    if not isinstance(legal, list) or not legal or not isinstance(orders, list) or not orders:
        raise EvaluationError("probe lacks public legal-action information")
    observation.update({
        "team": team,
        "contract_version": CONTRACT_VERSION,
        "benchmark_version": "2.0.1",
        "mode": "PAIRED_DIAGNOSTIC",
        "action_schema": {
            "type": "RACE_STRATEGY",
            "driver_a": "|".join(legal),
            "driver_b": "|".join(legal),
            "team_order": {"order": "|".join(orders)},
            "format_example": {"type": "RACE_STRATEGY", "driver_a": "STAY", "driver_b": "STAY",
                               "team_order": {"order": orders[0]}},
        },
    })
    return observation


def exact_prompt(observation: dict[str, Any], team: str = "Apex") -> str:
    return CHIEF_PROMPT.format(team=team, rules=RULES_SUMMARY,
                               observation=json.dumps(observation, sort_keys=True))


def validate_live_action(action: Any, observation: dict[str, Any]) -> tuple[bool, str | None]:
    if not isinstance(action, dict) or action.get("type") != "RACE_STRATEGY":
        return False, "not a RACE_STRATEGY object"
    legal = set(observation["race_progress"]["legal_actions"])
    for driver in ("driver_a", "driver_b"):
        if action.get(driver) not in legal:
            return False, f"illegal {driver} action"
    order = action.get("team_order")
    if not isinstance(order, dict) or order.get("order") not in observation["team_orders"]["legal_team_orders"]:
        return False, "illegal or missing team order"
    return True, None


def action_key(action: dict[str, Any]) -> str:
    return f"{action['driver_a']}/{action['driver_b']}"


def evaluate_live_pair(source_row: dict[str, Any], records: list[dict[str, Any]]) -> dict[str, Any]:
    """Join two hash-bound calls to one frozen C6 pair and classify without changing C6."""
    pair = copy.deepcopy(source_row["pair"])
    by_condition = {record["condition"]: record for record in records}
    if set(by_condition) != {"a", "b"}:
        raise EvaluationError("live pair requires exactly condition a and b")
    condition_results = {}
    for label, source_key in (("a", "condition_a"), ("b", "condition_b")):
        record = by_condition[label]
        expected_hash = pair["public_evidence_diff"][
            "baseline_observation_hash" if label == "a" else "altered_observation_hash"]
        if record.get("source_observation_hash") != expected_hash:
            raise EvaluationError("live record does not match frozen observation")
        action = record.get("action") if record.get("valid_action") else None
        chosen = action_key(action) if action else None
        pair[source_key]["chief_action"] = chosen
        q_all = pair[source_key].get("q_all") or {}
        best = pair[source_key].get("reference_action")
        regret = None
        if chosen in q_all and best in q_all:
            regret = round(max(0.0, q_all[best] - q_all[chosen]), 6)
            if not math.isfinite(regret):
                raise EvaluationError("non-finite decision regret")
        condition_results[label] = {
            "chosen_action": chosen,
            "reference_action": best,
            "expected_team_points_regret": regret,
            "observation_hash": expected_hash,
            "record_status": record.get("status"),
        }
    classified = classify_adaptation(pair)
    return {"pair_id": pair["pair_id"], "probe_class": source_row["reference_classification"],
            "classification": classified["classification"], "reason": classified["reason"],
            "reference_reversal": classified["reference_reversal"],
            "conditions": condition_results,
            "regret_source": "C6 authoritative public-input rollout q_all point estimates",
            "regret_uncertainty": "reference preference CI retained in frozen pair; chosen-action regret has no CI"}
