"""M6 driver objectives and team-order compliance (independent, opt-in).

The caller owns the seeded random stream and supplies one draw. This module exposes
the public probability and explanation, never the private draw. It does not update
race physics, constructors' points, rewards, or the authoritative engine.
"""

from __future__ import annotations

import copy
import json
import math
from pathlib import Path
from typing import Any

FIXTURE = Path(__file__).with_name("fixtures") / "m6_compliance.json"
SUPPORTED_ORDERS = {"HOLD", "KEEP_ORDER", "REQUEST_GIVE_BACK"}


def load_m6_config(path: Path = FIXTURE) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError("invalid M6 fixture") from exc
    if (payload.get("schema_version") != 1
            or payload.get("data_status") != "synthetic_provisional_not_fia_calibrated"):
        raise ValueError("M6 fixture must be versioned and explicitly provisional")
    p = payload.get("parameters") or {}
    required = {"base_compliance", "minimum_compliance", "maximum_reduction",
                "gap_full_effect_points", "late_season_horizon_races",
                "early_season_pressure_weight", "order_adjustments"}
    if set(p) != required or set(p["order_adjustments"]) != SUPPORTED_ORDERS:
        raise ValueError("invalid M6 parameter fields")
    numeric = [p[key] for key in required - {"order_adjustments"}] + list(p["order_adjustments"].values())
    if any(isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value)
           for value in numeric):
        raise ValueError("M6 parameters must be finite numbers")
    if not (0 <= p["minimum_compliance"] <= p["base_compliance"] <= 1
            and 0 <= p["maximum_reduction"] <= 1
            and p["gap_full_effect_points"] > 0
            and p["late_season_horizon_races"] > 0
            and 0 <= p["early_season_pressure_weight"] <= 1):
        raise ValueError("M6 parameters are out of bounds")
    return copy.deepcopy(payload)


def wdc_standings(driver_points: dict[str, int | float], teams: dict[str, list[str]],
                  races_remaining: int) -> dict[str, Any]:
    if isinstance(races_remaining, bool) or not isinstance(races_remaining, int) or races_remaining < 0:
        raise ValueError("races_remaining must be a non-negative integer")
    assigned = [driver for drivers in teams.values() for driver in drivers]
    if len(assigned) != len(set(assigned)) or set(assigned) != set(driver_points):
        raise ValueError("every driver must belong to exactly one team")
    if any(len(drivers) != 2 for drivers in teams.values()):
        raise ValueError("M6 reduced contract requires two drivers per team")
    if any(isinstance(points, bool) or not isinstance(points, (int, float)) or not math.isfinite(points)
           or points < 0 for points in driver_points.values()):
        raise ValueError("driver points must be finite and non-negative")
    teammate = {}
    team_of = {}
    for team, drivers in teams.items():
        teammate[drivers[0]], teammate[drivers[1]] = drivers[1], drivers[0]
        team_of.update({driver: team for driver in drivers})
    ordered = sorted(driver_points, key=lambda driver: (-driver_points[driver], driver))
    return {"races_remaining": races_remaining,
            "drivers": [{"position": index + 1, "driver": driver, "team": team_of[driver],
                         "points": driver_points[driver], "teammate": teammate[driver],
                         "gap_to_teammate": driver_points[driver] - driver_points[teammate[driver]]}
                        for index, driver in enumerate(ordered)]}


def compliance_probability(gap_to_teammate: float, races_remaining: int, order: str,
                           config: dict[str, Any]) -> float:
    if order not in SUPPORTED_ORDERS:
        raise ValueError("M6 does not cover this order")
    if (isinstance(gap_to_teammate, bool) or not isinstance(gap_to_teammate, (int, float))
            or not math.isfinite(gap_to_teammate)):
        raise ValueError("gap_to_teammate must be finite")
    if isinstance(races_remaining, bool) or not isinstance(races_remaining, int) or races_remaining < 0:
        raise ValueError("races_remaining must be a non-negative integer")
    p = config["parameters"]
    lead_pressure = min(1.0, max(0.0, gap_to_teammate) / p["gap_full_effect_points"])
    horizon = p["late_season_horizon_races"]
    late = 1.0 - min(races_remaining, horizon) / horizon
    season_pressure = p["early_season_pressure_weight"] + (1 - p["early_season_pressure_weight"]) * late
    value = (p["base_compliance"] + p["order_adjustments"][order]
             - p["maximum_reduction"] * lead_pressure * season_pressure)
    return round(min(1.0, max(p["minimum_compliance"], value)), 6)


def public_compliance_observation(standings: dict[str, Any], config: dict[str, Any],
                                  enabled: bool) -> dict[str, Any]:
    drivers = []
    for row in standings["drivers"]:
        probabilities = {order: (compliance_probability(row["gap_to_teammate"],
                                                        standings["races_remaining"], order, config)
                                  if enabled else 1.0)
                         for order in sorted(SUPPORTED_ORDERS)}
        drivers.append({**copy.deepcopy(row), "order_compliance_probability": probabilities})
    return {"m6_enabled": enabled, "races_remaining": standings["races_remaining"],
            "driver_standings": drivers, "profile_status": config["data_status"],
            "profile_inputs": ["public_gap_to_teammate", "public_races_remaining", "order"]}


def resolve_order_compliance(order: str, affected_driver: str, probability: float,
                             *, enabled: bool, seeded_draw: float | None = None) -> dict[str, Any]:
    if order not in SUPPORTED_ORDERS:
        raise ValueError("M6 does not cover this order")
    if not isinstance(affected_driver, str) or not affected_driver:
        raise ValueError("affected_driver is required")
    if isinstance(probability, bool) or not isinstance(probability, (int, float)) or not 0 <= probability <= 1:
        raise ValueError("probability must be within [0,1]")
    if not enabled:
        return {"requested_order": order, "effective_order": order, "complied": True,
                "compliance_probability": 1.0, "event": None}
    if (isinstance(seeded_draw, bool) or not isinstance(seeded_draw, (int, float))
            or not math.isfinite(seeded_draw) or not 0 <= seeded_draw < 1):
        raise ValueError("enabled M6 requires a supplied seeded draw in [0,1)")
    complied = seeded_draw < probability
    event = None if complied else {
        "type": "ORDER_DECLINED", "driver": affected_driver, "order": order,
        "effective_order": "RACE", "public_reason": "WDC_COMPLIANCE_PROFILE",
        "compliance_probability": probability,
    }
    return {"requested_order": order, "effective_order": order if complied else "RACE",
            "complied": complied, "compliance_probability": probability, "event": event}
