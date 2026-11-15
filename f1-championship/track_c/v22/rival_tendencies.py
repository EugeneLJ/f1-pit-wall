"""Isolated M2 hidden rival tendencies and public-history inference.

No M1 pace mode, M3 proximity calculation, M4 stewarding, M5 order, or M6
compliance is implemented here. The owner supplies resolved public events and
legal-action value distributions; this module never exposes the actual assignment.
"""

from __future__ import annotations

import copy
import json
import math
from pathlib import Path
from typing import Any

from .common import categorical, finite, normal, reject_public_secrets, validate_seed

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "v22_m2.json"
REACTIONS = ("INHERIT_BASELINE", "ATTACK", "DEFEND", "NO_ATTACK")


def load_model() -> dict[str, Any]:
    model = json.loads(FIXTURE.read_text(encoding="utf-8"))
    if model.get("schema_version") != 1 or model.get("data_status") != "synthetic_only" or model["sources"]:
        raise ValueError("M2 requires an unsourced synthetic fixture")
    types = tuple(model["types"])
    if types != ("DEFENDER", "OPPORTUNIST", "CONSERVATIVE"):
        raise ValueError("M2 type order must remain stable")
    weights = tuple(model["prior"][kind]["value"] for kind in types)
    if any(weight <= 0 for weight in weights) or not math.isclose(sum(weights), 1.0):
        raise ValueError("M2 prior must be positive and normalized")
    events = model["reaction_observation_confusion"]
    for expected in REACTIONS:
        probabilities = events[f"expected_{expected}"]
        if set(probabilities) != set(REACTIONS) | {"provenance"}:
            raise ValueError("reaction observation model is incomplete")
        if not math.isclose(sum(probabilities[reaction] for reaction in REACTIONS), 1.0):
            raise ValueError("reaction observation probabilities must sum to one")
    return copy.deepcopy(model)


def _context(context: dict[str, Any]) -> dict[str, Any]:
    required = {"car", "m3_active", "defence_applicable", "attack_legal", "gap_ahead", "lap_index"}
    result_fields = {"event_id", "observed_reaction", "lap_residual"}
    if (not isinstance(context, dict) or not required <= set(context)
            or set(context) - required - result_fields):
        raise ValueError("M2 reaction context fields are incomplete or unrecognized")
    if not isinstance(context["car"], str) or not context["car"]:
        raise ValueError("M2 car identifier is required")
    for name in ("m3_active", "defence_applicable", "attack_legal"):
        if not isinstance(context[name], bool):
            raise ValueError(f"M2 {name} must be supplied as a boolean")
    if context["gap_ahead"] is not None:
        finite(context["gap_ahead"], minimum=0.0)
    if isinstance(context["lap_index"], bool) or not isinstance(context["lap_index"], int) or context["lap_index"] < 0:
        raise ValueError("M2 public event lap index must be a non-negative integer")
    return copy.deepcopy(context)


def draw_tendency(race_seed: int, race_id: str, car: str, model: dict[str, Any] | None = None) -> str:
    """Private per-race assignment; the caller must not serialize its return value."""
    validate_seed(race_seed)
    if not isinstance(race_id, str) or not race_id or not isinstance(car, str) or not car:
        raise ValueError("race/car identity is required")
    model = model or load_model()
    types = tuple(model["types"])
    weights = tuple(model["prior"][kind]["value"] for kind in types)
    return categorical(race_seed, types, weights, model["stream_version"], "type", race_id, car)


def reaction(tendency: str, context: dict[str, Any], model: dict[str, Any] | None = None) -> str:
    """Resolve an intent directive only; it is not an attack/pass/outcome guarantee."""
    model = model or load_model()
    if tendency not in model["types"]:
        raise ValueError("unknown hidden rival tendency")
    context = _context(context)
    if tendency == "DEFENDER" and context["defence_applicable"]:
        return "DEFEND"
    if tendency == "OPPORTUNIST" and context["m3_active"] and context["attack_legal"]:
        return "ATTACK"
    if (tendency == "CONSERVATIVE" and context["gap_ahead"] is not None
            and context["gap_ahead"] > finite(model["conservative_gap_threshold_sec"])):
        # The owner may still use baseline actions, but must suppress an attack.
        return "NO_ATTACK"
    return "INHERIT_BASELINE"


def residual_mean(tendency: str, context: dict[str, Any], model: dict[str, Any]) -> float:
    context = _context(context)
    directive = reaction(tendency, context, model)
    if directive == "DEFEND":
        return model["lap_residual_seconds"]["defending_offset_sec"]["value"]
    if directive == "ATTACK":
        return model["lap_residual_seconds"]["attacking_offset_sec"]["value"]
    if tendency == "CONSERVATIVE":
        return model["lap_residual_seconds"]["conservative_offset_sec"]["value"]
    return 0.0


def observable_lap(race_seed: int, race_id: str, tendency: str, context: dict[str, Any],
                   model: dict[str, Any] | None = None) -> dict[str, Any]:
    """Public resolved event produced by the authoritative event owner/replay."""
    model = model or load_model()
    context = _context(context)
    directive = reaction(tendency, context, model)
    observation = model["reaction_observation_confusion"][f"expected_{directive}"]
    observed = categorical(
        race_seed, REACTIONS, tuple(observation[item] for item in REACTIONS),
        model["stream_version"], "reaction-observation", race_id, context["car"], context["lap_index"],
    )
    residual = residual_mean(tendency, context, model)
    sd = model["lap_residual_seconds"]["observation_sd_sec"]["value"]
    residual += sd * normal(race_seed, model["stream_version"], "lap-signal", race_id,
                           context["car"], context["lap_index"])
    return {
        "event_id": f"{race_id}:{context['car']}:{context['lap_index']}",
        "car": context["car"],
        "m3_active": context["m3_active"],
        "defence_applicable": context["defence_applicable"],
        "attack_legal": context["attack_legal"],
        "gap_ahead": context["gap_ahead"],
        "lap_index": context["lap_index"],
        "observed_reaction": observed,
        "lap_residual": round(residual, 12),
    }


def _public_event(event: dict[str, Any], model: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(event, dict) or not isinstance(event.get("event_id"), str) or not event["event_id"]:
        raise ValueError("public M2 event_id is required")
    _context(event)
    if event["observed_reaction"] not in REACTIONS:
        raise ValueError("unrecognized public reaction")
    finite(event["lap_residual"])
    return copy.deepcopy(event)


def posterior(prior: dict[str, float], events: list[dict[str, Any]],
              model: dict[str, Any] | None = None) -> dict[str, float]:
    """Bayes update from actual public evidence using one joint reaction/pace factor."""
    model = model or load_model()
    types = tuple(model["types"])
    logs = {}
    for kind in types:
        probability = finite(prior.get(kind), minimum=0.0)
        logs[kind] = math.log(probability) if probability > 0 else -math.inf
    if not math.isclose(sum(prior[kind] for kind in types), 1.0):
        raise ValueError("tendency prior must sum to one")
    seen = set()
    sd = model["lap_residual_seconds"]["observation_sd_sec"]["value"]
    for event in events:
        event = _public_event(event, model)
        if event["event_id"] in seen:
            raise ValueError("duplicate public M2 evidence event")
        seen.add(event["event_id"])
        for kind in types:
            expected = reaction(kind, event, model)
            likelihood = model["reaction_observation_confusion"][f"expected_{expected}"][event["observed_reaction"]]
            delta = event["lap_residual"] - residual_mean(kind, event, model)
            pace_log = -0.5 * (delta / sd) ** 2 - math.log(sd * math.sqrt(2.0 * math.pi))
            logs[kind] += math.log(likelihood) + pace_log
    maximum = max(logs.values())
    if maximum == -math.inf or any(math.isnan(value) for value in logs.values()):
        raise ValueError("public M2 evidence is incompatible with the published model")
    weights = {kind: math.exp(value - maximum) for kind, value in logs.items()}
    total = sum(weights.values())
    return {kind: weights[kind] / total for kind in types}


def public_projection(prior: dict[str, float], events: list[dict[str, Any]],
                      model: dict[str, Any] | None = None) -> dict[str, Any]:
    """Return causal public evidence and derived belief, never the hidden type."""
    model = model or load_model()
    belief = posterior(prior, events, model)
    output = {
        "schema_version": 1,
        "m2_enabled": True,
        "prior": {kind: prior[kind] for kind in model["types"]},
        "evidence": [_public_event(event, model) for event in events],
        "posterior": belief,
        "interpretation": "derived public-history belief, not the hidden rival type or a policy identifier",
        "uncertainty_model": "joint reaction and public lap-residual likelihood",
    }
    reject_public_secrets(output)
    return output


def disabled_projection() -> dict[str, Any]:
    output = {"schema_version": 1, "m2_enabled": False, "effects": "none"}
    reject_public_secrets(output)
    return output


def expected_values(belief: dict[str, float], action_values: dict[str, dict[str, dict[str, float]]],
                    model: dict[str, Any] | None = None) -> dict[str, Any]:
    """Evaluate every owner-declared legal action with near-tie-first evidence rules.

    action_values[a][tendency] requires finite {mean, se}; the owner vouches for its
    legal action set, information cutoff, continuation, and value provenance.
    """
    model = model or load_model()
    types = tuple(model["types"])
    if set(belief) != set(types) or not math.isclose(sum(belief.values()), 1.0):
        raise ValueError("invalid posterior for M2 decision evaluation")
    if not isinstance(action_values, dict) or not action_values:
        raise ValueError("M2 legal action values are required")
    rows = []
    for action in sorted(action_values):
        if not isinstance(action, str) or not action:
            raise ValueError("M2 legal action identifiers must be strings")
        by_type = action_values[action]
        if not isinstance(by_type, dict) or set(by_type) != set(types):
            raise ValueError("every legal action requires a value for every hypothetical type")
        mean = 0.0
        estimation_variance = 0.0
        second_moment = 0.0
        for kind in types:
            value = by_type[kind]
            if not isinstance(value, dict) or set(value) != {"mean", "se"}:
                raise ValueError("each type value requires exactly mean and se")
            mu = finite(value["mean"])
            se = finite(value["se"], minimum=0.0)
            mean += belief[kind] * mu
            estimation_variance += belief[kind] * se * se
            second_moment += belief[kind] * (se * se + mu * mu)
        variance = max(0.0, second_moment - mean * mean)
        rows.append({"action": action, "mean": mean,
                     "standard_error": math.sqrt(estimation_variance),
                     "predictive_sd": math.sqrt(variance)})
    rows.sort(key=lambda row: (-row["mean"], row["action"]))
    chosen, alternative = rows[0], rows[1] if len(rows) > 1 else None
    delta = None if alternative is None else chosen["mean"] - alternative["mean"]
    difference_se = (math.sqrt(chosen["standard_error"] ** 2 + alternative["standard_error"] ** 2)
                     if alternative is not None else 0.0)
    threshold = finite(model["decision_gate"]["near_tie_threshold"])
    z = finite(model["decision_gate"]["z95"])
    if alternative is None:
        status = "SEPARATED"
    elif abs(delta) <= threshold:
        status = "NEAR_TIE"
    elif abs(delta) - z * difference_se <= threshold:
        status = "UNCERTAIN"
    else:
        status = "SEPARATED"
    output = {
        "classification": status,
        "chosen_action": chosen["action"],
        "runner_up_action": alternative["action"] if alternative else None,
        "estimated_difference": delta,
        "paired_standard_error": difference_se,
        "near_tie_threshold": threshold,
        "values": rows,
        "partial_observability": "posterior mixture over all hidden types; not a lookup into the live assignment",
        "information_access": "public-history posterior and owner-declared equal-public-information values only",
    }
    reject_public_secrets(output)
    return output
