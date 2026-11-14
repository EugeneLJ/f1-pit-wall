"""Track C Engineer runtime, validation, recording, replay, and usage metrics.

The live SDK dependency is imported only when live mode is explicitly invoked.
API keys are read from environment variables at call time and never serialized.
"""

from __future__ import annotations

import copy
import hashlib
import json
import math
import os
import time
from pathlib import Path
from typing import Any, Protocol

from .coordination import ENGINEERS, build_engineer_observation

DEFAULT_GEMINI_ENGINEER_MODEL = "gemini-3.5-flash-lite"
RECORD_SOURCES = {"LIVE_MODEL", "MOCK", "RECORDED_REPLAY", "MISSING", "INVALID"}
RUNTIME_CONDITIONS = {
    "CHIEF_ONLY", "GEMINI_LITE_ENGINEERS", "RECORDED_RECOMMENDATIONS",
    "CONFLICTING_LOCAL_RECOMMENDATIONS", "NOMINAL_CONFIDENCE_CONTROL",
    "HIGH_SELF_REPORTED_CONFIDENCE_CONTROL",
}
SECRET_NAMES = {"api_key", "gemini_api_key", "google_api_key", "authorization", "x-goog-api-key"}

RECOMMENDATION_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "engineer_id", "driver_id", "proposed_action", "supporting_evidence",
        "expected_local_benefit", "confidence", "reasoning_summary", "observation_hash",
    ],
    "properties": {
        "engineer_id": {"type": "string", "enum": sorted(ENGINEERS)},
        "driver_id": {"type": "string", "enum": ["driver_a", "driver_b"]},
        "proposed_action": {
            "type": "object", "additionalProperties": False,
            "required": ["type", "driver", "choice"],
            "properties": {
                "type": {"type": "string", "enum": ["RACE_STRATEGY"]},
                "driver": {"type": "string", "enum": ["driver_a", "driver_b"]},
                "choice": {"type": "string", "enum": ["PIT", "STAY"]},
            },
        },
        "supporting_evidence": {
            "type": "array", "minItems": 1,
            "items": {
                "type": "object", "additionalProperties": False,
                "required": ["field", "observed_value", "relevance"],
                "properties": {
                    "field": {"type": "string"},
                    "observed_value": {
                        "type": ["string", "number", "integer", "boolean", "null"]
                    },
                    "relevance": {"type": "string"},
                },
            },
        },
        "expected_local_benefit": {
            "type": "object", "additionalProperties": False,
            "required": ["value", "unit", "basis"],
            "properties": {
                "value": {"type": "number"}, "unit": {"type": "string"},
                "basis": {"type": "string"},
            },
        },
        "confidence": {
            "type": "object", "additionalProperties": False,
            "required": ["value", "kind"],
            "properties": {
                "value": {"type": "number", "minimum": 0, "maximum": 1},
                "kind": {"type": "string", "enum": ["self_reported"]},
            },
        },
        "reasoning_summary": {"type": "string"},
        "observation_hash": {"type": "string"},
    },
}


# Additive v2 contract for the integrated championship (benchmark 2.0.0): the pit choice is any
# legal compound action of the observation, and an Engineer may instead ask the Chief to
# prioritize its assigned driver (a team-order request; only the Chief can issue orders).
TEAM_ORDER_REQUESTS = ("PRIORITIZE_ASSIGNED_DRIVER", "NO_TEAM_ORDER")
RECOMMENDATION_SCHEMA_V2 = copy.deepcopy(RECOMMENDATION_SCHEMA)
RECOMMENDATION_SCHEMA_V2["properties"]["proposed_action"] = {
    "type": "object", "additionalProperties": False,
    "required": ["type", "driver"],
    "properties": {
        "type": {"type": "string", "enum": ["RACE_STRATEGY", "TEAM_ORDER"]},
        "driver": {"type": "string", "enum": ["driver_a", "driver_b"]},
        "choice": {"type": "string", "enum": ["STAY", "PIT_SOFT", "PIT_MEDIUM", "PIT_HARD"]},
        "order": {"type": "string", "enum": list(TEAM_ORDER_REQUESTS)},
    },
}


def schema_for(observation: dict[str, Any]) -> dict[str, Any]:
    return RECOMMENDATION_SCHEMA_V2 if observation.get("runtime_schema_version") == 2 else RECOMMENDATION_SCHEMA


class LiveTransport(Protocol):
    def generate(
        self, *, api_key: str, model: str, prompt: str,
        response_schema: dict[str, Any], sampling: dict[str, Any],
    ) -> dict[str, Any]: ...


class GoogleGenAITransport:
    """Lazy adapter for the official ``google-genai`` Python SDK."""

    def generate(
        self, *, api_key: str, model: str, prompt: str,
        response_schema: dict[str, Any], sampling: dict[str, Any],
    ) -> dict[str, Any]:
        try:
            from google import genai
            from google.genai import types
        except ImportError as exc:
            raise RuntimeError("live mode requires the optional google-genai package") from exc
        client = genai.Client(api_key=api_key)
        config = types.GenerateContentConfig(
            response_mime_type="application/json",
            response_json_schema=response_schema,
            temperature=sampling["temperature"],
            max_output_tokens=sampling["max_output_tokens"],
        )
        response = client.models.generate_content(model=model, contents=prompt, config=config)
        usage = getattr(response, "usage_metadata", None)
        return {
            "text": response.text,
            "model_revision": getattr(response, "model_version", None),
            "usage": {
                "input_tokens": getattr(usage, "prompt_token_count", None),
                "output_tokens": getattr(usage, "candidates_token_count", None),
                "total_tokens": getattr(usage, "total_token_count", None),
            },
            "estimated_cost_usd": None,
        }


def format_runtime_observation(
    chief_observation: dict[str, Any], engineer_id: str,
) -> dict[str, Any]:
    """Create a driver-local input and add only explicitly public team context."""
    local = build_engineer_observation(chief_observation, engineer_id)
    driver_id = local["assigned_driver"]["key"]
    team_context = chief_observation.get("team_context", {})
    if chief_observation.get("contract_version") == 2:
        local["runtime_schema_version"] = 2
        if not team_context:
            team_context = _integrated_team_context(chief_observation)
    if team_context and not isinstance(team_context, dict):
        raise ValueError("public team context must be an object")
    instructions = team_context.get("public_instructions", [])
    commitments = team_context.get("public_commitments", [])
    if not isinstance(instructions, list) or not isinstance(commitments, list):
        raise ValueError("public team instructions and commitments must be lists")
    local["public_team_context"] = {
        "instructions": copy.deepcopy(instructions),
        "assigned_driver_commitments": [
            copy.deepcopy(item) for item in commitments
            if isinstance(item, dict) and item.get("driver_id") == driver_id
        ],
    }
    return local


def _integrated_team_context(chief_observation: dict[str, Any]) -> dict[str, Any]:
    """Public team context of an integrated observation: the commitment roles of each driver
    (never the teammate's telemetry or the other Engineer's report)."""
    orders = chief_observation.get("team_orders") or {}
    commitment = orders.get("commitment")
    commitments = []
    if isinstance(commitment, dict):
        for role in ("promoted", "yielded"):
            commitments.append({"driver_id": commitment[role], "role": role,
                                "objective": commitment["objective"], "status": commitment["status"],
                                "deadline_lap": commitment["deadline_lap"]})
    return {"public_instructions": ["maximize the team's Constructors' points"],
            "public_commitments": commitments}


def observation_hash(observation: dict[str, Any]) -> str:
    payload = json.dumps(observation, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def validate_runtime_recommendation(
    value: Any, observation: dict[str, Any], engineer_id: str,
) -> dict[str, Any]:
    required = set(RECOMMENDATION_SCHEMA["required"])
    if not isinstance(value, dict) or set(value) != required:
        raise ValueError("invalid recommendation fields")
    driver_id = ENGINEERS[engineer_id][0]
    if value["engineer_id"] != engineer_id or value["driver_id"] != driver_id:
        raise ValueError("recommendation identity does not match provider")
    action = value["proposed_action"]
    if observation.get("runtime_schema_version") == 2:
        legal = observation["race_context"].get("legal_actions", [])
        valid = isinstance(action, dict) and action.get("driver") == driver_id and (
            (set(action) == {"type", "driver", "choice"} and action.get("type") == "RACE_STRATEGY"
             and action.get("choice") in legal)
            or (set(action) == {"type", "driver", "order"} and action.get("type") == "TEAM_ORDER"
                and action.get("order") in TEAM_ORDER_REQUESTS))
        if not valid:
            raise ValueError("invalid proposed action")
    elif (not isinstance(action, dict) or set(action) != {"type", "driver", "choice"}
            or action.get("type") != "RACE_STRATEGY" or action.get("driver") != driver_id
            or action.get("choice") not in {"PIT", "STAY"}):
        raise ValueError("invalid proposed action")
    if value["observation_hash"] != observation_hash(observation):
        raise ValueError("recommendation observation hash mismatch")
    evidence = value["supporting_evidence"]
    flattened = _flatten_observation(observation)
    if not isinstance(evidence, list) or not evidence:
        raise ValueError("supporting evidence is required")
    for item in evidence:
        if (not isinstance(item, dict)
                or set(item) != {"field", "observed_value", "relevance"}
                or item["field"] not in flattened
                or flattened[item["field"]] != item["observed_value"]
                or not isinstance(item["relevance"], str) or not item["relevance"].strip()):
            raise ValueError("evidence must quote an existing observation field exactly")
    benefit = value["expected_local_benefit"]
    if (not isinstance(benefit, dict) or set(benefit) != {"value", "unit", "basis"}
            or isinstance(benefit["value"], bool)
            or not isinstance(benefit["value"], (int, float))
            or not math.isfinite(benefit["value"])
            or not all(isinstance(benefit[key], str) and benefit[key].strip()
                       for key in ("unit", "basis"))):
        raise ValueError("invalid expected local benefit")
    confidence = value["confidence"]
    if (not isinstance(confidence, dict) or set(confidence) != {"value", "kind"}
            or confidence["kind"] != "self_reported"
            or isinstance(confidence["value"], bool)
            or not isinstance(confidence["value"], (int, float))
            or not math.isfinite(confidence["value"])
            or not 0 <= confidence["value"] <= 1):
        raise ValueError("confidence must be finite self-reported confidence")
    if not isinstance(value["reasoning_summary"], str) or not value["reasoning_summary"].strip():
        raise ValueError("reasoning summary is required")
    return copy.deepcopy(value)


class MockRuntimeProvider:
    def __init__(self, engineer_id: str, *, confidence: float = 0.7,
                 proposal: str = "local_pit") -> None:
        if engineer_id not in ENGINEERS:
            raise ValueError("unknown engineer")
        if not 0 <= confidence <= 1:
            raise ValueError("invalid mock confidence")
        if proposal not in ("local_pit", "claim_priority"):
            raise ValueError("unknown mock proposal mode")
        self.engineer_id = engineer_id
        self.confidence = confidence
        self.proposal = proposal

    def recommend(self, observation: dict[str, Any]) -> dict[str, Any]:
        driver_id = ENGINEERS[self.engineer_id][0]
        state = observation["race_context"]["assigned_driver_state"]
        tyre_age = state.get("tyre_age")
        choice = "PIT" if isinstance(tyre_age, (int, float)) and tyre_age >= 12 else "STAY"
        proposed = {"type": "RACE_STRATEGY", "driver": driver_id, "choice": choice}
        if observation.get("runtime_schema_version") == 2:
            context = observation["race_context"]
            if self.proposal == "claim_priority":
                proposed = {"type": "TEAM_ORDER", "driver": driver_id, "order": "PRIORITIZE_ASSIGNED_DRIVER"}
            elif choice == "PIT":
                remaining = context.get("laps_remaining", 0)
                compound = "SOFT" if remaining <= 6 else "MEDIUM" if remaining <= 14 else "HARD"
                if state.get("compounds_used") == [compound]:
                    compound = "MEDIUM" if compound != "MEDIUM" else "HARD"
                proposed["choice"] = f"PIT_{compound}"
        value = {
            "engineer_id": self.engineer_id,
            "driver_id": driver_id,
            "proposed_action": proposed,
            "supporting_evidence": [{
                "field": "race_context.assigned_driver_state.tyre_age",
                "observed_value": tyre_age,
                "relevance": "public tyre age informs the assigned driver's local pit trade-off",
            }],
            "expected_local_benefit": {
                "value": 0.0, "unit": "synthetic_local_points_delta",
                "basis": "deterministic mock fixture, not a calibrated expectation",
            },
            "confidence": {"value": self.confidence, "kind": "self_reported"},
            "reasoning_summary": (f"Local public tyre evidence supports {proposed.get('choice', proposed.get('order'))} "
                                  f"for {driver_id}."),
            "observation_hash": observation_hash(observation),
        }
        return validate_runtime_recommendation(value, observation, self.engineer_id)


class GeminiEngineerProvider:
    def __init__(
        self, engineer_id: str, *, model: str = DEFAULT_GEMINI_ENGINEER_MODEL,
        transport: LiveTransport | None = None, temperature: float = 0.0,
        max_output_tokens: int = 1024, retries: int = 0,
    ) -> None:
        if engineer_id not in ENGINEERS:
            raise ValueError("unknown engineer")
        if retries < 0 or retries > 2:
            raise ValueError("retries must be between zero and two")
        self.engineer_id = engineer_id
        self.model = model
        self.transport = transport or GoogleGenAITransport()
        self.sampling = {"temperature": temperature, "max_output_tokens": max_output_tokens}
        self.retries = retries
        self.prompt_template = (
            "You are {engineer_id}, responsible only for {driver_id}. Use only the supplied "
            "driver-local public observation. Do not invent telemetry or future events. Return "
            "one JSON recommendation matching the supplied schema. Confidence is self-reported, "
            "not a calibrated probability. Set observation_hash to exactly {observation_hash} and "
            "quote evidence fields by their dotted path in the observation with the exact value."
            "\nOBSERVATION={observation}"
        )

    def recommend(self, observation: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
        api_key = os.environ.get("GOOGLE_API_KEY") or os.environ.get("GEMINI_API_KEY")
        if not api_key:
            raise RuntimeError("live Gemini mode requires GOOGLE_API_KEY or GEMINI_API_KEY")
        driver_id = ENGINEERS[self.engineer_id][0]
        prompt = self.prompt_template.format(
            engineer_id=self.engineer_id, driver_id=driver_id,
            observation_hash=observation_hash(observation),
            observation=json.dumps(observation, sort_keys=True, allow_nan=False),
        )
        started = time.monotonic()
        last_error: Exception | None = None
        for attempt in range(self.retries + 1):
            try:
                response = self.transport.generate(
                    api_key=api_key, model=self.model, prompt=prompt,
                    response_schema=schema_for(observation), sampling=self.sampling,
                )
                parsed = json.loads(response["text"])
                recommendation = validate_runtime_recommendation(
                    parsed, observation, self.engineer_id
                )
                metadata = {
                    "provider": "google_genai",
                    "model": self.model,
                    "model_revision": response.get("model_revision"),
                    "prompt_hash": hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
                    "sampling": copy.deepcopy(self.sampling),
                    "usage": copy.deepcopy(response.get("usage", {})),
                    "latency_ms": round((time.monotonic() - started) * 1000, 3),
                    "retries": attempt,
                    "estimated_cost_usd": response.get("estimated_cost_usd"),
                }
                return recommendation, metadata
            except Exception as exc:
                last_error = exc
        detail = str(last_error)[:200] if last_error is not None else ""
        raise RuntimeError(f"Gemini recommendation failed: {type(last_error).__name__}: {detail}") from last_error


class ImmutableRecommendationStore:
    """Append-only hash-chained JSONL records with exact-observation replay."""

    def __init__(self, path: Path) -> None:
        self.path = path

    def append(self, record: dict[str, Any]) -> dict[str, Any]:
        sanitized = redact_secrets(copy.deepcopy(record))
        existing = self.read_all()
        sanitized["previous_record_hash"] = existing[-1]["record_hash"] if existing else None
        sanitized.pop("record_hash", None)
        sanitized["record_hash"] = _hash_record(sanitized)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        descriptor = os.open(self.path, os.O_APPEND | os.O_CREAT | os.O_WRONLY, 0o600)
        try:
            os.write(descriptor, (json.dumps(sanitized, sort_keys=True) + "\n").encode("utf-8"))
        finally:
            os.close(descriptor)
        return copy.deepcopy(sanitized)

    def read_all(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        records = []
        previous = None
        for line in self.path.read_text(encoding="utf-8").splitlines():
            record = json.loads(line)
            supplied = record.pop("record_hash")
            if record.get("previous_record_hash") != previous or _hash_record(record) != supplied:
                raise ValueError("recommendation record chain failed validation")
            record["record_hash"] = supplied
            previous = supplied
            records.append(record)
        return records

    def replay(self, engineer_id: str, observation: dict[str, Any]) -> dict[str, Any]:
        target = observation_hash(observation)
        matches = [record for record in self.read_all()
                   if record.get("engineer_id") == engineer_id
                   and record.get("observation_hash") == target
                   and record.get("status") == "VALID"]
        if not matches:
            raise KeyError("no valid recorded recommendation for exact observation")
        result = copy.deepcopy(matches[-1])
        result["source"] = "RECORDED_REPLAY"
        return result


def build_runtime_record(
    *, engineer_id: str, observation: dict[str, Any], source: str,
    recommendation: dict[str, Any] | None, metadata: dict[str, Any] | None = None,
    error: str | None = None,
) -> dict[str, Any]:
    if source not in RECORD_SOURCES:
        raise ValueError("unknown recommendation source")
    status = "VALID" if recommendation is not None else ("MISSING" if source == "MISSING" else "INVALID")
    if recommendation is not None:
        recommendation = validate_runtime_recommendation(recommendation, observation, engineer_id)
    return redact_secrets({
        "record_version": 1,
        "engineer_id": engineer_id,
        "observation_hash": observation_hash(observation),
        "source": source,
        "status": status,
        "recommendation": copy.deepcopy(recommendation),
        "runtime": copy.deepcopy(metadata or {}),
        "error": error,
    })


def run_provider_safely(
    provider: Any, observation: dict[str, Any], *, source: str,
) -> dict[str, Any]:
    """Return an explicit invalid record; never repair or fabricate a response."""
    engineer_id = provider.engineer_id
    try:
        result = provider.recommend(observation)
        if isinstance(result, tuple):
            recommendation, metadata = result
        else:
            recommendation, metadata = result, {}
        return build_runtime_record(
            engineer_id=engineer_id, observation=observation, source=source,
            recommendation=recommendation, metadata=metadata,
        )
    except Exception as exc:  # provider/network/schema boundary
        detail = str(exc)[:300]
        for name in ("GOOGLE_API_KEY", "GEMINI_API_KEY"):
            secret = os.environ.get(name)
            if secret:
                detail = detail.replace(secret, "[REDACTED]")
        return build_runtime_record(
            engineer_id=engineer_id, observation=observation, source="INVALID",
            recommendation=None, error=type(exc).__name__,
            metadata={"requested_source": source, "error_detail": detail},
        )


class EngineerRuntimeHarness:
    """Collect two advisory reports without granting state mutation authority."""

    def __init__(
        self, *, live_providers: dict[str, Any] | None = None,
        store: ImmutableRecommendationStore | None = None,
    ) -> None:
        self.live_providers = live_providers
        self.store = store

    def collect(self, chief_observation: dict[str, Any], condition: str) -> list[dict[str, Any]]:
        if condition not in RUNTIME_CONDITIONS:
            raise ValueError("unknown runtime condition")
        if condition == "CHIEF_ONLY":
            return []
        records = []
        for engineer_id in ("engineer_a", "engineer_b"):
            observation = format_runtime_observation(chief_observation, engineer_id)
            if condition == "RECORDED_RECOMMENDATIONS":
                if self.store is None:
                    raise ValueError("recorded condition requires a store")
                record = self.store.replay(engineer_id, observation)
            elif condition == "GEMINI_LITE_ENGINEERS":
                if self.live_providers is None or engineer_id not in self.live_providers:
                    record = build_runtime_record(
                        engineer_id=engineer_id, observation=observation, source="MISSING",
                        recommendation=None, error="live_provider_not_configured",
                    )
                else:
                    record = run_provider_safely(
                        self.live_providers[engineer_id], observation, source="LIVE_MODEL"
                    )
            else:
                confidence = 0.95 if condition == "HIGH_SELF_REPORTED_CONFIDENCE_CONTROL" else 0.7
                proposal = ("claim_priority" if condition == "CONFLICTING_LOCAL_RECOMMENDATIONS"
                            and observation.get("runtime_schema_version") == 2 else "local_pit")
                provider = MockRuntimeProvider(engineer_id, confidence=confidence, proposal=proposal)
                record = run_provider_safely(provider, observation, source="MOCK")
                record["runtime"]["confidence_condition"] = (
                    "high_self_reported_uncalibrated"
                    if confidence == 0.95 else "nominal_not_empirically_calibrated"
                )
            if self.store is not None and record["source"] != "RECORDED_REPLAY":
                record = self.store.append(record)
            records.append(record)
        return records


def measure_engineer_usage(
    records: list[dict[str, Any]], *, delivered_record_hashes: set[str],
    explicitly_referenced_record_hashes: set[str], chief_action: dict[str, Any] | None,
    outcome: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    measurements = []
    for record in records:
        recommendation = record.get("recommendation")
        available = record.get("status") == "VALID" and recommendation is not None
        record_hash = record.get("record_hash")
        delivered = available and record_hash in delivered_record_hashes
        referenced = delivered and record_hash in explicitly_referenced_record_hashes
        matches = None
        if available and chief_action is not None:
            proposed = recommendation["proposed_action"]
            if "choice" in proposed:
                matches = chief_action.get(proposed["driver"]) == proposed["choice"]
        measurements.append({
            "engineer_id": record.get("engineer_id"),
            "recommendation_available": available,
            "delivered_to_chief": delivered,
            "explicitly_referenced_or_consumed": referenced,
            "consumption_observability": (
                "explicit_reference" if referenced else "not_observed_do_not_infer_ignored"
            ),
            "chief_action_matches": matches,
            "chief_action_differs": None if matches is None else not matches,
            "decision_outcome": copy.deepcopy(outcome),
        })
    return measurements


def redact_secrets(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: ("[REDACTED]" if key.lower() in SECRET_NAMES else redact_secrets(child))
            for key, child in value.items()
        }
    if isinstance(value, list):
        return [redact_secrets(child) for child in value]
    return value


def _flatten_observation(value: Any, prefix: str = "") -> dict[str, Any]:
    flattened = {}
    if isinstance(value, dict):
        for key, child in value.items():
            path = f"{prefix}.{key}" if prefix else key
            flattened.update(_flatten_observation(child, path))
    elif not isinstance(value, list):
        flattened[prefix] = value
    return flattened


def _hash_record(record: dict[str, Any]) -> str:
    payload = json.dumps(record, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
