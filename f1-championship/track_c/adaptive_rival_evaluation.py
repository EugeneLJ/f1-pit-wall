"""C6 adaptive-rival evidence classification over C4-verified decisions.

Policy identity is never treated as observable.  A response probe is eligible only
after a rival action is present in the Chief's public observation.  Classification
also requires paired Chief actions and equal-information reference evidence.
"""

from __future__ import annotations

import copy
import gzip
import json
import math
from pathlib import Path
from typing import Any

from .coordination_evaluation import EvaluationError, verify_bundle

CLASSIFICATIONS = {
    "FAILURE_TO_ADAPT", "OVERREACTION", "INCORRECT_ADAPTATION", "APPROPRIATE_ADAPTATION",
    "NO_ADAPTATION_NEEDED", "NEAR_TIE", "INCONCLUSIVE", "INSUFFICIENT_EVIDENCE",
}


def load_verified_bundle(path: Path | str) -> dict[str, Any]:
    path = Path(path)
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "rt", encoding="utf-8") as handle:
        bundle = json.load(handle)
    verify_bundle(bundle)
    return bundle


def public_rival_evidence(observation: dict[str, Any], own_team: str,
                          rival_team: str | None = None) -> dict[str, Any]:
    """Extract only evidence already visible in one sealed Chief observation."""
    progress = observation.get("race_progress") or {}
    own_drivers = {row.get("name") for row in (progress.get("drivers") or {}).values()}
    classification = progress.get("classification", [])
    rival_entries = [{k: row.get(k) for k in ("driver", "team", "position", "compound", "tyre_age")}
                     for row in classification
                     if row.get("team") != own_team and (rival_team is None or row.get("team") == rival_team)]
    rival_drivers = {row["driver"] for row in rival_entries}
    pit_history = []
    for event in progress.get("public_pit_history", []):
        visible_stops = [copy.deepcopy(stop) for stop in event.get("stops", [])
                         if stop.get("driver") not in own_drivers
                         and (rival_team is None or stop.get("driver") in rival_drivers)]
        if visible_stops:
            pit_history.append({"decision": event.get("decision"), "stops": visible_stops})
    return {"track_status": progress.get("track_status"), "decision_index": progress.get("decision_index"),
            "rival_public_classification": rival_entries, "visible_rival_pit_history": pit_history,
            "has_visible_rival_action": bool(pit_history),
            "hidden_policy_identity_visible": False}


def audit_bundle_visibility(bundle: dict[str, Any], team: str,
                            rival_team: str | None = None) -> dict[str, Any]:
    """Inventory visible rival evidence; this is not a failure attribution."""
    verify_bundle(bundle)
    rows = []
    previous_count = 0
    previous_race = None
    for decision in bundle["decisions"]:
        if decision["team"] != team or decision["chief_observation"].get("decision_type") != "RACE_STRATEGY":
            continue
        observation = decision["chief_observation"]
        race_index = observation.get("championship", {}).get("race_index")
        if race_index is None:
            race_index = observation.get("race_progress", {}).get("race")
        if race_index != previous_race:
            previous_count = 0
            previous_race = race_index
        evidence = public_rival_evidence(observation, team, rival_team)
        count = sum(len(event["stops"]) for event in evidence["visible_rival_pit_history"])
        rows.append({"tick_id": decision["tick_id"], "observation_hash": _observation_hash(decision),
                     "new_visible_rival_stops": max(0, count - previous_count), **evidence})
        previous_count = count
    return {"team": team, "rival_team": rival_team, "race_decisions": len(rows),
            "decisions_after_any_visible_rival_pit": sum(row["has_visible_rival_action"] for row in rows),
            "new_visible_rival_stops": sum(row["new_visible_rival_stops"] for row in rows), "rows": rows}


def _observation_hash(decision: dict[str, Any]) -> str:
    import hashlib
    text = json.dumps(decision["chief_observation"], sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(text.encode()).hexdigest()


def classify_adaptation(pair: dict[str, Any], near_tie_threshold: float = 0.5) -> dict[str, Any]:
    """Classify one matched public-evidence pair without reading realized futures."""
    required = {"pair_id", "public_evidence_diff", "condition_a", "condition_b"}
    if required - set(pair):
        raise EvaluationError("adaptive pair is incomplete")
    if pair.get("uses_hidden_policy_as_observation"):
        return _result(pair, "INSUFFICIENT_EVIDENCE", "hidden rival policy is not public evidence")
    provenance = pair.get("reference_provenance")
    if not isinstance(provenance, dict):
        return _result(pair, "INSUFFICIENT_EVIDENCE", "reference provenance is missing")
    declarations = [provenance[key] for key in
                    ("future_info", "uses_future_realization", "realized_future_used_as_observation")
                    if key in provenance]
    if not declarations:
        return _result(pair, "INSUFFICIENT_EVIDENCE", "future-information declaration is missing")
    if any(value is not False for value in declarations):
        return _result(pair, "INSUFFICIENT_EVIDENCE", "reference uses or ambiguously declares future information")
    evidence = pair["public_evidence_diff"]
    if not evidence.get("visible_before_chief_decision"):
        return _result(pair, "INSUFFICIENT_EVIDENCE", "rival change was not yet observable")
    a, b = pair["condition_a"], pair["condition_b"]
    if any(key not in side for side in (a, b) for key in ("reference_action", "reference_gap")):
        return _result(pair, "INCONCLUSIVE", "equal-information reference missing")
    gaps = [a["reference_gap"], b["reference_gap"]]
    if any(isinstance(x, bool) or not isinstance(x, (int, float)) or not math.isfinite(x) for x in gaps):
        raise EvaluationError("reference gaps must be finite")
    reversal = a["reference_action"] != b["reference_action"]
    if min(gaps) <= near_tie_threshold:
        return _result(pair, "NEAR_TIE", "reference preference is not separated", reversal=reversal)
    if a.get("chief_action") is None or b.get("chief_action") is None:
        return _result(pair, "INSUFFICIENT_EVIDENCE", "paired Chief actions were not run", reversal=reversal)
    changed = a["chief_action"] != b["chief_action"]
    correct_a = a["chief_action"] == a["reference_action"]
    correct_b = b["chief_action"] == b["reference_action"]
    if reversal:
        if correct_a and correct_b:
            label, reason = "APPROPRIATE_ADAPTATION", "Chief follows both separated references"
        elif not changed:
            label, reason = "FAILURE_TO_ADAPT", "reference reverses but Chief action does not"
        else:
            label, reason = "INCORRECT_ADAPTATION", "Chief changes action but not to both references"
    elif changed and not (correct_a and correct_b):
        label, reason = "OVERREACTION", "reference is stable but Chief changes to a worse action"
    elif correct_a and correct_b:
        label, reason = "NO_ADAPTATION_NEEDED", "reference and Chief action are stable"
    else:
        label, reason = "INCONCLUSIVE", "stable reference but paired regret evidence is incomplete"
    return _result(pair, label, reason, reversal=reversal)


def _result(pair: dict[str, Any], classification: str, reason: str,
            reversal: bool | None = None) -> dict[str, Any]:
    if classification not in CLASSIFICATIONS:
        raise AssertionError(classification)
    return {"pair_id": pair["pair_id"], "classification": classification, "reason": reason,
            "reference_reversal": reversal, "public_evidence": copy.deepcopy(pair["public_evidence_diff"]),
            "condition_a": copy.deepcopy(pair["condition_a"]),
            "condition_b": copy.deepcopy(pair["condition_b"]),
            "reference_provenance": copy.deepcopy(pair.get("reference_provenance")),
            "result_kind": pair.get("result_kind", "SYNTHETIC_DIAGNOSTIC_PROBE")}
