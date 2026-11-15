"""Validated, public C5 setup-model loading. All coefficients are fixture-owned."""

from __future__ import annotations

import copy
import json
import math
from pathlib import Path
from typing import Any

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "c5_setups.json"
PROGRAMS = ("SETUP_TEST", "LONG_RUN", "QUALI_SIM")
RUN_PLANS = ("ONE_RUN", "TWO_RUN")
METRICS = ("qualifying_pace_offset_sec", "long_run_pace_offset_sec_per_lap", "deg_multiplier_factor")
FORBIDDEN_PARTS = (
    "seed", "secret", "rng", "hidden", "true_effect", "true_effects",
    "future_draw", "normal_draw", "random_draw", "race_modifier",
)


def finite_number(value: Any, *, positive: bool = False, nonnegative: bool = False) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("expected a finite number")
    number = float(value)
    if not math.isfinite(number):
        raise ValueError("expected a finite number")
    if positive and number <= 0:
        raise ValueError("expected a positive number")
    if nonnegative and number < 0:
        raise ValueError("expected a non-negative number")
    return number


def integers(value: Any, *, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise ValueError(f"expected an integer >= {minimum}")
    return value


def rng_integer(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value < 2**256:
        raise ValueError("rng_key must be a non-negative integer below 2^256")
    return value


def reject_secret_content(value: Any, path: str = "") -> None:
    """Reject secret-shaped keys/values before exposing public JSON."""
    if isinstance(value, dict):
        for key, child in value.items():
            lowered = str(key).lower()
            if any(part in lowered for part in FORBIDDEN_PARTS):
                raise ValueError(f"private field in public C5 data: {path}{key}")
            reject_secret_content(child, f"{path}{key}.")
    elif isinstance(value, (list, tuple)):
        for index, child in enumerate(value):
            reject_secret_content(child, f"{path}{index}.")
    elif isinstance(value, int) and not isinstance(value, bool) and value.bit_length() > 64:
        raise ValueError(f"possible secret oversized integer in public C5 data at {path}")


def load_model(archetype: str) -> dict[str, Any]:
    """Return a fresh public model; the prior is not the hidden per-weekend draw."""
    raw = json.loads(FIXTURE.read_text(encoding="utf-8"))
    if raw.get("schema_version") != 1 or raw.get("data_status") != "synthetic_only":
        raise ValueError("unsupported C5 fixture version/provenance")
    if raw["sources"] or archetype not in raw["archetypes"]:
        raise ValueError("unknown C5 archetype or unsourced coefficient claim")
    defaults = raw["defaults"]
    if defaults["default_setup_id"] not in raw["setups"]:
        raise ValueError("unknown default setup")
    if defaults["sessions_total"]["value"] != 2:
        raise ValueError("C5 v1 requires exactly two practice sessions")
    for setup_id, setup in raw["setups"].items():
        if not isinstance(setup_id, str) or not setup_id or "provenance" in setup_id:
            raise ValueError("invalid setup identifier")
        if set(setup["priors"]) != set(METRICS):
            raise ValueError("setup prior metrics are incomplete")
        for metric, prior in setup["priors"].items():
            finite_number(prior["mean"])
            finite_number(prior["sd"], nonnegative=True)
            if prior.get("provenance") != "synthetic":
                raise ValueError("every setup prior requires synthetic provenance")
    programs = raw["noise_model"]["programs"]
    if set(programs) != set(PROGRAMS):
        raise ValueError("C5 program set is incomplete")
    for program in PROGRAMS:
        if programs[program]["metric"] not in METRICS:
            raise ValueError("unknown program metric")
        finite_number(programs[program]["observation_sd_per_lap"]["value"], positive=True)
    model = {
        "schema_version": 1,
        "data_status": "synthetic_only",
        "archetype": archetype,
        "default_setup_id": defaults["default_setup_id"],
        "sessions_total": defaults["sessions_total"]["value"],
        "lap_budget_per_driver": integers(defaults["lap_budget_per_driver"]["value"], minimum=1),
        "ci95_z": finite_number(defaults["ci95_z"]["value"], positive=True),
        "rivals_run_plan": defaults["rivals_run_plan"],
        "setups": copy.deepcopy(raw["setups"]),
        "noise_model": copy.deepcopy(raw["noise_model"]),
        "reference": copy.deepcopy(raw["reference"]),
        "base_deg_time_loss_sec_per_lap": finite_number(
            raw["archetypes"][archetype]["base_deg_time_loss_sec_per_lap"]["value"], nonnegative=True
        ),
        "sources": [],
    }
    integers(model["lap_budget_per_driver"], minimum=1)
    model["noise_model"]["qualifying_sd_per_run"] = finite_number(
        raw["noise_model"]["qualifying_sd_per_run"]["value"], positive=True
    )
    reject_secret_content(model)
    return model


def prior(model: dict[str, Any], setup_id: str, metric: str) -> tuple[float, float]:
    try:
        value = model["setups"][setup_id]["priors"][metric]
    except KeyError as exc:
        raise ValueError(f"unknown setup or metric: {setup_id}/{metric}") from exc
    return float(value["mean"]), float(value["sd"])


def validate_setup(model: dict[str, Any], setup_id: Any) -> str:
    if not isinstance(setup_id, str) or setup_id not in model["setups"]:
        raise ValueError(f"unknown C5 setup: {setup_id!r}")
    return setup_id


def observation_sd(model: dict[str, Any], program: str) -> float:
    if program not in PROGRAMS:
        raise ValueError(f"unknown C5 practice program: {program!r}")
    return float(model["noise_model"]["programs"][program]["observation_sd_per_lap"]["value"])
