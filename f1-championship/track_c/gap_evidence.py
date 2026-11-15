"""Season-level Frontier–Reference gap export with strict estimand separation."""

from __future__ import annotations

import copy
import json
import math
import re
import statistics as st
from collections import defaultdict
from pathlib import Path
from typing import Any

from .coordination_evaluation import EvaluationError

ROLES = {"FRONTIER", "REFERENCE", "COMPETITION"}


def validate_manifest(manifest: dict[str, Any]) -> None:
    required = {"schema_version", "benchmark", "runs"}
    if required - set(manifest) or manifest.get("schema_version") != 1:
        raise EvaluationError("invalid gap manifest header")
    benchmark = manifest["benchmark"]
    for field in ("version", "config_hash", "reward_version"):
        if not isinstance(benchmark.get(field), str) or not benchmark[field]:
            raise EvaluationError(f"benchmark.{field} is required")
    seen = set()
    for run in manifest["runs"]:
        for field in ("run_id", "role", "seed_id", "comparison_group", "complete"):
            if field not in run:
                raise EvaluationError(f"run missing {field}")
        if run["run_id"] in seen or run["role"] not in ROLES:
            raise EvaluationError("duplicate run or invalid role")
        seen.add(run["run_id"])
        if run["role"] != "COMPETITION":
            for field in ("constructors_points", "normalized_reward"):
                value = run.get(field)
                if value is not None and (isinstance(value, bool) or not isinstance(value, (int, float))
                                          or not math.isfinite(value)):
                    raise EvaluationError(f"{field} must be finite or pending")
            reward = run.get("normalized_reward")
            if reward is not None and not 0.0 <= reward <= 1.0:
                raise EvaluationError("normalized_reward must be within [0, 1]")
        for failure in run.get("selected_decision_failures", []):
            observation_hash = failure.get("observation_hash")
            regret = failure.get("regret_evidence")
            if not isinstance(observation_hash, str) or not re.fullmatch(r"[0-9a-f]{64}", observation_hash):
                raise EvaluationError("selected failure lacks observation hash or regret evidence")
            if not isinstance(regret, dict) or not regret.get("source"):
                raise EvaluationError("selected failure lacks observation hash or regret evidence")
            values = ([regret.get("expected_points_regret")] if "expected_points_regret" in regret else
                      [regret.get("regret_ci", {}).get(key) for key in ("low", "mean", "high")])
            if not values or any(isinstance(value, bool) or not isinstance(value, (int, float))
                                 or not math.isfinite(value) for value in values):
                raise EvaluationError("selected failure has invalid regret evidence")


def export_gap_evidence(manifest: dict[str, Any]) -> dict[str, Any]:
    validate_manifest(manifest)
    groups = defaultdict(lambda: {"FRONTIER": [], "REFERENCE": [], "COMPETITION": []})
    for run in manifest["runs"]:
        groups[run["comparison_group"]][run["role"]].append(run)
    comparisons, competitions = [], []
    for group, roles in sorted(groups.items()):
        competitions.extend({"comparison_group": group, **copy.deepcopy(run)}
                            for run in roles["COMPETITION"])
        frontier_by_seed = _unique_by_seed(roles["FRONTIER"], group, "FRONTIER")
        reference_by_seed = _unique_by_seed(roles["REFERENCE"], group, "REFERENCE")
        all_seeds = sorted(set(frontier_by_seed) | set(reference_by_seed))
        pairs, pending = [], []
        for seed in all_seeds:
            frontier, reference = frontier_by_seed.get(seed), reference_by_seed.get(seed)
            if frontier is None or reference is None:
                pending.append({"seed_id": seed, "missing": "FRONTIER" if frontier is None else "REFERENCE"})
                continue
            if not frontier["complete"] or not reference["complete"]:
                pending.append({"seed_id": seed, "missing": "complete matched runs"})
                continue
            if frontier.get("constructors_points") is None or reference.get("constructors_points") is None:
                pending.append({"seed_id": seed, "missing": "constructors_points"})
                continue
            pairs.append({"seed_id": seed, "frontier_run_id": frontier["run_id"],
                          "reference_run_id": reference["run_id"],
                          "frontier_model": frontier.get("model"),
                          "frontier_provider": frontier.get("provider"),
                          "frontier_harness": copy.deepcopy(frontier.get("harness")),
                          "frontier_points": frontier["constructors_points"],
                          "reference_points": reference["constructors_points"],
                          "reference_minus_frontier_points": reference["constructors_points"] - frontier["constructors_points"],
                          "frontier_reward": frontier.get("normalized_reward"),
                          "reference_reward": reference.get("normalized_reward"),
                          "reference_harness": copy.deepcopy(reference.get("harness")),
                          "reference_policy_provenance": copy.deepcopy(reference.get("policy_provenance")),
                          "selected_decision_failures": copy.deepcopy(frontier.get("selected_decision_failures", []))})
        differences = [row["reference_minus_frontier_points"] for row in pairs]
        comparisons.append({"comparison_group": group, "matched_pairs": pairs, "unmatched_or_pending": pending,
                            "season_level_gap": _paired_interval(differences),
                            "sampling_unit": "matched season seed",
                            "decision_regret_is_not_summed_as_an_independent_sample": True,
                            "status": "MEASURED" if pairs else "PENDING_REFERENCE_OR_FRONTIER"})
    return {"schema_version": 1, "benchmark": copy.deepcopy(manifest["benchmark"]),
            "frontier_reference_gap": comparisons,
            "decision_level_regret": "embedded evidence; distinct from season-level gap",
            "gemini_deepseek_competition": competitions,
            "separation_note": "Competition scores are not a Frontier–Reference gap"}


def _unique_by_seed(runs: list[dict[str, Any]], group: str, role: str) -> dict[str, dict[str, Any]]:
    out = {}
    for run in runs:
        if run["seed_id"] in out:
            raise EvaluationError(f"{group} has multiple {role} runs for seed {run['seed_id']}")
        out[run["seed_id"]] = run
    return out


def _paired_interval(values: list[float]) -> dict[str, Any]:
    if not values:
        return {"n_seasons": 0, "mean_points": None, "ci95": None, "status": "PENDING"}
    mean = st.mean(values)
    if len(values) < 2:
        return {"n_seasons": 1, "mean_points": round(mean, 6), "ci95": None,
                "status": "ONE_PAIR_NO_CONFIDENCE_INTERVAL"}
    se = st.stdev(values) / math.sqrt(len(values))
    # Two-sided 95% Student-t critical values; normal approximation after df 30.
    criticals = {1: 12.706, 2: 4.303, 3: 3.182, 4: 2.776, 5: 2.571, 6: 2.447,
                 7: 2.365, 8: 2.306, 9: 2.262, 10: 2.228, 11: 2.201, 12: 2.179,
                 13: 2.160, 14: 2.145, 15: 2.131, 16: 2.120, 17: 2.110, 18: 2.101,
                 19: 2.093, 20: 2.086, 21: 2.080, 22: 2.074, 23: 2.069, 24: 2.064,
                 25: 2.060, 26: 2.056, 27: 2.052, 28: 2.048, 29: 2.045, 30: 2.042}
    t = criticals.get(len(values) - 1, 1.96)
    return {"n_seasons": len(values), "mean_points": round(mean, 6),
            "ci95": [round(mean - t * se, 6), round(mean + t * se, 6)],
            "method": "paired Student-t across independent season seeds"}


def markdown_report(report: dict[str, Any]) -> str:
    benchmark = report["benchmark"]
    lines = ["# Gap evidence report", "", f"- Benchmark: `{benchmark['version']}`",
             f"- Config hash: `{benchmark['config_hash']}`", f"- Reward version: `{benchmark['reward_version']}`", "",
             "## Frontier–Reference season gap", ""]
    for group in report["frontier_reference_gap"]:
        gap = group["season_level_gap"]
        lines.extend([f"### {group['comparison_group']}", "",
                      f"Status: **{group['status']}**. Matched season pairs: {gap['n_seasons']}."])
        if gap["mean_points"] is not None:
            lines.append(f"Reference − Frontier mean points: **{gap['mean_points']}**.")
        if gap["ci95"]:
            lines.append(f"Paired 95% CI: **[{gap['ci95'][0]}, {gap['ci95'][1]}]**.")
        if group["unmatched_or_pending"]:
            lines.append(f"Pending/unmatched: `{json.dumps(group['unmatched_or_pending'], sort_keys=True)}`")
        lines.append("")
    lines.extend(["## Decision-level regret", "",
                  "Decision evidence is reported per sealed observation and is not treated as independent season samples.", "",
                  "## Gemini–DeepSeek competition", "",
                  "Competition results are listed separately and are not the official Frontier–Reference gap.", ""])
    for row in report["gemini_deepseek_competition"]:
        lines.append(f"- `{row['run_id']}` ({row['seed_id']}): {row.get('constructors_points', 'n/a')} points")
    return "\n".join(lines) + "\n"


def write_gap_outputs(manifest: dict[str, Any], json_path: Path, markdown_path: Path) -> dict[str, Any]:
    report = export_gap_evidence(manifest)
    json_path.write_text(json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    markdown_path.write_text(markdown_report(report), encoding="utf-8")
    return report
