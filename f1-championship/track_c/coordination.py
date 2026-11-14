"""Driver-local engineer recommendations and Chief coordination.

This module consumes public observations only. It has no simulator or
ChampionshipState dependency and cannot mutate race state.
"""

from __future__ import annotations

import copy
import hashlib
import json
import math
from pathlib import Path
from typing import Any, Callable, Protocol

NO_ENGINEER = "NO_ENGINEER"
ALIGNED = "ALIGNED"
CONFLICTING = "CONFLICTING"
MISCALIBRATED_CONFIDENCE = "MISCALIBRATED_CONFIDENCE"
REPLAY = "REPLAY"
CONDITIONS = {NO_ENGINEER, ALIGNED, CONFLICTING, MISCALIBRATED_CONFIDENCE, REPLAY}
ENGINEERS = {"engineer_a": ("driver_a", "Apex A"),
             "engineer_b": ("driver_b", "Apex B")}
HIDDEN_KEYS = {"seed", "events", "event_history", "cars", "future_track_status",
               "remaining_duration", "hidden_state"}
SCENARIO_FIXTURE = Path(__file__).with_name("fixtures") / "team_order_scenarios.json"


class EngineerProvider(Protocol):
    engineer_id: str

    def recommend(self, observation: dict[str, Any], condition: str) -> dict[str, Any]: ...


def build_engineer_observation(
    chief_observation: dict[str, Any], engineer_id: str,
) -> dict[str, Any]:
    """Project a public Chief observation to one driver's local view."""
    _reject_hidden(chief_observation)
    if engineer_id not in ENGINEERS:
        raise ValueError("unknown engineer")
    driver_key, driver_name = ENGINEERS[engineer_id]
    progress = chief_observation.get("race_progress")
    if not isinstance(progress, dict) or progress.get("status") in {"PRE_RACE", "CHAMPIONSHIP_COMPLETE"}:
        raise ValueError("engineer briefing requires an active race observation")
    drivers = progress.get("drivers")
    if not isinstance(drivers, dict) or driver_key not in drivers:
        raise ValueError("assigned driver is absent from the public race observation")

    # Integrated contract (v2, benchmark 2.0.0): the team and driver names come from the
    # team-local observation; v1 observations keep the original Apex naming.
    team = chief_observation.get("team", "Apex") if chief_observation.get("contract_version") == 2 else "Apex"
    driver_name = drivers[driver_key].get("name", driver_name)
    public_classification = []
    for entry in progress.get("classification", []):
        if entry.get("driver") == driver_name or entry.get("team") != team:
            public_classification.append(copy.deepcopy(entry))
    observation = {
        "schema_version": 1,
        "engineer_id": engineer_id,
        "assigned_driver": {"key": driver_key, "name": driver_name},
        "local_objective": "improve the assigned driver's expected race result",
        "current_track": copy.deepcopy(chief_observation.get("current_track")),
        "race_context": {
            "lap": progress.get("lap"),
            "laps_total": progress.get("laps_total"),
            "decision_index": progress.get("decision_index"),
            "decision_count": progress.get("decision_count"),
            "track_status": progress.get("track_status"),
            "assigned_driver_state": copy.deepcopy(drivers[driver_key]),
            "public_rivals": public_classification,
            "legal_actions": copy.deepcopy(progress.get("legal_actions", [])),
            **{key: copy.deepcopy(progress[key]) for key in (
                "laps_remaining", "segment_laps", "tyre_life_laps", "neutralization", "event_model")
               if key in progress},
        },
        "information_boundary": {
            "teammate_telemetry_visible": False,
            "future_events_visible": False,
            "hidden_simulator_state_visible": False,
        },
    }
    _reject_hidden(observation)
    return observation


class DeterministicMockEngineer:
    """No-model provider used for deterministic contract and ablation tests."""

    def __init__(self, engineer_id: str) -> None:
        if engineer_id not in ENGINEERS:
            raise ValueError("unknown engineer")
        self.engineer_id = engineer_id

    def recommend(self, observation: dict[str, Any], condition: str) -> dict[str, Any]:
        validate_engineer_observation(observation, self.engineer_id)
        if condition not in CONDITIONS - {NO_ENGINEER, REPLAY}:
            raise ValueError("mock engineer requires an active engineer condition")
        driver_key, driver_name = ENGINEERS[self.engineer_id]
        state = observation["race_context"]["assigned_driver_state"]
        if condition == ALIGNED:
            choice, confidence, calibration = "STAY", 0.72, "nominal"
        elif condition == CONFLICTING:
            choice = "PIT" if self.engineer_id == "engineer_a" else "STAY"
            confidence, calibration = 0.76, "nominal"
        else:
            choice = "PIT" if self.engineer_id == "engineer_a" else "STAY"
            confidence, calibration = 0.99, "intentionally_overconfident_fixture"
        tyre_age = state.get("tyre_age")
        position = state.get("position")
        recommendation = {
            "schema_version": 1,
            "engineer_id": self.engineer_id,
            "driver": {"key": driver_key, "name": driver_name},
            "proposed_action": {"type": "RACE_STRATEGY", "driver": driver_key,
                                "choice": choice},
            "expected_benefit": {"value": 1.5 if choice == "PIT" else 0.4,
                                 "unit": "synthetic_expected_points"},
            "confidence": confidence,
            "calibration": calibration,
            "evidence": [
                {"field": "assigned_driver.tyre_age", "observed_value": tyre_age,
                 "relevance": "public tyre age informs pit timing"},
                {"field": "assigned_driver.position", "observed_value": position,
                 "relevance": "public track position affects local opportunity cost"},
                {"field": "track_status",
                 "observed_value": observation["race_context"].get("track_status"),
                 "relevance": "current status changes the immediate pit window"},
            ],
            "reasoning_summary": (
                f"Recommend {choice} for {driver_name} from assigned-driver public evidence only."
            ),
        }
        validate_recommendation(recommendation, observation)
        return recommendation


class RecommendationReplay:
    """Record/replay provider keyed by the exact public local observation."""

    def __init__(self, engineer_id: str) -> None:
        if engineer_id not in ENGINEERS:
            raise ValueError("unknown engineer")
        self.engineer_id = engineer_id
        self._records: dict[str, dict[str, Any]] = {}

    def record(self, observation: dict[str, Any], recommendation: dict[str, Any]) -> None:
        validate_engineer_observation(observation, self.engineer_id)
        validate_recommendation(recommendation, observation)
        self._records[_observation_key(observation)] = copy.deepcopy(recommendation)

    def recommend(self, observation: dict[str, Any], condition: str) -> dict[str, Any]:
        del condition
        validate_engineer_observation(observation, self.engineer_id)
        key = _observation_key(observation)
        if key not in self._records:
            raise ValueError("no recorded recommendation for this observation")
        return copy.deepcopy(self._records[key])


def build_coordination_observation(
    chief_observation: dict[str, Any], condition: str,
    providers: dict[str, EngineerProvider] | None = None,
) -> dict[str, Any]:
    if condition not in CONDITIONS:
        raise ValueError("unknown coordination condition")
    _reject_hidden(chief_observation)
    recommendations = []
    if condition != NO_ENGINEER:
        if condition == REPLAY and providers is None:
            raise ValueError("replay condition requires recorded providers")
        active = providers or {engineer_id: DeterministicMockEngineer(engineer_id)
                               for engineer_id in ENGINEERS}
        if set(active) != set(ENGINEERS):
            raise ValueError("both Engineer A and Engineer B providers are required")
        for engineer_id in ("engineer_a", "engineer_b"):
            local = build_engineer_observation(chief_observation, engineer_id)
            recommendation = active[engineer_id].recommend(local, condition)
            validate_recommendation(recommendation, local)
            recommendations.append(recommendation)
    return {
        "schema_version": 1,
        "condition": condition,
        "chief_public_observation": copy.deepcopy(chief_observation),
        "recommendations": recommendations,
        "chief_authority": "recommendations are advisory; only the Chief final action may execute",
    }


class CoordinationRound:
    """Requires an explicit Chief decision before any submit callback can run."""

    def __init__(self, coordination_observation: dict[str, Any]) -> None:
        self.observation = copy.deepcopy(coordination_observation)
        self._decision: dict[str, Any] | None = None
        self._executed = False

    def chief_decide(self, final_action: dict[str, Any], reasoning_summary: str) -> dict[str, Any]:
        if self._decision is not None:
            raise ValueError("Chief decision already recorded")
        clean = _validate_chief_action(final_action)
        if not isinstance(reasoning_summary, str) or not reasoning_summary.strip():
            raise ValueError("Chief reasoning summary is required")
        acceptance = {}
        for recommendation in self.observation["recommendations"]:
            proposed = recommendation["proposed_action"]
            acceptance[recommendation["engineer_id"]] = (
                proposed["type"] == "RACE_STRATEGY"
                and clean[proposed["driver"]] == proposed["choice"]
            )
        self._decision = {
            "schema_version": 1,
            "final_action": clean,
            "recommendation_accepted": acceptance,
            "reasoning_summary": reasoning_summary,
        }
        return copy.deepcopy(self._decision)

    def execute(self, submit: Callable[[dict[str, Any]], Any]) -> Any:
        if self._decision is None:
            raise PermissionError("only a recorded Chief decision may execute")
        if self._executed:
            raise ValueError("Chief action already executed")
        self._executed = True
        return submit(copy.deepcopy(self._decision["final_action"]))


def validate_engineer_observation(observation: Any, engineer_id: str) -> None:
    if not isinstance(observation, dict) or observation.get("engineer_id") != engineer_id:
        raise ValueError("recommendation observation does not match engineer")
    if observation.get("assigned_driver", {}).get("key") != ENGINEERS[engineer_id][0]:
        raise ValueError("engineer received the wrong driver observation")
    _reject_hidden(observation)


def validate_recommendation(value: Any, observation: dict[str, Any]) -> None:
    required = {"schema_version", "engineer_id", "driver", "proposed_action",
                "expected_benefit", "confidence", "calibration", "evidence",
                "reasoning_summary"}
    if not isinstance(value, dict) or set(value) != required or value["schema_version"] != 1:
        raise ValueError("invalid recommendation fields")
    validate_engineer_observation(observation, value["engineer_id"])
    if value["driver"] != observation["assigned_driver"]:
        raise ValueError("recommendation driver does not match local observation")
    _validate_proposed_action(value["proposed_action"], value["driver"]["key"])
    benefit = value["expected_benefit"]
    if (not isinstance(benefit, dict) or set(benefit) != {"value", "unit"}
            or isinstance(benefit["value"], bool)
            or not isinstance(benefit["value"], (int, float))
            or not math.isfinite(benefit["value"])
            or not isinstance(benefit["unit"], str)):
        raise ValueError("invalid expected benefit")
    confidence = value["confidence"]
    if (isinstance(confidence, bool) or not isinstance(confidence, (int, float))
            or not math.isfinite(confidence) or not 0.0 <= confidence <= 1.0):
        raise ValueError("confidence must be finite and within [0, 1]")
    if not isinstance(value["calibration"], str) or not value["calibration"]:
        raise ValueError("calibration label is required")
    if not isinstance(value["evidence"], list) or not value["evidence"]:
        raise ValueError("recommendation evidence is required")
    for evidence in value["evidence"]:
        if (not isinstance(evidence, dict)
                or set(evidence) != {"field", "observed_value", "relevance"}
                or not isinstance(evidence["field"], str)
                or not isinstance(evidence["relevance"], str)):
            raise ValueError("invalid recommendation evidence")
    if not isinstance(value["reasoning_summary"], str) or not value["reasoning_summary"].strip():
        raise ValueError("reasoning summary is required")


def load_team_order_scenarios(path: Path = SCENARIO_FIXTURE) -> list[dict[str, Any]]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError("invalid team-order scenario fixture") from exc
    if (not isinstance(value, dict) or value.get("schema_version") != 1
            or value.get("data_status") != "synthetic_placeholder"
            or not isinstance(value.get("scenarios"), list)):
        raise ValueError("invalid team-order fixture header")
    for scenario in value["scenarios"]:
        if set(scenario) != {"id", "description", "public_state", "proposed_action"}:
            raise ValueError("invalid team-order scenario")
        _validate_team_order_action(scenario["proposed_action"])
    return copy.deepcopy(value["scenarios"])


def validate_team_order_action(action: Any) -> None:
    """Validate the fixture-only future team-order contract.

    Passing validation does not authorize submission to the current race engine.
    """
    _validate_team_order_action(action)


def _validate_proposed_action(action: Any, driver_key: str) -> None:
    if not isinstance(action, dict) or action.get("type") not in {"RACE_STRATEGY", "TEAM_ORDER"}:
        raise ValueError("unsupported proposed action")
    if action["type"] == "RACE_STRATEGY":
        if (set(action) != {"type", "driver", "choice"} or action["driver"] != driver_key
                or action["choice"] not in {"PIT", "STAY"}):
            raise ValueError("invalid race-strategy recommendation")
    else:
        _validate_team_order_action(action)


def _validate_team_order_action(action: Any) -> None:
    if (not isinstance(action, dict)
            or set(action) != {"type", "order", "favored_driver", "give_back"}
            or action["type"] != "TEAM_ORDER"
            or action["order"] not in {"HOLD", "SWAP", "RACE", "DEFEND"}
            or action["favored_driver"] not in {"driver_a", "driver_b", None}):
        raise ValueError("invalid future team-order action")
    give_back = action["give_back"]
    if give_back is not None:
        if (not isinstance(give_back, dict)
                or set(give_back) != {"condition", "deadline_lap"}
                or give_back["condition"] != "IF_NO_POSITION_GAIN"
                or isinstance(give_back["deadline_lap"], bool)
                or not isinstance(give_back["deadline_lap"], int)
                or give_back["deadline_lap"] <= 0):
            raise ValueError("invalid conditional give-back")


def _validate_chief_action(action: Any) -> dict[str, str]:
    if (not isinstance(action, dict) or set(action) != {"type", "driver_a", "driver_b"}
            or action.get("type") != "RACE_STRATEGY"
            or action.get("driver_a") not in {"PIT", "STAY"}
            or action.get("driver_b") not in {"PIT", "STAY"}):
        raise ValueError("invalid Chief race-strategy action")
    return dict(action)


def _observation_key(observation: dict[str, Any]) -> str:
    payload = json.dumps(observation, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _reject_hidden(value: Any) -> None:
    if isinstance(value, dict):
        forbidden = set(value) & HIDDEN_KEYS
        if forbidden:
            raise ValueError(f"hidden fields are not allowed: {sorted(forbidden)}")
        for child in value.values():
            _reject_hidden(child)
    elif isinstance(value, list):
        for child in value:
            _reject_hidden(child)
