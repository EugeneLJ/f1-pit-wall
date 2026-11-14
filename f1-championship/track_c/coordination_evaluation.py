"""C4 coordination evaluation over integrated journals and Track C records.

This module is deliberately analysis-only.  It verifies evidence produced by the
authoritative engine, but never advances race state or invents a counterfactual.
Strategic failure labels require a positive equal-information team-points regret
whose confidence interval excludes the configured near-tie threshold.
"""

from __future__ import annotations

import copy
import hashlib
import json
import math
from collections import Counter, defaultdict
from typing import Any, Iterable

from f1pitwall.integrated.verify import verify_chain as verify_journal_chain
from f1pitwall.journal import canonical, observation_hash

ACTUAL_KINDS = {"ACTUAL_MODEL"}
CONTROL_KINDS = {"SYNTHETIC_CONTROL", "SCRIPTED_CONTROL", "RECORDED_REPLAY"}
LAYERS = {"LAYER_1", "LAYER_2"}
RIVAL_CONDITIONS = {"ADAPTIVE", "FIXED_REPLAY"}
ABLATIONS = {
    "CHIEF_ONLY", "GEMINI_LITE_ENGINEERS", "RECORDED_RECOMMENDATIONS",
    "CONFLICTING_LOCAL_RECOMMENDATIONS", "NOMINAL_CONFIDENCE_CONTROL",
    "HIGH_SELF_REPORTED_CONFIDENCE_CONTROL",
}
FAILURE_LABELS = {
    "FAILURE_TO_INTEGRATE_DRIVER_LOCAL_EVIDENCE",
    "EXCESSIVE_RELIANCE_ON_ENGINEER_RECOMMENDATIONS",
    "UNJUSTIFIED_REJECTION_OF_USEFUL_RECOMMENDATIONS",
    "CONFIDENCE_DRIVEN_CHANGE_WITHOUT_NEW_EVIDENCE",
    "LOCALLY_RATIONAL_TEAM_SUBOPTIMAL",
    "FAILURE_TO_RECONSIDER_CHANGED_COMMITMENT",
    "UNNECESSARY_OR_MISSED_GIVE_BACK",
    "FAILURE_TO_ADAPT_TO_SC_VSC_OR_RIVAL",
}


class EvaluationError(ValueError):
    """Input is malformed, cross-team data leaked, or integrity cannot be established."""


def _hash_record(body: dict[str, Any]) -> str:
    return hashlib.sha256(canonical(body).encode()).hexdigest()


def verify_engineer_records(records: Iterable[dict[str, Any]]) -> None:
    """Verify one append-order Track C record chain without mutating records."""
    previous = None
    for number, original in enumerate(records, 1):
        record = copy.deepcopy(original)
        supplied = record.pop("record_hash", None)
        if not isinstance(supplied, str) or record.get("previous_record_hash") != previous:
            raise EvaluationError(f"Engineer record chain break at record {number}")
        if _hash_record(record) != supplied:
            raise EvaluationError(f"Engineer record hash mismatch at record {number}")
        previous = supplied


def _resolved_by_tick(journal: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {entry["tick_id"]: entry for entry in journal if entry.get("kind") == "resolved"}


def _legal_actions(observation: dict[str, Any]) -> set[str]:
    schema = observation.get("action_schema") or {}
    if observation.get("decision_type") == "RACE_STRATEGY":
        raw = schema.get("driver_a", "")
        return set(raw.split("|")) if isinstance(raw, str) else set(raw)
    return {"USE", "REPLACE"} if observation.get("decision_type") == "COMPONENT_DECISION" else set()


def _reject_private_fields(value: Any, path: str = "") -> None:
    forbidden = {"hidden_seed", "base_seed", "rng_state", "future_events", "rival_private_plan",
                 "private_rival_plan", "other_engineer_private_reasoning"}
    if isinstance(value, dict):
        for key, child in value.items():
            if str(key).lower() in forbidden:
                raise EvaluationError(f"private field exposed at {path + key}")
            _reject_private_fields(child, f"{path}{key}.")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _reject_private_fields(child, f"{path}{index}.")


def verify_bundle(bundle: dict[str, Any]) -> dict[str, Any]:
    """Verify journal/record hashes and bind every analysis decision to its sealed action."""
    required = {"schema_version", "run_id", "result_kind", "layer", "rival_condition",
                "seed_id", "slot_assignment", "journal", "engineer_record_chains", "decisions",
                "season_result"}
    missing = required - set(bundle)
    if missing:
        raise EvaluationError(f"bundle missing fields: {sorted(missing)}")
    if bundle["schema_version"] != 1 or bundle["result_kind"] not in ACTUAL_KINDS | CONTROL_KINDS:
        raise EvaluationError("unsupported schema_version or result_kind")
    if bundle["layer"] not in LAYERS or bundle["rival_condition"] not in RIVAL_CONDITIONS:
        raise EvaluationError("unknown layer or rival condition")
    verify_journal_chain(bundle["journal"])
    for chain in bundle["engineer_record_chains"]:
        verify_engineer_records(chain.get("records", []))

    entries = _resolved_by_tick(bundle["journal"])
    seen = set()
    diagnostics = []
    for decision in bundle["decisions"]:
        key = (decision.get("tick_id"), decision.get("team"))
        if key in seen:
            raise EvaluationError(f"duplicate decision {key}")
        seen.add(key)
        entry = entries.get(key[0])
        if entry is None or key[1] not in entry.get("submissions", {}):
            raise EvaluationError(f"decision {key} has no sealed journal submission")
        observation = decision.get("chief_observation")
        if not isinstance(observation, dict) or observation.get("team") != key[1]:
            raise EvaluationError(f"decision {key} violates team-local observation ownership")
        _reject_private_fields(observation)
        expected_obs_hash = entry["obs_before_sha256"].get(key[1])
        if observation_hash(observation) != expected_obs_hash:
            raise EvaluationError(f"decision {key} observation hash mismatch")
        submission = entry["submissions"][key[1]]
        if decision.get("chosen_action") != submission["action"]:
            raise EvaluationError(f"decision {key} action differs from sealed submission")
        delivered = set(entry.get("engineer_record_hashes", {}).get(key[1], []))
        supplied = {(r.get("record", r)).get("record_hash") for r in decision.get("engineer_reports", [])}
        if supplied != delivered:
            raise EvaluationError(f"decision {key} Engineer records differ from delivered hashes")
        if any((r.get("record", r)).get("team", key[1]) != key[1]
               for r in decision.get("engineer_reports", [])):
            raise EvaluationError(f"decision {key} contains another team's Engineer record")
        for wrapped in decision.get("engineer_reports", []):
            record, local = wrapped.get("record", wrapped), wrapped.get("engineer_observation")
            if local is not None:
                _reject_private_fields(local)
                if observation_hash(local) != record.get("observation_hash"):
                    raise EvaluationError(f"decision {key} Engineer observation hash mismatch")
        declared = set(decision.get("legal_action_set", []))
        public = _legal_actions(observation)
        if declared and public and not declared <= public:
            raise EvaluationError(f"decision {key} declares non-public legal actions")
        if submission.get("status") != "SUBMITTED":
            diagnostics.append({"tick_id": key[0], "team": key[1],
                                "kind": "TOOL_OR_SUBMISSION_ERROR", "status": submission.get("status")})
    return {"integrity": "VERIFIED", "resolved_ticks": len(entries), "diagnostics": diagnostics}


def _lookup(value: Any, path: str) -> tuple[bool, Any]:
    node = value
    for part in path.split("."):
        if isinstance(node, dict) and part in node:
            node = node[part]
        else:
            return False, None
    return True, node


def engineer_information_value(decision: dict[str, Any]) -> list[dict[str, Any]]:
    """Classify evidence availability, not recommendation correctness or usefulness."""
    chief = decision["chief_observation"]
    seen_evidence: Counter[tuple[str, str]] = Counter()
    pending = []
    for report in decision.get("engineer_reports", []):
        local = report.get("engineer_observation")
        record = report.get("record", report)
        recommendation = record.get("recommendation") or {}
        for evidence in recommendation.get("supporting_evidence", []):
            path = evidence.get("field", "")
            found_local, local_value = _lookup(local, path) if isinstance(local, dict) else (False, None)
            chief_path = _chief_lineage_path(path, recommendation.get("driver_id"))
            found_chief, chief_value = _lookup(chief, chief_path)
            fingerprint = (path, canonical(evidence.get("observed_value")))
            seen_evidence[fingerprint] += 1
            if found_chief and chief_value == evidence.get("observed_value"):
                category = "PUBLIC_ALREADY_AVAILABLE_HIGHLIGHTED"
            elif found_local and local_value == evidence.get("observed_value"):
                category = "ENGINEER_LOCAL_NOT_IN_CHIEF_SCHEMA"
            else:
                category = "UNATTRIBUTABLE_OR_SCHEMA_MISMATCH"
            pending.append({"engineer_id": record.get("engineer_id"), "path": path,
                            "chief_lineage_path": chief_path,
                            "category": category, "value": evidence.get("observed_value")})
    for row in pending:
        if seen_evidence[(row["path"], canonical(row["value"]))] > 1:
            row["redundancy"] = "REDUNDANT_ACROSS_REPORTS"
        else:
            row["redundancy"] = "NOT_DUPLICATED"
    return pending


def _chief_lineage_path(local_path: str, driver_id: str | None) -> str:
    prefix = "race_context.assigned_driver_state."
    if local_path.startswith(prefix) and driver_id:
        return f"race_progress.drivers.{driver_id}.{local_path.removeprefix(prefix)}"
    if local_path.startswith("race_context."):
        return f"race_progress.{local_path.removeprefix('race_context.')}"
    return local_path


def _regret(reference: dict[str, Any] | None) -> dict[str, Any]:
    if not reference:
        return {"status": "MISSING_REFERENCE", "confirmed": False}
    required = {"reference_action", "chosen_expected_team_points", "reference_expected_team_points",
                "regret_ci", "source", "uses_future_realization"}
    if required - set(reference):
        return {"status": "INCOMPLETE_REFERENCE", "confirmed": False}
    if reference["uses_future_realization"]:
        return {"status": "PRIVILEGED_REFERENCE_REJECTED", "confirmed": False}
    ci = reference["regret_ci"]
    values = (ci.get("low"), ci.get("mean"), ci.get("high"))
    if any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) for v in values):
        return {"status": "INVALID_REGRET_CI", "confirmed": False}
    sensitivity = reference.get("sensitivity", {})
    threshold = max(0.0, float(sensitivity.get("near_tie_threshold_points", 0.05)))
    confirmed = ci["low"] > threshold
    return {"status": "CONFIRMED_POSITIVE_REGRET" if confirmed else "UNCERTAIN_OR_NEAR_TIE",
            "confirmed": confirmed, "points": dict(ci), "near_tie_threshold_points": threshold,
            "source": reference["source"]}


def evaluate_decision(decision: dict[str, Any]) -> dict[str, Any]:
    """Produce observable facts, separate diagnostics, and evidence-gated failure labels."""
    reference = decision.get("equal_information_reference")
    regret = _regret(reference)
    diagnostics = list(decision.get("diagnostics", []))
    reports = decision.get("engineer_reports", [])
    valid = [r for r in reports if (r.get("record", r)).get("status") == "VALID"]
    invalid = [r for r in reports if (r.get("record", r)).get("status") in {"INVALID", "MISSING"}]
    if invalid:
        diagnostics.append({"kind": "MISSING_OR_INVALID_RECOMMENDATION", "count": len(invalid)})
    consumed = set(decision.get("chosen_action", {}).get("consumed_reports", []))
    available_hashes = {(r.get("record", r)).get("record_hash") for r in valid}
    usage = {"available": len(valid), "delivered": len(reports),
             "explicitly_consumed": len(consumed & available_hashes),
             "action_disagreement_does_not_imply_ignored": True}

    hypotheses = list(decision.get("diagnostic_hypotheses", []))
    labels = []
    if regret["confirmed"]:
        for hypothesis in hypotheses:
            label = hypothesis.get("label")
            evidence = hypothesis.get("evidence", [])
            if label in FAILURE_LABELS and evidence:
                labels.append({"label": label, "evidence": copy.deepcopy(evidence)})
    return {
        "tick_id": decision["tick_id"], "team": decision["team"],
        "observed_action": copy.deepcopy(decision["chosen_action"]),
        "equal_information_reference_action": copy.deepcopy(reference.get("reference_action") if reference else None),
        "regret": regret, "information_value": engineer_information_value(decision),
        "engineer_usage": usage, "diagnostics": diagnostics, "strategic_failures": labels,
        "attribution_limit": (None if labels else
                              "No defensible strategic label without positive non-near-tie equal-information regret"),
    }


def commitment_outcomes(season_result: dict[str, Any]) -> list[dict[str, Any]]:
    """Interpret engine statuses; never add a synthetic reward or penalty."""
    rows = []
    for race in season_result.get("race_results", []):
        for team, view in race.get("team_orders", {}).items():
            commitments = list(view.get("closed_commitments", []))
            if view.get("commitment"):
                commitments.append(view["commitment"])
            for item in commitments:
                status = item.get("status", "UNKNOWN")
                rows.append({"race_index": race.get("race_index"), "team": team,
                             "objective": item.get("objective"), "deadline_lap": item.get("deadline_lap"),
                             "status": status, "give_back_feasible": item.get("give_back_feasible"),
                             "reconsideration_reason": item.get("reconsideration_reason"),
                             "constructors_points_effect": item.get("constructors_points_effect"),
                             "interpretation": _commitment_interpretation(status)})
    return rows


def _commitment_interpretation(status: str) -> str:
    mapping = {
        "OBJECTIVE_ACHIEVED": "objective_achieved",
        "OBJECTIVE_FAILED_BEFORE_DEADLINE": "objective_failed_before_deadline",
        "DEADLINE_EXPIRED": "deadline_reached",
        "FULFILLED": "give_back_completed",
        "VIOLATED": "broken_commitment_requires_feasibility_and_regret_evidence",
        "RECONSIDERED": "rationality_requires_public_state_and_regret_evidence",
        "UNSAFE": "give_back_unsafe",
    }
    return mapping.get(status, "status_recorded_no_normative_inference")


def summarize_bundle(bundle: dict[str, Any]) -> dict[str, Any]:
    integrity = verify_bundle(bundle)
    decisions = [evaluate_decision(row) for row in bundle["decisions"]]
    labels = Counter(f["label"] for row in decisions for f in row["strategic_failures"])
    regrets = [row["regret"]["points"]["mean"] for row in decisions if row["regret"]["confirmed"]]
    return {
        "schema_version": 1, "run_id": bundle["run_id"], "result_kind": bundle["result_kind"],
        "layer": bundle["layer"], "rival_condition": bundle["rival_condition"],
        "seed_id": bundle["seed_id"], "slot_assignment": copy.deepcopy(bundle["slot_assignment"]),
        "integrity": integrity, "season_result": copy.deepcopy(bundle["season_result"]),
        "decision_count": len(decisions), "decisions": decisions,
        "failure_counts": dict(labels), "confirmed_regret_points_sum_descriptive_only": sum(regrets),
        "sampling_unit": "season_or_matched_pair_not_individual_decision",
        "commitments": commitment_outcomes(bundle["season_result"]),
    }


def compare_layers(layer1: dict[str, Any], layer2: dict[str, Any]) -> dict[str, Any]:
    """Compare matched runs without claiming that the pair is an independent sample set."""
    for bundle, expected in ((layer1, "LAYER_1"), (layer2, "LAYER_2")):
        if bundle.get("layer") != expected:
            raise EvaluationError(f"expected {expected}")
    for field in ("seed_id", "slot_assignment", "rival_condition"):
        if layer1.get(field) != layer2.get(field):
            raise EvaluationError(f"Layer 1/2 comparison is not matched on {field}")
    a, b = summarize_bundle(layer1), summarize_bundle(layer2)
    p1, p2 = layer1["season_result"]["team_points"], layer2["season_result"]["team_points"]
    teams = sorted(set(p1) | set(p2))
    return {"comparison": "MATCHED_LAYER_1_VS_LAYER_2", "seed_id": layer1["seed_id"],
            "rival_condition": layer1["rival_condition"],
            "team_points_change": {team: p2.get(team, 0) - p1.get(team, 0) for team in teams},
            "layer_1": a, "layer_2": b,
            "causal_limit": "One matched season is descriptive; aggregate paired seasons/seeds for inference"}


def compare_confidence_controls(nominal: dict[str, Any], high: dict[str, Any]) -> dict[str, Any]:
    """Ensure a confidence-expression ablation does not also change facts or advice."""
    verify_bundle(nominal)
    verify_bundle(high)
    if nominal["seed_id"] != high["seed_id"] or nominal["slot_assignment"] != high["slot_assignment"]:
        raise EvaluationError("confidence controls are not matched")
    nrows = {(d["tick_id"], d["team"]): d for d in nominal["decisions"]}
    hrows = {(d["tick_id"], d["team"]): d for d in high["decisions"]}
    if set(nrows) != set(hrows):
        raise EvaluationError("confidence controls do not cover the same decisions")
    checked = 0
    for key in nrows:
        nr = [(r.get("record", r)).get("recommendation") for r in nrows[key]["engineer_reports"]]
        hr = [(r.get("record", r)).get("recommendation") for r in hrows[key]["engineer_reports"]]
        if len(nr) != len(hr):
            raise EvaluationError(f"confidence control report count differs at {key}")
        for left, right in zip(nr, hr):
            if left is None or right is None:
                continue
            factual = lambda x: {k: v for k, v in x.items() if k not in {"confidence", "uncertainty"}}
            if factual(left) != factual(right):
                raise EvaluationError(f"confidence control changed evidence or recommendation at {key}")
            checked += 1
    return {"matched": True, "recommendations_checked": checked,
            "interpretation": "Any action change is associated with confidence expression, not new factual evidence",
            "confound_warning": "Compare prompt bytes and token usage before causal attribution"}


def summarize_seasons(reports: list[dict[str, Any]]) -> dict[str, Any]:
    """Season-level aggregation; correlated decisions are never the denominator."""
    actual = [r for r in reports if r["result_kind"] in ACTUAL_KINDS]
    controls = [r for r in reports if r["result_kind"] in CONTROL_KINDS]
    return {"season_count": len(reports), "actual_model_seasons": len(actual),
            "control_seasons": len(controls),
            "confirmed_failure_seasons": sum(bool(r.get("failure_counts")) for r in reports),
            "unit_of_analysis": "season; paired comparison when match identifiers agree"}


def build_bundle_from_run(*, run: dict[str, Any], observations: list[dict[str, Any]],
                          layer: str, result_kind: str, slot_assignment: dict[str, str],
                          engineer_records: dict[str, list[dict[str, Any]]] | None = None,
                          run_id: str | None = None) -> dict[str, Any]:
    """Normalize a B6/B7 runner result; references must be attached by a trusted analysis later."""
    records = engineer_records or {}
    by_tick_team = defaultdict(list)
    for team, chain in records.items():
        for record in chain:
            by_tick_team[(record.get("tick_id"), team)].append(record)
    entries = _resolved_by_tick(run["journal"])
    decisions = []
    for captured in observations:
        tick = captured["tick_id"]
        entry = entries.get(tick)
        if entry is None:
            continue
        provenance = {p.get("team"): p for p in captured.get("provenance", [])}
        for team, observation in sorted(captured["observations"].items()):
            from track_c.engineer_runtime import format_runtime_observation
            reports = []
            for record in by_tick_team[(tick, team)]:
                local = format_runtime_observation(observation, record["engineer_id"])
                reports.append({"record": copy.deepcopy(record), "engineer_observation": local})
            prov = provenance.get(team, {})
            diagnostics = []
            if prov.get("status") not in (None, "SUBMITTED"):
                diagnostics.append({"kind": "PROVIDER_OR_TOOL_ERROR", "status": prov.get("status"),
                                    "metadata": copy.deepcopy(prov.get("metadata", {}))})
            decisions.append({"tick_id": tick, "team": team,
                              "chief_observation": copy.deepcopy(observation),
                              "engineer_reports": reports,
                              "legal_action_set": sorted(_legal_actions(observation)),
                              "chosen_action": copy.deepcopy(entry["submissions"][team]["action"]),
                              "equal_information_reference": None,
                              "diagnostic_hypotheses": [], "diagnostics": diagnostics})
    bundle = {
        "schema_version": 1,
        "run_id": run_id or f"{layer.lower()}-{run['base_seed_id']}",
        "result_kind": result_kind, "layer": layer,
        "rival_condition": run["rival_condition"], "seed_id": run["base_seed_id"],
        "slot_assignment": copy.deepcopy(slot_assignment), "journal": copy.deepcopy(run["journal"]),
        "engineer_record_chains": [{"team": team, "records": copy.deepcopy(chain)}
                                   for team, chain in sorted(records.items())],
        "decisions": decisions,
        "season_result": {"team_points": copy.deepcopy(run["standings"]["team_points"]),
                          "driver_points": copy.deepcopy(run["standings"]["driver_points"]),
                          "race_results": copy.deepcopy(run["race_results"]),
                          "complete": run["complete"]},
    }
    return bundle
