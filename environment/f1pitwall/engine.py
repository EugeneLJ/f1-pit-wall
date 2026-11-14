"""Public deterministic one-decision race model.

The verifier contains its own trusted implementation and never imports this
agent-visible module.
"""

from __future__ import annotations
from typing import Any

POINTS = (25, 18, 15, 12, 10, 8, 6, 4)
RIVALS = (("Rival 1", 100.0), ("Rival 2", 102.0), ("Rival 3", 104.0),
          ("Rival 4", 106.0), ("Rival 5", 109.0), ("Rival 6", 112.0))
BASE_REMAINING = {"driver_a": 105.0, "driver_b": 108.0}
ACTION_DELTA = {
    "driver_a": {"PIT": -4.0, "STAY": 3.0},
    "driver_b": {"PIT": 5.0, "STAY": -3.0},
}
OBSERVATION = {
    "race": "Harbor Sprint", "lap": 18, "laps_total": 20,
    "decision_points_remaining": 1,
    "drivers": {
        "driver_a": {"tyre": "SOFT", "tyre_age": 14, "position": 3},
        "driver_b": {"tyre": "HARD", "tyre_age": 6, "position": 5},
    },
    "legal_actions": ["PIT", "STAY"],
}
RULES = {
    "lower_time_is_better": True, "points_by_position": list(POINTS),
    "rival_remaining_times": dict(RIVALS),
    "apex_base_remaining_times": BASE_REMAINING,
    "action_time_deltas": ACTION_DELTA,
    "ties": "Rivals win exact ties; no ties occur for legal actions.",
}


def validate_action(action: Any) -> dict[str, str]:
    if not isinstance(action, dict) or set(action) != {"driver_a", "driver_b"}:
        raise ValueError("action must contain exactly driver_a and driver_b")
    clean = {}
    for driver in ("driver_a", "driver_b"):
        choice = action[driver]
        if choice not in ("PIT", "STAY"):
            raise ValueError(f"{driver} must be PIT or STAY")
        clean[driver] = choice
    return clean


def evaluate_action(action: Any) -> dict[str, Any]:
    clean = validate_action(action)
    field = list(RIVALS)
    for driver, display in (("driver_a", "Apex A"), ("driver_b", "Apex B")):
        field.append((display, BASE_REMAINING[driver] + ACTION_DELTA[driver][clean[driver]]))
    field.sort(key=lambda item: item[1])
    classification, team_points = [], 0
    for index, (name, time) in enumerate(field):
        points = POINTS[index]
        classification.append({"position": index + 1, "driver": name, "time": time, "points": points})
        if name.startswith("Apex"):
            team_points += points
    return {"action": clean, "classification": classification, "constructors_points": team_points}
