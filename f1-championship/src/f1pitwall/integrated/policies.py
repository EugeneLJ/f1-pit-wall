"""Deterministic scripted Chief policies for integrated modes (B6-B).

Each policy maps ONE team-local observation to an action. They use only fields present in
that observation (own cars, public classification, track status, published models), so they
are legal equal-information competitors, not oracles. The pit rules mirror the opt-in rival
variants of B5-P1 (`rival_policies.py`); `baseline` is the published P0 heuristic
(`solution/play.py`); `coordinator` adds team orders and commitments on top of `baseline`.
"""

from __future__ import annotations

from typing import Any, Callable, Dict, Optional

POLICIES = ("baseline", "conservative_2stop", "opportunistic", "undercut", "long_stint",
            "event_aware", "coordinator")


def component_action(obs: Dict[str, Any]) -> Dict[str, Any]:
    decisions = []
    for driver, state in obs["controlled_drivers"].items():
        for component, info in state["components"].items():
            decisions.append({"driver": driver, "component": component,
                              "action": "USE" if "USE" in info["legal_actions"] else "REPLACE"})
    return {"type": "COMPONENT_DECISION", "decisions": decisions}


def _compound(race, key, prefer_hard=False):
    remaining = race["laps_remaining"]
    used = set(race["drivers"][key].get("compounds_used", []))
    if prefer_hard and remaining > 10 and used != {"HARD"}:
        return "HARD"
    compound = "SOFT" if remaining <= 6 else "MEDIUM" if remaining <= 14 else "HARD"
    if used == {compound}:
        compound = {"SOFT": "MEDIUM", "HARD": "MEDIUM", "MEDIUM": "SOFT" if remaining <= 10 else "HARD"}[compound]
    return compound


def _ahead(race, key):
    name = race["drivers"][key]["name"]
    order = race["classification"]
    i = next(k for k, e in enumerate(order) if e["driver"] == name)
    if i == 0:
        return None
    return order[i - 1], order[i]["elapsed"] - order[i - 1]["elapsed"]


def _wants(name: str, race: Dict[str, Any], key: str) -> bool:
    car = race["drivers"][key]
    status, remaining = race["track_status"], race["laps_remaining"]
    life = race["tyre_life_laps"][car["compound"]]
    age, seg = car["tyre_age"], race["segment_laps"]
    last = race["decision_index"] == race["decision_count"]
    stops = len(car["compounds_used"]) - 1
    total = race["laps_total"]
    lap = total - remaining
    neutral = status in ("SC", "VSC")
    if name in ("baseline", "coordinator"):
        threshold = {"SC": 6, "VSC": 8}.get(status, 99)
        worn_soft = car["compound"] == "SOFT" and age >= 8 and race["decision_index"] == 1
        end_of_life = age >= life and remaining >= 3 * seg
        return (age >= threshold and remaining > seg) or worn_soft or end_of_life
    if name == "conservative_2stop":
        targets = (round(total / 3), round(2 * total / 3))
        due = stops < 2 and lap >= targets[stops]
        near = stops < 2 and lap >= targets[stops] - 3
        return (due or (neutral and near)) and remaining >= 6
    if name == "opportunistic":
        return (age >= life and not last) or (neutral and age >= 4 and remaining >= 9)
    if name == "undercut":
        ahead = _ahead(race, key)
        under = (ahead is not None and ahead[1] < 2.0 and ahead[0]["tyre_age"] > age
                 and age >= life - 4 and remaining >= 9)
        return (age >= life and not last) or under or (status == "SC" and age >= 7)
    if name == "long_stint":
        return (age >= life + 3 and not last and remaining > 3) or (status == "SC" and age >= 12)
    if name == "event_aware":
        if status == "SC":
            return age >= 4 and remaining >= 9
        if status == "VSC":
            return age >= 7 and remaining >= 9
        return age >= life + 2 and not last and remaining > 3
    raise ValueError(f"unknown policy {name}")


def race_action(name: str, obs: Dict[str, Any]) -> Dict[str, Any]:
    race = obs["race_progress"]
    last = race["decision_index"] == race["decision_count"]
    must = {k: last and len(c["compounds_used"]) < 2 for k, c in race["drivers"].items()}
    wants = {k: _wants(name, race, k) or must[k] for k in race["drivers"]}
    if name in ("baseline", "coordinator") and wants["driver_a"] and wants["driver_b"] \
            and not (must["driver_a"] and must["driver_b"]):
        keep = [k for k in wants if must[k]] or [max(("driver_a", "driver_b"),
                                                     key=lambda k: race["drivers"][k]["tyre_age"])]
        wants = {k: k == keep[0] for k in wants}
    prefer_hard = name == "long_stint"
    action = {"type": "RACE_STRATEGY",
              "driver_a": "PIT_" + _compound(race, "driver_a", prefer_hard) if wants["driver_a"] else "STAY",
              "driver_b": "PIT_" + _compound(race, "driver_b", prefer_hard) if wants["driver_b"] else "STAY",
              "team_order": {"order": "RACE"}}
    orders = obs["team_orders"]
    legal = orders["legal_team_orders"]
    if name == "coordinator":
        action["team_order"] = _coordinator_order(race, orders, action)
    elif "RACE" not in legal:  # a commitment is due: non-coordinating scripts keep the order
        action["team_order"] = {"order": "KEEP_ORDER"}
    return action


def _coordinator_order(race, orders, action) -> Dict[str, Any]:
    """Swap when the trailing car has clearly fresher tyres and the exchange is executable and
    safe; promise a give-back if the promoted car has not passed the car ahead within 6 laps;
    give back when due if it is executable and safe, otherwise keep the order (reconsider)."""
    legal, feas, c = orders["legal_team_orders"], orders["exchange_feasibility_if_no_pit"], orders["commitment"]
    pitting = action["driver_a"] != "STAY" or action["driver_b"] != "STAY"
    if c is not None and c["status"] == "DUE":
        gb = c["give_back_feasibility"]
        if gb["executable_if_no_pit"] and gb["safe"] and not pitting:
            return {"order": "REQUEST_GIVE_BACK"}
        return {"order": "KEEP_ORDER"}
    if "SWAP" in legal and feas["executable"] and feas["safe"] and not pitting and feas["car_ahead"]:
        lead, trail = race["drivers"][feas["leader"]], race["drivers"][feas["trailer"]]
        if lead["tyre_age"] - trail["tyre_age"] >= 6 and race["laps_remaining"] > 9:
            deadline = race["lap"] + 6
            return {"order": "SWAP", "commitment": {"objective": "PASS_CAR_AHEAD", "deadline_lap": deadline,
                                                    "give_back_if": "OBJECTIVE_NOT_MET"}}
    return {"order": "KEEP_ORDER" if "RACE" not in legal else "RACE"}


def scripted(name: str) -> Callable[[Dict[str, Any]], Dict[str, Any]]:
    if name not in POLICIES:
        raise ValueError(f"unknown scripted policy {name}")

    def policy(obs: Dict[str, Any]) -> Dict[str, Any]:
        if obs["decision_type"] == "COMPONENT_DECISION":
            return component_action(obs)
        return race_action(name, obs)
    policy.__name__ = f"scripted_{name}"
    return policy
