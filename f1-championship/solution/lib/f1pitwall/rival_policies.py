"""Opt-in rival pit-strategy variants (B5-P1). Not used unless a race config names one.

The default rival behaviour stays engine._rival_action ("public"), which is the published rule.
Variants are reasonable public-information strategies for robustness and opponent-sensitivity
analysis. Each sees only what a pit wall could see: its own tyres, laps remaining, the current
SC/VSC status, the running order and gaps, and the cars' visible compounds and tyre ages.
All respect the two-compound rule. None reads seeds, future events or retirement draws.
"""

from __future__ import annotations

from typing import Any, Dict, List

VARIANTS = ("public", "conservative_2stop", "opportunistic", "undercut", "long_stint", "event_aware")


def _compound(car, laps_remaining, tyres, prefer_hard=False):
    from .engine import rival_compound
    if prefer_hard and laps_remaining > 10 and not (set(car["compounds_used"]) == {"HARD"}):
        return "HARD"
    return rival_compound(car, laps_remaining, tyres)


def decide(name: str, car: Dict[str, Any], state: Dict[str, Any], status: str, step_index: int,
           decision_count: int, tyres: Dict[str, Any], laps_remaining: int) -> str:
    """Rival action for `car` under variant `name` ('STAY' or 'PIT_<compound>')."""
    life = tyres["compounds"][car["compound"]]["life_laps"]
    age = car["tyre_age"]
    stops = len(car["compounds_used"]) - 1
    last = step_index == decision_count - 1
    needs_second = tyres["two_compound_rule"] and len(set(car["compounds_used"])) < 2
    if needs_second and last:
        return "PIT_" + _compound(car, laps_remaining, tyres)
    neutral = status in ("SC", "VSC")
    total = laps_remaining + state["config"]["decision_laps"][step_index]  # race length
    lap = total - laps_remaining
    pit = False
    prefer_hard = False
    if name == "conservative_2stop":
        targets = (round(total / 3), round(2 * total / 3))
        due = stops < 2 and lap >= targets[stops]
        near = stops < 2 and lap >= targets[stops] - 3
        pit = (due or (neutral and near)) and laps_remaining >= 6
    elif name == "opportunistic":
        pit = (age >= life and not last) or (neutral and age >= 4 and laps_remaining >= 9)
    elif name == "undercut":
        ahead = _car_ahead(state, car)
        undercut = (ahead is not None and ahead["gap"] < 2.0 and ahead["car"]["tyre_age"] > age
                    and age >= life - 4 and laps_remaining >= 9)
        pit = (age >= life and not last) or undercut or (status == "SC" and age >= 7)
    elif name == "long_stint":
        prefer_hard = True
        pit = (age >= life + 3 and not last and laps_remaining > 3) or (status == "SC" and age >= 12)
    elif name == "event_aware":
        # Plans around neutralizations: stop early in any SC window, take a VSC only with older
        # tyres, and under GREEN stretch two laps past tyre life to keep an SC window open.
        if status == "SC":
            pit = age >= 4 and laps_remaining >= 9
        elif status == "VSC":
            pit = age >= 7 and laps_remaining >= 9
        else:
            pit = age >= life + 2 and not last and laps_remaining > 3
    else:
        raise ValueError(f"unknown rival policy {name}")
    if not pit:
        return "STAY"
    return "PIT_" + _compound(car, laps_remaining, tyres, prefer_hard)


def _car_ahead(state, car):
    order: List[Dict[str, Any]] = sorted(state["cars"], key=lambda c: (c["elapsed"], c["name"]))
    index = next(i for i, c in enumerate(order) if c["name"] == car["name"])
    if index == 0:
        return None
    ahead = order[index - 1]
    return {"car": ahead, "gap": car["elapsed"] - ahead["elapsed"]}
