#!/usr/bin/env python3
"""Post-run Harbor artifact verification, verified race replay, and static HTML.

This is presentation code only. Official completion, integrity, points, and reward
come from the isolated verifier. No official overall score is recomputed here.
"""

from __future__ import annotations

import argparse
import hashlib
import html
import importlib
import importlib.util
import json
import math
import os
from pathlib import Path
import platform
import re
import shutil
import sys
import time
from datetime import datetime, timezone
from typing import Any, Iterable

CAPTURE_DIR = "demo_artifacts"
EXIT_INVALID = 2
EXIT_UNVERIFIED = 3
ZERO_HASH = "0" * 64


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ValueError(f"missing {path.name}") from exc
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"malformed {path.name}: {type(exc).__name__}: {exc}") from exc


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")


def sha256_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def is_number(value: Any) -> bool:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return False
    try:
        return math.isfinite(value)
    except (OverflowError, TypeError, ValueError):
        return False


def is_count(value: Any, *, positive: bool = False) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= (1 if positive else 0)


def validate_report(report: dict[str, Any]) -> list[str]:
    """Validate only fields consumed by the presentation layer."""
    errors: list[str] = []
    completion = report.get("completion")
    integrity = report.get("integrity")
    if not isinstance(completion, dict):
        errors.append("verifier report has no valid completion object")
        completion = {}
    if not isinstance(integrity, dict):
        errors.append("verifier report has no valid integrity object")
        integrity = {}
    complete = completion.get("complete")
    intact = integrity.get("intact")
    if not isinstance(complete, bool):
        errors.append("verifier completion.complete must be boolean")
    if not isinstance(intact, bool):
        errors.append("verifier integrity.intact must be boolean")
    for key in ("accepted_decisions", "races_completed"):
        if not is_count(completion.get(key)):
            errors.append(f"verifier completion.{key} must be a non-negative integer")
    if not is_count(completion.get("races_total"), positive=True):
        errors.append("verifier completion.races_total must be a positive integer")
    if all(is_count(completion.get(key)) for key in ("races_completed", "races_total")):
        if completion["races_completed"] > completion["races_total"]:
            errors.append("verifier races_completed exceeds races_total")
        elif isinstance(complete, bool) and complete != (completion["races_completed"] == completion["races_total"]):
            errors.append("verifier completion flag and completed-race count disagree")
    if complete is True and intact is not True:
        errors.append("a complete report must also pass trusted replay integrity")
    if intact is True:
        performance = report.get("performance")
        if not isinstance(performance, dict) or not is_number(performance.get("apex_constructors_points")) or performance.get("apex_constructors_points") < 0:
            errors.append("an intact report must contain valid official Apex constructors' points")
    if not is_number(report.get("reward")) or not 0.0 <= float(report["reward"]) <= 1.0:
        errors.append("verifier report reward is missing, non-finite, or outside [0, 1]")
    return errors


def benchmark_version(report: dict[str, Any]) -> str:
    if isinstance(report.get("benchmark_version"), str):
        return report["benchmark_version"]
    evidence = report.get("evidence")
    if isinstance(evidence, dict) and isinstance(evidence.get("evidence_benchmark_version"), str):
        return evidence["evidence_benchmark_version"]
    return "pre-1.1.0"


def relative_parts(root: Path, path: Path) -> tuple[str, ...]:
    try:
        return path.relative_to(root).parts
    except ValueError:
        return path.parts


def find_verifier_report(run_dir: Path) -> tuple[Path | None, list[str]]:
    """Find Harbor's verifier mount, never an agent/artifact lookalike."""
    candidates = []
    for path in run_dir.rglob("report.json"):
        parts = relative_parts(run_dir, path)
        if not path.is_file() or CAPTURE_DIR in parts or path.parent.name != "verifier":
            continue
        if "agent" in parts or "artifacts" in parts:
            continue
        candidates.append(path)
    candidates.sort()
    if not candidates:
        return None, ["Harbor verifier report.json was not found"]
    if len(candidates) > 1:
        return None, ["multiple Harbor verifier reports found; refusing to choose one"]
    return candidates[0], []


def check_evidence(report: dict[str, Any], evidence_dir: Path) -> tuple[dict[str, Any], list[str]]:
    """Cross-check captured bytes with the verifier's sealed-evidence claims.

    This deliberately does not replace trusted replay. The isolated verifier's
    integrity.intact flag remains the replay authority.
    """
    errors: list[str] = []
    info: dict[str, Any] = {"manifest": None, "journal_sha256": None, "journal_path": None}
    journal_path = evidence_dir / "journal.jsonl"
    manifest_path = evidence_dir / "manifest.json"
    if not journal_path.is_file() or not manifest_path.is_file():
        return info, ["sidecar evidence requires journal.jsonl and manifest.json"]
    try:
        raw = journal_path.read_bytes()
        digest = sha256_bytes(raw)
        info["journal_sha256"] = digest
        info["journal_path"] = str(journal_path)
    except OSError as exc:
        return info, [f"cannot read sidecar journal: {exc}"]
    try:
        manifest = read_json(manifest_path)
        if not isinstance(manifest, dict):
            raise ValueError("manifest.json must contain an object")
        info["manifest"] = manifest
    except ValueError as exc:
        errors.append(str(exc))
        manifest = None

    evidence = report.get("evidence")
    report_digest = evidence.get("journal_sha256") if isinstance(evidence, dict) else None
    if not isinstance(report_digest, str) or not re.fullmatch(r"[0-9a-f]{64}", report_digest):
        errors.append("verifier report has no valid evidence journal digest")
    elif report_digest != digest:
        errors.append("captured journal digest differs from verifier report")
    if manifest is not None:
        if manifest.get("journal_sha256") != digest:
            errors.append("captured journal does not match sealed manifest")
        embedded = evidence.get("manifest") if isinstance(evidence, dict) else None
        if embedded is not None and embedded != manifest:
            errors.append("captured manifest differs from verifier report")
        try:
            text = raw.decode("utf-8")
            lines = text.splitlines()
            if any(not line.strip() for line in lines):
                raise ValueError("journal contains a blank line")
            entries = [json.loads(line) for line in lines]
            if manifest.get("journal_entries") != len(entries):
                errors.append("journal entry count does not match sealed manifest")
            expected_head = entries[-1].get("entry_hash") if entries else ZERO_HASH
            if not isinstance(expected_head, str) or manifest.get("head_hash") != expected_head:
                errors.append("journal head does not match sealed manifest")
            info["journal_entries"] = len(entries)
            accepted = sum(isinstance(entry, dict) and entry.get("kind") == "accepted" for entry in entries)
            info["accepted_decisions"] = accepted
            completion = report.get("completion") if isinstance(report.get("completion"), dict) else {}
            if completion.get("accepted_decisions") != accepted:
                errors.append("accepted journal actions differ from verifier completion count")
            stats = manifest.get("request_stats")
            if isinstance(stats, dict) and "act_accepted" in stats and stats.get("act_accepted") != accepted:
                errors.append("accepted journal actions differ from manifest request statistics")
        except (UnicodeDecodeError, ValueError, AttributeError, TypeError) as exc:
            errors.append(f"malformed sidecar journal: {type(exc).__name__}: {exc}")
    return info, errors


def check_reward(report: dict[str, Any], report_path: Path) -> tuple[str | None, list[str]]:
    reward_path = report_path.with_name("reward.txt")
    if not reward_path.is_file():
        return None, ["Harbor verifier reward.txt was not found beside report.json"]
    try:
        reward_text = reward_path.read_text(encoding="utf-8").strip()
        parsed = float(reward_text)
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        return None, [f"malformed verifier reward.txt: {type(exc).__name__}: {exc}"]
    official = report.get("reward")
    if not is_number(official) or not 0.0 <= float(official) <= 1.0:
        return reward_text, ["verifier report reward is missing, non-finite, or outside [0, 1]"]
    if not math.isfinite(parsed) or reward_text != f"{float(official):.8f}":
        return reward_text, ["reward.txt does not match the official report reward rounded to eight decimals"]
    return reward_text, []


def require_replay_runtime() -> None:
    if sys.version_info[:2] != (3, 12):
        raise ValueError("canonical post-run replay requires Python 3.12 (use f1-championship/scripts/py312)")


def derive_race_summary(benchmark: Path, evidence_dir: Path, report: dict[str, Any], digest: str) -> dict[str, Any]:
    """Use the benchmark's unchanged trusted replay to expose race transitions.

    Python 3.12 is mandatory because the authoritative replay is bit-exact there.
    The seed is read by the trusted session and is never included in the output.
    """
    require_replay_runtime()
    tests_dir = benchmark / "tests"
    seed_path = tests_dir / "hidden_seed.json"
    if not tests_dir.is_dir() or not seed_path.is_file():
        raise ValueError("benchmark tests/hidden_seed.json is required for per-race replay detail")
    package_dir = tests_dir / "f1pitwall"
    if not (package_dir / "__init__.py").is_file():
        raise ValueError("benchmark verifier package f1pitwall is missing")
    # Do not reuse an f1pitwall package loaded by another local test/module.
    # A private alias keeps replay on the benchmark's own verifier copy.
    package_key = sha256_bytes(str(package_dir.resolve()).encode("utf-8"))[:16]
    package_alias = f"_f1_demo_verifier_{package_key}"
    if package_alias not in sys.modules:
        spec = importlib.util.spec_from_file_location(
            package_alias,
            package_dir / "__init__.py",
            submodule_search_locations=[str(package_dir.resolve())],
        )
        if spec is None or spec.loader is None:
            raise ValueError("cannot load benchmark verifier package")
        module = importlib.util.module_from_spec(spec)
        sys.modules[package_alias] = module
        spec.loader.exec_module(module)
    journal = importlib.import_module(f"{package_alias}.journal")
    parse_journal, replay = journal.parse_journal, journal.replay
    seed_data = read_json(seed_path)
    if not isinstance(seed_data, dict) or isinstance(seed_data.get("base_seed"), bool) or not isinstance(seed_data.get("base_seed"), int):
        raise ValueError("benchmark hidden seed is malformed")
    entries = parse_journal((evidence_dir / "journal.jsonl").read_text(encoding="utf-8"))
    result = replay(entries, seed_data["base_seed"])
    session = result["session"]
    completion = report.get("completion") if isinstance(report.get("completion"), dict) else {}
    if result["complete"] is not completion.get("complete") or result["accepted"] != completion.get("accepted_decisions"):
        raise ValueError("canonical replay differs from official completion counts")
    accepted = [entry for entry in entries if entry.get("kind") == "accepted"]
    traces = session.trace()
    if len(accepted) != len(traces):
        raise ValueError("canonical replay trace and journal have different accepted-action counts")
    races = []
    last_race = 0
    for entry, row in zip(accepted, traces):
        transition = row.get("state_transition") or {}
        before = transition.get("race_index_before")
        after = transition.get("race_index_after")
        if not isinstance(before, int) or after != before + 1:
            continue
        awarded = transition.get("awarded_points")
        classification = transition.get("classification")
        if not isinstance(awarded, dict) or not isinstance(classification, list):
            raise ValueError("race-completion transition lacks results")
        track = session.state.calendar[before]
        positions = {
            item.get("driver"): item.get("position")
            for item in classification
            if isinstance(item, dict) and item.get("driver") in ("Apex A", "Apex B")
        }
        # Strategy rows for this race are already verified observations/actions.
        race_rows = []
        for candidate in traces:
            trans = candidate.get("state_transition") or {}
            if trans.get("race_index_before") == before and candidate.get("decision_type") == "RACE_STRATEGY":
                race_rows.append(candidate)
        actions = [row.get("action", {}) for row in race_rows]
        statuses = [
            (row.get("observation", {}).get("race_progress", {}) or {}).get("track_status")
            for row in race_rows
        ]
        races.append({
            "race": before + 1,
            "name": track.name,
            "archetype": track.archetype,
            "apex_points": sum(value for driver, value in awarded.items() if driver in ("Apex A", "Apex B")),
            "apex_positions": positions,
            "stops": sum(
                1
                for action in actions
                for key in ("driver_a", "driver_b")
                if str(action.get(key, "")).startswith("PIT_")
            ),
            "sc_vsc_decisions": sum(status in ("SC", "VSC") for status in statuses),
            "verified": True,
            "journal_seq": entry.get("seq"),
        })
        last_race = after
    if last_race != completion.get("races_completed"):
        raise ValueError("canonical replay race count differs from verifier report")
    return {
        "schema_version": 1,
        "source": "canonical verifier replay of the sealed journal (full observation-hash verification)",
        "journal_sha256": digest,
        "replay_verified": True,
        "complete": result["complete"],
        "races_total": len(session.state.calendar),
        "races": races,
    }


def validate_race_summary(summary: dict[str, Any], report: dict[str, Any], digest: str) -> dict[str, Any]:
    if summary.get("schema_version") != 1 or summary.get("replay_verified") is not True:
        raise ValueError("race summary is not marked as verified replay output")
    if summary.get("journal_sha256") != digest:
        raise ValueError("race summary belongs to a different journal")
    completion = report.get("completion") if isinstance(report.get("completion"), dict) else {}
    if summary.get("complete") is not completion.get("complete"):
        raise ValueError("race summary completion differs from verifier report")
    if summary.get("races_total") != completion.get("races_total"):
        raise ValueError("race summary calendar differs from verifier report")
    races = summary.get("races")
    if not isinstance(races, list) or len(races) != completion.get("races_completed"):
        raise ValueError("race summary count differs from verifier report")
    for index, race in enumerate(races, start=1):
        if not isinstance(race, dict) or race.get("race") != index or race.get("verified") is not True:
            raise ValueError("race completions are not contiguous verified events")
        if not is_number(race.get("apex_points")):
            raise ValueError(f"race {index} has invalid points")
    performance = report.get("performance")
    if completion.get("complete") and isinstance(performance, dict) and is_number(performance.get("apex_constructors_points")):
        if sum(race["apex_points"] for race in races) != performance["apex_constructors_points"]:
            raise ValueError("race points do not sum to official constructors' points")
    return summary


def load_race_details(
    report: dict[str, Any],
    evidence_dir: Path,
    evidence_info: dict[str, Any],
    benchmark: Path,
    intact: bool,
) -> tuple[dict[str, Any] | None, list[str], list[str]]:
    warnings: list[str] = []
    errors: list[str] = []
    if not intact or not evidence_info.get("journal_sha256"):
        return None, ["Race progress withheld: sealed replay and artifact integrity have not both passed."], errors
    digest = evidence_info["journal_sha256"]
    try:
        require_replay_runtime()
    except ValueError as exc:
        return None, [f"Per-race canonical replay unavailable: {exc}"], errors
    try:
        # Existing analysis traces and cached summaries are never promoted to
        # verified progress: only this journal's canonical replay is accepted.
        candidate = derive_race_summary(benchmark, evidence_dir, report, digest)
        return validate_race_summary(candidate, report, digest), warnings, errors
    except (ImportError, OSError) as exc:
        warnings.append(f"Per-race canonical replay unavailable: {type(exc).__name__}: {exc}")
    except Exception as exc:
        # A completed replay that contradicts the official report is not an
        # optional-presentation warning; it invalidates this demo's consistency.
        errors.append(f"Canonical replay/report mismatch: {type(exc).__name__}: {exc}")
    return None, warnings, errors


def load_failure_evidence(
    explicit: Path | None,
    trial_dir: Path,
    run_dir: Path,
    verified: bool,
) -> tuple[dict[str, Any], list[str]]:
    warnings: list[str] = []
    path = explicit
    if path is None:
        candidates = []
        for candidate in trial_dir.rglob("confirm_own_continuation.json"):
            parts = relative_parts(run_dir, candidate)
            if candidate.is_file() and CAPTURE_DIR not in parts and "agent" not in parts and "artifacts" not in parts:
                candidates.append(candidate)
        if len(candidates) == 1:
            path = candidates[0]
    if path is None:
        return {"status": "unavailable", "reason": "No counterfactual failure-analysis artifact was supplied.", "rows": []}, warnings
    if not verified:
        return {"status": "unavailable", "reason": "Strategic failure evidence is withheld because this run is not verified.", "rows": []}, warnings
    try:
        raw = read_json(path)
        if not isinstance(raw, list):
            raise ValueError("failure evidence must be a JSON list")
        rows = []
        skipped = 0
        for item in raw:
            if not isinstance(item, dict) or item.get("confirmed") is not True:
                continue
            numeric = (
                "loss_own_continuation", "se_own_continuation",
                "loss_baseline_continuation", "se_baseline_continuation",
            )
            if not is_count(item.get("race_index")) or not all(is_number(item.get(key)) for key in numeric):
                skipped += 1
                continue
            own_confirmed = (
                item["loss_own_continuation"] > 1
                and item["se_own_continuation"] >= 0
                and item["loss_own_continuation"] > 2 * item["se_own_continuation"]
            )
            baseline_candidate = (
                item["loss_baseline_continuation"] > 1
                and item["se_baseline_continuation"] >= 0
                and item["loss_baseline_continuation"] > 2 * item["se_baseline_continuation"]
            )
            if not own_confirmed or not baseline_candidate:
                skipped += 1
                continue
            rows.append({
                "race": item["race_index"] + 1,
                "decision": item.get("decision", "unknown"),
                "lap": item.get("lap", "unknown"),
                "status": item.get("status", "unknown"),
                "category": item.get("category", "unknown"),
                "agent": item.get("agent", "unknown"),
                "best": item.get("best", "unknown"),
                "loss": item["loss_own_continuation"],
                "se": item["se_own_continuation"],
                "baseline_loss": item["loss_baseline_continuation"],
            })
        if skipped:
            warnings.append(f"Skipped {skipped} malformed confirmed-failure rows.")
        rows.sort(key=lambda row: float(row["loss"]), reverse=True)
        return {
            "status": "available",
            "source": str(path),
            "confirmed_count": len(rows),
            "rows": rows[:3],
            "note": "The supplied analysis confirms these counterfactual estimates; their association with this journal is not independently verified. They are not verifier integrity failures or realized point losses.",
        }, warnings
    except (ValueError, OSError) as exc:
        warnings.append(f"Malformed failure evidence ignored: {exc}")
        return {"status": "unavailable", "reason": f"Failure evidence was malformed: {exc}", "rows": []}, warnings


def load_reference_comparison(
    args: argparse.Namespace,
    report: dict[str, Any],
    run_verified: bool,
) -> dict[str, Any]:
    reference_report = args.reference_report
    reference_evidence = args.reference_evidence
    reference_seed = args.reference_seed
    supplied = (reference_report, reference_evidence, reference_seed)
    unavailable = lambda reason: {"status": "unavailable", "reason": reason}
    if not any(supplied):
        return unavailable("No valid matched reference was supplied; no Frontier–Reference gap is claimed.")
    if not all(supplied):
        return unavailable("Matched comparison requires reference report, evidence directory, and reference seed path.")
    if not run_verified:
        return unavailable("The Frontier run is not verified, so no comparison is shown.")
    try:
        reference = read_json(reference_report)
        if not isinstance(reference, dict):
            raise ValueError("reference report must contain an object")
        report_errors = validate_report(reference)
        if report_errors:
            raise ValueError("; ".join(report_errors))
        if reference["completion"]["complete"] is not True or reference["integrity"]["intact"] is not True:
            raise ValueError("reference is not complete and replay-intact")
        _, evidence_errors = check_evidence(reference, reference_evidence)
        _, reward_errors = check_reward(reference, reference_report)
        if evidence_errors or reward_errors:
            raise ValueError("; ".join(evidence_errors + reward_errors))
        if benchmark_version(reference) != benchmark_version(report) or reference.get("scalar_version") != report.get("scalar_version"):
            raise ValueError("benchmark or scalar version differs between Frontier and Reference")
        current_seed = Path(args.seed_path) if args.seed_path else args.benchmark_path / "tests" / "hidden_seed.json"
        if not current_seed.is_file() or not reference_seed.is_file():
            raise ValueError("matched seed file is missing")
        if sha256_file(current_seed) != sha256_file(reference_seed):
            raise ValueError("seed files do not match byte-for-byte")
        frontier_performance = report.get("performance") or {}
        reference_performance = reference.get("performance") or {}
        fp = frontier_performance.get("apex_constructors_points")
        rp = reference_performance.get("apex_constructors_points")
        fr = report.get("reward")
        rr = reference.get("reward")
        if not all(is_number(value) for value in (fp, rp, fr, rr)):
            raise ValueError("matched reports lack valid official points or rewards")
        return {
            "status": "available",
            "match": "Same benchmark/scalar version and byte-identical verifier seed files; both sealed journals passed artifact checks and trusted replay.",
            "frontier_points": fp,
            "reference_points": rp,
            "points_gap": fp - rp,
            "frontier_reward": fr,
            "reference_reward": rr,
            "reward_gap": fr - rr,
            "reference_report": str(reference_report),
        }
    except (ValueError, OSError, AttributeError) as exc:
        return unavailable(f"Matched reference rejected: {exc}")


def progress_line(completed: int, total: int) -> str:
    if isinstance(completed, bool) or isinstance(total, bool) or not isinstance(completed, int) or not isinstance(total, int):
        raise ValueError("race counts must be integers")
    if total < 1 or completed < 1 or completed > total:
        raise ValueError("race counts are outside the calendar")
    prefix = "-" * (2 * (completed - 1))
    suffix = "-" * max(0, 7 - 2 * (completed - 1))
    finish = " FINISH" if completed == total else ""
    return f"RACE {completed}/{total} [{prefix}=o==o>{suffix}]{finish}"


def verified_events(summary: dict[str, Any] | None) -> tuple[list[int], int | None]:
    if not summary or summary.get("replay_verified") is not True:
        return [], None
    total = summary.get("races_total")
    races = summary.get("races")
    if not isinstance(total, int) or not isinstance(races, list):
        return [], total if isinstance(total, int) else None
    completed = []
    for expected, race in enumerate(races, start=1):
        if not isinstance(race, dict) or race.get("race") != expected or race.get("verified") is not True:
            break
        completed.append(expected)
    return completed, total


def emit_progress(summary: dict[str, Any] | None, stream: Any, tty: str = "auto", delay: float = 0.0) -> None:
    interactive = stream.isatty() if tty == "auto" else tty == "always"
    completed, total = verified_events(summary)
    if not completed or not isinstance(total, int) or total < 1:
        stream.write("No verified race-completion events; progress not shown.\n")
        stream.flush()
        return
    stream.write("Verified post-run replay (not live):\n")
    for race in completed:
        line = progress_line(race, total)
        if interactive:
            stream.write("\r\x1b[2K" + line)
        else:
            stream.write(line + "\n")
        stream.flush()
        if delay > 0:
            time.sleep(delay)
    if interactive:
        stream.write("\n")
        stream.flush()


def esc(value: Any) -> str:
    return html.escape(str(value), quote=True)


def status_word(value: bool, yes: str = "PASS", no: str = "FAIL") -> str:
    return yes if value else no


def format_number(value: Any, places: int = 3) -> str:
    if not is_number(value):
        return "unavailable"
    if isinstance(value, int):
        return str(value)
    return f"{value:.{places}f}"


def render_table(headers: Iterable[str], rows: Iterable[Iterable[Any]]) -> str:
    head = "".join(f"<th scope=\"col\">{esc(item)}</th>" for item in headers)
    body = []
    for row in rows:
        body.append("<tr>" + "".join(f"<td>{esc(cell)}</td>" for cell in row) + "</tr>")
    return f"<div class=\"table-wrap\"><table><thead><tr>{head}</tr></thead><tbody>{''.join(body)}</tbody></table></div>"


def render_html(context: dict[str, Any]) -> str:
    metadata = context["metadata"]
    report = context.get("report") or {}
    completion = report.get("completion") if isinstance(report.get("completion"), dict) else {}
    integrity = report.get("integrity") if isinstance(report.get("integrity"), dict) else {}
    performance = report.get("performance") if isinstance(report.get("performance"), dict) else {}
    complete = completion.get("complete") is True
    intact = integrity.get("intact") is True
    verified = context["verified"]
    harbor_exit = context["harbor_exit_code"]
    success = verified and harbor_exit == 0
    banner = "VERIFIED RUN" if success else ("HARBOR RUN FAILED" if harbor_exit else "RUN NOT VERIFIED")
    banner_class = "ok" if success else "bad"
    reward = report.get("reward")
    points = performance.get("apex_constructors_points", "unavailable")
    normalization = report.get("normalization") if isinstance(report.get("normalization"), dict) else {}
    errors = context.get("errors", [])
    warnings = context.get("warnings", [])
    summary = context.get("race_summary")
    comparison = context.get("comparison", {"status": "unavailable", "reason": "Not evaluated."})
    failures = context.get("failures", {"status": "unavailable", "reason": "Not supplied."})

    metadata_rows = [
        ("Run", metadata.get("run_id", "unknown")),
        ("Agent", metadata.get("agent", "opencode")),
        ("Model", metadata.get("model", "unknown")),
        ("Harbor", metadata.get("harbor_version", "unknown")),
        ("Benchmark path", metadata.get("benchmark_path", "unknown")),
        ("Started (UTC)", metadata.get("started_at", "unknown")),
        ("Finished (UTC)", metadata.get("finished_at", "unknown")),
        ("Harbor exit code", harbor_exit),
        ("Job output", context.get("trial_dir", "not found")),
        ("Harbor log", metadata.get("harbor_log", "harbor.log")),
    ]
    verification_rows = [
        ("Harbor execution", status_word(harbor_exit == 0), f"exit {harbor_exit}"),
        ("Championship completion", status_word(complete, "COMPLETE", "INCOMPLETE"),
         f"{completion.get('races_completed', '?')}/{completion.get('races_total', '?')} races; "
         f"{completion.get('accepted_decisions', '?')} accepted decisions"),
        ("Trusted sealed replay", status_word(intact, "VERIFIED", "NOT VERIFIED"),
         integrity.get("error") or "Hash chain and observation hashes accepted by the isolated verifier" if intact else "No verifier success detail"),
        ("Captured artifact cross-check", status_word(context["artifact_ok"]),
         "Manifest, journal bytes/count/head, report digest, and reward consistency" if context["artifact_ok"] else "See diagnostics"),
    ]
    team_points = performance.get("team_points") if isinstance(performance.get("team_points"), dict) else {}
    standings = sorted(team_points.items(), key=lambda item: (-item[1], item[0])) if all(is_number(v) for v in team_points.values()) else []
    normalization_rows = [
        ("Official normalized reward", f"{reward:.8f}" if is_number(reward) else "unavailable"),
        ("Scalar version", report.get("scalar_version", "unknown")),
        ("Formula reported by verifier", normalization.get("formula", "unavailable")),
        ("P / D / U", " / ".join(str(normalization.get(key, "unavailable")) for key in (
            "P_apex_points", "D_do_nothing_points_same_seed", "U_theoretical_max_points"))),
    ]
    race_rows = []
    if summary:
        for race in summary["races"]:
            positions = race.get("apex_positions") if isinstance(race.get("apex_positions"), dict) else {}
            seq = race.get("journal_seq")
            race_rows.append([
                f"{race['race']}/{summary['races_total']}", race.get("name", "unknown"), race.get("archetype", "unknown"),
                positions.get("Apex A", "?"), positions.get("Apex B", "?"), race.get("stops", "?"),
                race.get("sc_vsc_decisions", "?"), race["apex_points"], f"verified (journal seq {seq})" if seq is not None else "verified completion",
            ])
    comparison_html = f"<p class=\"muted\">{esc(comparison.get('reason', 'Unavailable.'))}</p>"
    if comparison.get("status") == "available":
        comparison_html = (
            f"<p class=\"muted\">{esc(comparison['match'])}</p>"
            + render_table(["Metric", "Frontier", "Reference", "Frontier − Reference"], [
                ["Constructors' points", comparison["frontier_points"], comparison["reference_points"], format_number(comparison["points_gap"])],
                ["Official normalized reward", f"{comparison['frontier_reward']:.8f}", f"{comparison['reference_reward']:.8f}", f"{comparison['reward_gap']:+.8f}"],
                ["Captured reference report", comparison["reference_report"], "matched", "no score recomputed"],
            ])
        )
    failure_html = f"<p class=\"muted\">{esc(failures.get('reason', 'No failure evidence supplied.'))}</p>"
    if failures.get("status") == "available":
        if failures.get("rows"):
            failure_html = (
                f"<p>{esc(failures['note'])} Confirmed rows in artifact: {esc(failures['confirmed_count'])}; showing up to three.</p>"
                + render_table(["Race", "Decision / lap", "Status / category", "Agent action", "Best public-info alternative", "Own-continuation loss ± SE", "Baseline-continuation loss"], [
                    [row["race"], f"{row['decision']} / {row['lap']}", f"{row['status']} / {row['category']}", row["agent"], row["best"],
                     f"{row['loss']:.3f} ± {row['se']:.3f}", f"{row['baseline_loss']:.3f}"]
                    for row in failures["rows"]
                ])
            )
        else:
            failure_html = "<p class=\"muted\">The supplied failure-analysis artifact contains no confirmed failures.</p>"
    diagnostics = []
    for error in errors:
        diagnostics.append(f"<li class=\"bad-text\"><strong>ERROR:</strong> {esc(error)}</li>")
    for warning in warnings:
        diagnostics.append(f"<li><strong>NOTE:</strong> {esc(warning)}</li>")
    if not diagnostics:
        diagnostics.append("<li>No artifact or presentation diagnostics.</li>")
    source_rows = [
        ("Official verifier report", context.get("report_path", "missing")),
        ("Sidecar evidence", context.get("evidence_dir", "missing")),
        ("Race detail source", summary.get("source") if summary else "unavailable"),
        ("Journal SHA-256", context.get("journal_sha256") or "unavailable"),
    ]
    css = """
:root{color-scheme:light dark;--bg:#f5f7fa;--panel:#fff;--text:#18212b;--muted:#5c6875;--line:#d7dee7;--accent:#d4212c;--ok:#167342;--bad:#a12622}
@media(prefers-color-scheme:dark){:root{--bg:#11171e;--panel:#19222c;--text:#edf2f7;--muted:#abb7c4;--line:#344252;--accent:#ff6971;--ok:#65d695;--bad:#ff8e87}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);font:15px/1.5 system-ui,-apple-system,Segoe UI,sans-serif}main{max-width:1180px;margin:auto;padding:28px}header{border-top:8px solid var(--accent);padding:22px 0}h1{font-size:2rem;margin:.2rem 0}h2{margin-top:0;font-size:1.15rem}.banner{display:inline-block;padding:6px 10px;border-radius:4px;font-weight:750;letter-spacing:.06em}.ok{background:var(--ok);color:#fff}.bad{background:var(--bad);color:#fff}.bad-text{color:var(--bad)}section{background:var(--panel);border:1px solid var(--line);border-radius:8px;padding:18px;margin:16px 0}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(210px,1fr));gap:12px}.metric{border-left:3px solid var(--accent);padding:8px 12px}.metric strong{display:block;font-size:1.7rem}.muted{color:var(--muted)}.table-wrap{overflow-x:auto}table{border-collapse:collapse;width:100%;font-variant-numeric:tabular-nums}th,td{text-align:left;border-bottom:1px solid var(--line);padding:8px;vertical-align:top}th{color:var(--muted);font-size:.82rem;text-transform:uppercase;letter-spacing:.035em}code{overflow-wrap:anywhere}li{margin:.35rem 0}footer{color:var(--muted);font-size:.86rem;padding:10px 0 24px}@media print{body{background:#fff;color:#000}main{max-width:none;padding:0}section{break-inside:avoid}}
"""
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>F1 Pit Wall — {esc(metadata.get('run_id', 'Harbor run'))}</title><style>{css}</style></head>
<body><main><header><span class="banner {banner_class}">{banner}</span><h1>F1 Pit Wall evaluation</h1>
<p>Benchmark <strong>{esc(benchmark_version(report))}</strong> · sealed Harbor + OpenCode evaluation · static post-run report</p></header>
<section><h2>Execution metadata</h2>{render_table(['Field','Value'], metadata_rows)}</section>
<section><h2>Completion and replay verification</h2>{render_table(['Check','Status','Evidence'], verification_rows)}</section>
<section><h2>Official result</h2><div class="grid"><div class="metric"><span>Apex constructors' points</span><strong>{esc(points)}</strong></div>
<div class="metric"><span>Normalized reward</span><strong>{esc(f'{reward:.8f}' if is_number(reward) else 'unavailable')}</strong></div>
<div class="metric"><span>Championship rank</span><strong>{esc(performance.get('championship_rank', 'unavailable'))}</strong></div></div>
<h3>Constructors' standings</h3>{render_table(['Team','Points'], standings) if standings else '<p class="muted">Standings unavailable.</p>'}
<h3>Verifier normalization (displayed, not recomputed)</h3>{render_table(['Field','Verifier value'], normalization_rows)}</section>
<section><h2>Race-by-race summary</h2>{render_table(['Race','Track','Archetype','Apex A pos.','Apex B pos.','Car stops','SC/VSC decisions','Apex points','Completion'], race_rows) if race_rows else '<p class="muted">No verified per-race result detail is available. Overall completion above is not substituted for invented race rows.</p>'}</section>
<section><h2>Frontier–Reference comparison</h2>{comparison_html}</section>
<section><h2>Representative failure evidence</h2>{failure_html}</section>
<section><h2>Diagnostics and provenance</h2><ul>{''.join(diagnostics)}</ul>{render_table(['Artifact','Source'], source_rows)}</section>
<footer>Official overall points and rewards come from verifier outputs; per-race details come from the journal-linked canonical replay. Arithmetic gaps are shown only for verified matched run pairs. Supplied counterfactual estimates are labelled separately. This report has no JavaScript, external assets, web server, or live-data dependency.</footer>
</main></body></html>
"""


def capture_artifacts(run_dir: Path, report_path: Path | None, trial_dir: Path | None) -> Path:
    capture = run_dir / CAPTURE_DIR
    (capture / "verifier").mkdir(parents=True, exist_ok=True)
    (capture / "evidence").mkdir(parents=True, exist_ok=True)
    (capture / "harbor").mkdir(parents=True, exist_ok=True)
    if report_path is not None:
        for name in ("report.json", "reward.txt", "test-stdout.txt", "test-stderr.txt"):
            source = report_path.with_name(name)
            if source.is_file():
                shutil.copy2(source, capture / "verifier" / name)
    if trial_dir is not None:
        evidence = trial_dir / "artifacts" / "evidence" / "f1sim"
        if evidence.is_dir():
            for source in evidence.iterdir():
                if source.is_file():
                    shutil.copy2(source, capture / "evidence" / source.name)
        for name in ("result.json", "config.json", "lock.json", "exception.txt", "trial.log"):
            source = trial_dir / name
            if source.is_file():
                shutil.copy2(source, capture / "harbor" / name)
        collection_manifest = trial_dir / "artifacts" / "manifest.json"
        if collection_manifest.is_file():
            shutil.copy2(collection_manifest, capture / "harbor" / "artifact-manifest.json")
    return capture


def inspect_and_render(args: argparse.Namespace) -> tuple[dict[str, Any], dict[str, Any]]:
    run_dir = args.run_dir.resolve()
    metadata_path = run_dir / "run.json"
    try:
        metadata = read_json(metadata_path)
        if not isinstance(metadata, dict):
            raise ValueError("run.json must contain an object")
    except ValueError:
        metadata = {"run_id": run_dir.name}
    metadata.setdefault("run_id", run_dir.name)
    metadata.setdefault("finished_at", utc_now())
    metadata.setdefault("python", platform.python_version())
    write_json(metadata_path, metadata)

    errors: list[str] = []
    warnings: list[str] = []
    report_path, discovery_errors = find_verifier_report(run_dir)
    errors.extend(discovery_errors)
    report: dict[str, Any] | None = None
    if report_path is not None:
        try:
            loaded = read_json(report_path)
            if not isinstance(loaded, dict):
                raise ValueError("verifier report.json must contain an object")
            report = loaded
        except ValueError as exc:
            errors.append(str(exc))
    trial_dir = report_path.parent.parent if report_path is not None else None
    evidence_dir = trial_dir / "artifacts" / "evidence" / "f1sim" if trial_dir is not None else run_dir / "missing-evidence"
    evidence_info: dict[str, Any] = {}
    evidence_errors: list[str] = []
    reward_text = None
    reward_errors: list[str] = []
    complete = False
    intact = False
    race_summary = None
    if report is not None and report_path is not None and trial_dir is not None:
        completion = report.get("completion") if isinstance(report.get("completion"), dict) else {}
        integrity = report.get("integrity") if isinstance(report.get("integrity"), dict) else {}
        complete = completion.get("complete") is True
        intact = integrity.get("intact") is True
        report_errors = validate_report(report)
        errors.extend(report_errors)
        evidence_info, evidence_errors = check_evidence(report, evidence_dir)
        errors.extend(evidence_errors)
        reward_text, reward_errors = check_reward(report, report_path)
        errors.extend(reward_errors)
        if intact and not evidence_errors and not report_errors:
            race_summary, race_warnings, race_errors = load_race_details(
                report, evidence_dir, evidence_info, args.benchmark_path, intact
            )
            warnings.extend(race_warnings)
            errors.extend(race_errors)
        else:
            warnings.append("Race progress withheld: verifier report, replay, or captured-evidence checks failed.")
    artifact_ok = bool(
        report is not None and not evidence_errors and not reward_errors
        and reward_text is not None and evidence_info.get("journal_sha256")
    )
    verified = bool(complete and intact and artifact_ok and not errors)
    comparison = load_reference_comparison(args, report or {}, verified)
    failures: dict[str, Any] = {"status": "unavailable", "reason": "No run artifact was available.", "rows": []}
    if trial_dir is not None:
        failures, failure_warnings = load_failure_evidence(args.failure_evidence, trial_dir, run_dir, verified)
        warnings.extend(failure_warnings)
    context = {
        "metadata": metadata,
        "report": report,
        "report_path": str(report_path) if report_path else None,
        "trial_dir": str(trial_dir) if trial_dir else None,
        "evidence_dir": str(evidence_dir),
        "journal_sha256": evidence_info.get("journal_sha256"),
        "reward_text": reward_text,
        "artifact_ok": artifact_ok,
        "verified": verified,
        "harbor_exit_code": args.harbor_exit_code,
        "errors": errors,
        "warnings": warnings,
        "race_summary": race_summary,
        "comparison": comparison,
        "failures": failures,
    }
    capture = capture_artifacts(run_dir, report_path, trial_dir)
    summary_path = capture / "race_summary.json"
    race_summary_sha256 = None
    if race_summary is not None:
        write_json(summary_path, race_summary)
        race_summary_sha256 = sha256_file(summary_path)
    else:
        summary_path.unlink(missing_ok=True)
    performance = (report or {}).get("performance")
    completion = (report or {}).get("completion")
    demo_exit = args.harbor_exit_code if args.harbor_exit_code else (0 if verified else EXIT_UNVERIFIED)
    result = {
        "schema_version": 1,
        "run_id": metadata["run_id"],
        "benchmark_version": benchmark_version(report or {}),
        "harbor_exit_code": args.harbor_exit_code,
        "demo_exit_code": demo_exit,
        "demo_success": verified and args.harbor_exit_code == 0,
        "verified": verified,
        "complete": complete,
        "integrity_intact": intact,
        "artifact_ok": artifact_ok,
        "journal_sha256": evidence_info.get("journal_sha256"),
        "race_summary_sha256": race_summary_sha256,
        "official_reward": (report or {}).get("reward"),
        "apex_constructors_points": performance.get("apex_constructors_points") if isinstance(performance, dict) else None,
        "races_total": (race_summary or {}).get("races_total") or (completion.get("races_total") if isinstance(completion, dict) else None),
        "race_events": [{"race": race["race"], "verified": True, "journal_seq": race.get("journal_seq")}
                        for race in (race_summary or {}).get("races", [])],
        "report_html": str(args.output.resolve()),
        "capture_dir": str(capture),
        "errors": errors,
        "warnings": warnings,
    }
    write_json(run_dir / "demo_result.json", result)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(render_html(context), encoding="utf-8")
    return context, result


def finalize_command(args: argparse.Namespace) -> int:
    try:
        context, result = inspect_and_render(args)
    except Exception as exc:
        print(f"Demo finalization failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        return EXIT_INVALID
    summary = context.get("race_summary")
    emit_progress(summary, sys.stdout, args.tty, args.replay_delay)
    for warning in context["warnings"]:
        print(f"NOTE: {warning}", file=sys.stderr)
    for error in context["errors"]:
        print(f"ERROR: {error}", file=sys.stderr)
    print(f"Verification: {'PASS' if result['verified'] else 'FAIL'}; Harbor exit: {args.harbor_exit_code}")
    print(f"Report: {args.output.resolve()}")
    return result["demo_exit_code"]


def replay_command(args: argparse.Namespace) -> int:
    capture = args.run_dir / CAPTURE_DIR
    result_path = args.run_dir / "demo_result.json"
    summary_path = capture / "race_summary.json"
    report_path = capture / "verifier" / "report.json"
    evidence_dir = capture / "evidence"
    try:
        result = read_json(result_path)
        if not isinstance(result, dict) or result.get("demo_success") is not True or result.get("harbor_exit_code") != 0:
            raise ValueError("the captured run was not a successful verified Harbor execution")
        report = read_json(report_path)
        if not isinstance(report, dict):
            raise ValueError("captured verifier report must contain an object")
        validation_errors = validate_report(report)
        evidence_info, evidence_errors = check_evidence(report, evidence_dir)
        _, reward_errors = check_reward(report, report_path)
        if validation_errors or evidence_errors or reward_errors:
            raise ValueError("; ".join(validation_errors + evidence_errors + reward_errors))
        digest = evidence_info.get("journal_sha256")
        if result.get("journal_sha256") != digest:
            raise ValueError("captured journal differs from demo result")
        if result.get("race_summary_sha256") != sha256_file(summary_path):
            raise ValueError("race summary digest differs from demo result")
        summary = read_json(summary_path)
        if not isinstance(summary, dict):
            raise ValueError("race summary must contain an object")
        validate_race_summary(summary, report, digest)
        completed, total = verified_events(summary)
        if not isinstance(total, int) or completed != list(range(1, total + 1)):
            raise ValueError("race summary does not contain every verified completion event")
        emit_progress(summary, sys.stdout, args.tty, args.replay_delay)
        return 0
    except (ValueError, OSError) as exc:
        print(f"Cannot replay demo artifacts: {exc}", file=sys.stderr)
        emit_progress(None, sys.stdout, args.tty, args.replay_delay)
        return EXIT_UNVERIFIED


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    finalize = commands.add_parser("finalize", help="capture and render one fresh Harbor run directory")
    finalize.add_argument("--run-dir", type=Path, required=True)
    finalize.add_argument("--benchmark-path", type=Path, required=True)
    finalize.add_argument("--harbor-exit-code", type=int, default=0)
    finalize.add_argument("--output", type=Path)
    finalize.add_argument("--tty", choices=("auto", "always", "never"), default=os.environ.get("F1_PROGRESS", "auto"))
    finalize.add_argument("--replay-delay", type=float, default=0.0)
    finalize.add_argument("--reference-report", type=Path)
    finalize.add_argument("--reference-evidence", type=Path)
    finalize.add_argument("--reference-seed", type=Path)
    finalize.add_argument("--seed-path", type=Path)
    finalize.add_argument("--failure-evidence", type=Path)
    finalize.set_defaults(func=finalize_command)
    replay = commands.add_parser("replay", help="print the captured verified post-run ASCII replay")
    replay.add_argument("--run-dir", type=Path, required=True)
    replay.add_argument("--tty", choices=("auto", "always", "never"), default="auto")
    replay.add_argument("--replay-delay", type=float, default=0.0)
    replay.set_defaults(func=replay_command)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if getattr(args, "harbor_exit_code", 0) < 0 or getattr(args, "harbor_exit_code", 0) > 255:
        parser.error("--harbor-exit-code must be in [0, 255]")
    if getattr(args, "replay_delay", 0.0) < 0 or not math.isfinite(args.replay_delay):
        parser.error("--replay-delay must be a finite non-negative number")
    if args.command == "finalize":
        if args.output is None:
            args.output = args.run_dir / "report.html"
        args.run_dir.mkdir(parents=True, exist_ok=True)
        if not args.benchmark_path.is_dir():
            print(f"Benchmark path is not a directory: {args.benchmark_path}", file=sys.stderr)
            return EXIT_INVALID
        for name in ("reference_report", "reference_evidence", "reference_seed", "failure_evidence", "seed_path"):
            value = getattr(args, name)
            if isinstance(value, str):
                setattr(args, name, Path(value))
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
