"""Track A coefficient model. All values are synthetic placeholders loaded from JSON.

Functions take an explicit coefficient dict so that solvers and tests can run
ablations (one mechanic switched off) without touching module state.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any, Dict, Mapping

COEFFICIENT_FIXTURE = Path(__file__).with_name("fixtures") / "track_a_coefficients.json"
COMPONENTS = ("ICE", "turbo", "energy_store")
MECHANICS = (
    "wear_pace",          # wear slows the car
    "reliability",        # wear raises retirement probability
    "allocation_limit",   # free units are scarce (ablation: unlimited)
    "shared_pool",        # free units are shared by both drivers (ablation: split per driver)
    "grid_penalty",       # replacements without a free unit cost grid places (ablation: none)
    "team_profiles",      # track-archetype pace profile per team
    "overtaking",         # track-dependent overtaking resistance
    "tyre_degradation",   # track-dependent tyre degradation
    "compound_choice",    # B1: PIT chooses a compound (ablation: MEDIUM only)
    "tyre_cliff",         # B1: tyres fall off beyond their life (ablation: linear only)
    "two_compound_rule",  # B1: two compounds per race (ablation: no rule)
    "pit_loss_by_track",  # B2: pit-lane loss depends on the track (ablation: 20 s everywhere)
    "double_stack_queue", # B2: shared crew queue for same-team stops (ablation: no queue)
    "tyre_warmup",        # B2: slower out-lap on new tyres (ablation: none)
    "long_race_format",   # B3: 14 decisions per race (ablation: legacy 3-decision short format)
    "neutralization_dynamics",  # B4: SC/VSC durations, compression, slow laps (ablation: B3 i.i.d. events)
)


def load(path: Path = COEFFICIENT_FIXTURE) -> Dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if value.get("data_status") != "synthetic_placeholder":
        raise ValueError("coefficients must be marked synthetic_placeholder")
    if tuple(value["components"]["names"]) != COMPONENTS:
        raise ValueError("unexpected component names")
    return value


DEFAULT = load()


def ablate(coeffs: Mapping[str, Any], *mechanics: str) -> Dict[str, Any]:
    """Return a copy with the named mechanics switched off."""
    out = copy.deepcopy(dict(coeffs))
    for mechanic in mechanics:
        if mechanic not in MECHANICS:
            raise ValueError(f"unknown mechanic {mechanic}")
        if mechanic == "wear_pace":
            out["components"]["pace_loss_sec_per_lap"]["k"] = {c: 0.0 for c in COMPONENTS}
        elif mechanic == "reliability":
            out["components"]["reliability"]["r"] = {c: 0.0 for c in COMPONENTS}
        elif mechanic == "allocation_limit":
            out["allocation"]["free_units_per_team"] = 10_000
        elif mechanic == "shared_pool":
            out["allocation"]["free_units_are_shared_between_drivers"] = False
        elif mechanic == "grid_penalty":
            out["allocation"]["grid_drop_when_no_free_unit"] = {c: 0 for c in COMPONENTS}
        elif mechanic == "team_profiles":
            profiles = out["track_performance"]["team_archetype_pace_offset_sec_per_lap"]
            for team, table in profiles.items():
                if team != "note":
                    profiles[team] = {k: 0.0 for k in table}
        elif mechanic == "overtaking":
            # Same racing model, but difficulty no longer varies by track.
            out["track_performance"]["overtaking"]["fixed_difficulty"] = 0.5
        elif mechanic == "tyre_degradation":
            out["track_performance"]["tyre_degradation_multiplier"] = None
        elif mechanic == "compound_choice":
            out["tyres"]["compound_choice"] = False
        elif mechanic == "tyre_cliff":
            out["tyres"]["cliff"]["cliff_sec_per_lap_per_lap"] = 0.0
        elif mechanic == "two_compound_rule":
            out["tyres"]["two_compound_rule"]["enabled"] = False
        elif mechanic == "pit_loss_by_track":
            table = out["pit_stops"]["loss_green_sec_by_archetype"]
            mean = sum(table.values()) / len(table)
            out["pit_stops"]["loss_green_sec_by_archetype"] = {k: mean for k in table}
        elif mechanic == "double_stack_queue":
            out["pit_stops"]["double_stack_queue_sec"] = 0.0
        elif mechanic == "neutralization_dynamics":
            out["neutralization"]["enabled"] = False
        elif mechanic == "long_race_format":
            out["race_format"]["use"] = "short"
        elif mechanic == "tyre_warmup":
            out["pit_stops"]["out_lap_warmup_sec"] = {k: 0.0 for k in out["pit_stops"]["out_lap_warmup_sec"]}
    out.setdefault("ablated", [])
    out["ablated"] = sorted(set(out["ablated"]) | set(mechanics))
    return out


def pace_loss(wears: Mapping[str, float], stress: float, coeffs: Mapping[str, Any]) -> float:
    k = coeffs["components"]["pace_loss_sec_per_lap"]["k"]
    return sum(k[c] * stress * wears[c] ** 2 for c in COMPONENTS)


def dnf_probability(wears: Mapping[str, float], stress: float, coeffs: Mapping[str, Any]) -> float:
    rel = coeffs["components"]["reliability"]
    risk = rel["base"] + sum(rel["r"][c] * stress * max(0.0, wears[c] - rel["onset"]) ** 2
                             for c in COMPONENTS)
    return min(rel["cap"], risk)


def degradation_multiplier(tyre_degradation: float, coeffs: Mapping[str, Any]) -> float:
    # Ablation: every track behaves like the reference degradation 0.5 (multiplier 1.0).
    return 1.0 if coeffs["track_performance"]["tyre_degradation_multiplier"] is None else 0.5 + tyre_degradation


def team_offset(team: str, archetype: str, coeffs: Mapping[str, Any]) -> float:
    return coeffs["track_performance"]["team_archetype_pace_offset_sec_per_lap"][team][archetype]


def overtaking_model(coeffs: Mapping[str, Any]):
    return coeffs["track_performance"]["overtaking"]


def overtaking_difficulty(track_value: float, coeffs: Mapping[str, Any]) -> float:
    fixed = coeffs["track_performance"]["overtaking"].get("fixed_difficulty")
    return track_value if fixed is None else fixed


def grid_drop(component: str, coeffs: Mapping[str, Any]) -> int:
    return int(coeffs["allocation"]["grid_drop_when_no_free_unit"][component])


def max_wear_for_use(coeffs: Mapping[str, Any]) -> float:
    return coeffs["components"]["max_wear_for_use"]


def wear_increment(component: str, stress: float, coeffs: Mapping[str, Any]) -> float:
    return stress * coeffs["components"]["wear_per_unit_stress"][component]


def tyre_model(coeffs: Mapping[str, Any]) -> Dict[str, Any]:
    """Race-config tyre block (B1): compounds, cliff, two-compound rule, rival compound rule."""
    tyres = coeffs["tyres"]
    return {
        "compound_choice": bool(tyres["compound_choice"]),
        "compounds": copy.deepcopy(tyres["compounds"]),
        "cliff_sec_per_lap_per_lap": float(tyres["cliff"]["cliff_sec_per_lap_per_lap"]),
        "two_compound_rule": bool(tyres["two_compound_rule"]["enabled"]),
        "two_compound_penalty_sec": float(tyres["two_compound_rule"]["penalty_sec"]),
        "rival_soft_max_laps": int(tyres["rival_compound_policy"]["soft_max_laps"]),
        "rival_medium_max_laps": int(tyres["rival_compound_policy"]["medium_max_laps"]),
    }


def pit_model(archetype: str, coeffs: Mapping[str, Any]) -> Dict[str, Any]:
    """Race-config pit block (B2) for one track."""
    pit = coeffs["pit_stops"]
    green = float(pit["loss_green_sec_by_archetype"][archetype])
    return {
        "loss_sec": {status: green * float(f) for status, f in pit["status_factor"].items()},
        "double_stack_queue_sec": float(pit["double_stack_queue_sec"]),
        "out_lap_warmup_sec": {k: float(v) for k, v in pit["out_lap_warmup_sec"].items()},
    }


def race_format(coeffs: Mapping[str, Any]) -> Dict[str, Any]:
    """Race-config format block (B3): decision laps, segment length, grid spacing, event odds."""
    fmt = coeffs["race_format"][coeffs["race_format"]["use"]]
    every = int(fmt["decision_every_laps"])
    laps = int(fmt["laps"])
    decision_laps = list(range(int(fmt["first_decision_lap"]), laps - every + 1, every))
    if decision_laps[-1] + every != laps:
        raise ValueError("race format must end exactly one segment after the last decision")
    out = {"decision_laps": decision_laps, "segment_laps": every,
           "grid_gap_scale": float(fmt["grid_gap_scale"]),
           "start_tyre_age": fmt["start_tyre_age_laps"],
           "event_probs": {k: float(v) for k, v in fmt["event_probabilities_per_decision"].items()},
           "neutralization": None}
    neutral = coeffs.get("neutralization")
    if coeffs["race_format"]["use"] == "long" and neutral and neutral["enabled"]:
        out["neutralization"] = {
            "start": {k: float(v) for k, v in neutral["start_probability_per_green_decision"].items()},
            "duration": {status: {int(d): float(p) for d, p in table.items()}
                         for status, table in neutral["duration_segments"].items()},
            "cooldown": int(neutral["green_segments_after_neutralization"]),
            "sc_gap": float(neutral["sc_compressed_gap_sec"]),
            "lap_time_factor": {k: float(v) for k, v in neutral["lap_time_factor"].items()},
            "tyre_age_laps": {k: int(v) for k, v in neutral["tyre_age_laps_per_segment"].items()},
        }
    return out
