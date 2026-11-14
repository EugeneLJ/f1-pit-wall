"""Integrated race step (benchmark 2.0.0): Track B race engine + Track C team orders.

`step(state, team_actions)` generalizes `engine.step` to any set of controlled team slots,
each submitting pit actions for its two cars plus one team order. With every controlled team
choosing RACE it executes exactly the 1.1.0 physics (tested bit-for-bit against engine.step).

Team orders act only through race time and the existing overtaking model:
  RACE             no instruction (1.1.0 behaviour)
  HOLD, KEEP_ORDER the car behind may not pass its teammate this segment
  SWAP             the car ahead lifts, the car behind passes (exchange; may be DELAYED/FAIL)
  REQUEST_GIVE_BACK  the promoted car yields back (same exchange mechanics)
  DEFENSIVE_BUFFER the car behind defends against the next car at a time cost
No order adds or removes points. Positions stay a strict order of elapsed times.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from .. import engine
from ..championship_adapter import CHAMPIONSHIP_TO_ENGINE_DRIVER

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "integrated_coefficients.json"
ORDERS = ("RACE", "HOLD", "SWAP", "DEFENSIVE_BUFFER")
FOLLOW_UPS = ("KEEP_ORDER", "REQUEST_GIVE_BACK")
ALL_ORDERS = ORDERS + FOLLOW_UPS
EXCHANGES = ("SWAP", "REQUEST_GIVE_BACK")
OPEN_COMMITMENT = ("ACTIVE", "DUE")


def load_team_order_model(path: Path = FIXTURE) -> Dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("data_status") != "synthetic_placeholder":
        raise ValueError("team-order coefficients must be marked synthetic")
    return data["team_orders"]


TEAM_ORDER_MODEL = load_team_order_model()


def team_cars(slot: str) -> Dict[str, str]:
    """Engine car names of a team slot: {'driver_a': ..., 'driver_b': ...}."""
    return {"driver_a": CHAMPIONSHIP_TO_ENGINE_DRIVER[f"{slot} A"],
            "driver_b": CHAMPIONSHIP_TO_ENGINE_DRIVER[f"{slot} B"]}


def attach(state: Dict[str, Any], controlled_slots: List[str]) -> Dict[str, Any]:
    """Mark a configured engine race state as integrated with these controlled team slots."""
    if "config" not in state or state["config"].get("tyres") is None:
        raise ValueError("integrated races require the configured Track B engine")
    slots = list(controlled_slots)
    if not slots or len(set(slots)) != len(slots):
        raise ValueError("controlled slots must be unique and non-empty")
    state["integrated"] = {
        "controlled": slots,
        "teams": {slot: {"commitment": None, "closed_commitments": [], "order_log": []} for slot in slots},
    }
    return state


def _order(state):
    return sorted(state["cars"], key=lambda c: (c["elapsed"], c["name"]))


def _by_name(state):
    return {c["name"]: c for c in state["cars"]}


def pair_geometry(state: Dict[str, Any], slot: str) -> Dict[str, Any]:
    """Public geometry of a team's two cars in the current running order."""
    cars = team_cars(slot)
    order = [c["name"] for c in _order(state)]
    elapsed = {c["name"]: c["elapsed"] for c in state["cars"]}
    ia, ib = order.index(cars["driver_a"]), order.index(cars["driver_b"])
    lead_key = "driver_a" if ia < ib else "driver_b"
    trail_key = "driver_b" if lead_key == "driver_a" else "driver_a"
    lead, trail = cars[lead_key], cars[trail_key]
    i_lead, i_trail = min(ia, ib), max(ia, ib)
    behind = order[i_trail + 1] if i_trail + 1 < len(order) else None
    ahead = order[i_lead - 1] if i_lead > 0 else None
    return {
        "leader": lead_key, "trailer": trail_key,
        "adjacent": i_trail - i_lead == 1,
        "gap_sec": round(elapsed[trail] - elapsed[lead], 6),
        "car_ahead": ahead,
        "car_behind": behind,
        "rear_gap_sec": None if behind is None else round(elapsed[behind] - elapsed[trail], 6),
    }


def exchange_feasibility(state: Dict[str, Any], slot: str, pits: Dict[str, bool],
                         model: Dict[str, Any] = TEAM_ORDER_MODEL) -> Dict[str, Any]:
    """Public feasibility of an exchange between the two teammates at the current decision."""
    geo = pair_geometry(state, slot)
    status = state["events"][state["step"]]
    ex = model["exchange"]
    reasons = []
    if status != "GREEN":
        reasons.append("NEUTRALIZED")
    if pits.get("driver_a") or pits.get("driver_b"):
        reasons.append("PIT_STOP")
    if not geo["adjacent"]:
        reasons.append("NOT_ADJACENT")
    if geo["gap_sec"] > ex["max_gap_sec"]:
        reasons.append("GAP_TOO_LARGE")
    safe = geo["rear_gap_sec"] is None or geo["rear_gap_sec"] >= ex["safe_rear_gap_sec"]
    return {"executable": not reasons, "blocking_reasons": reasons, "safe": safe, **geo}


def legal_team_orders(state: Dict[str, Any], slot: str) -> List[str]:
    commitment = state["integrated"]["teams"][slot]["commitment"]
    if commitment is not None and commitment["status"] == "DUE":
        return list(FOLLOW_UPS)
    if commitment is not None and commitment["status"] == "ACTIVE":
        return ["RACE", "HOLD", "DEFENSIVE_BUFFER"] + list(FOLLOW_UPS)
    return list(ORDERS)


def validate_team_action(state: Dict[str, Any], slot: str, action: Any) -> Dict[str, Any]:
    """Validate one controlled team's race action against the current public state."""
    if not isinstance(action, dict) or set(action) - {"driver_a", "driver_b", "team_order"} \
            or not {"driver_a", "driver_b", "team_order"} <= set(action):
        raise ValueError("race action must contain exactly driver_a, driver_b and team_order")
    pit = engine.validate_action({"driver_a": action["driver_a"], "driver_b": action["driver_b"]}, state)
    order = action["team_order"]
    if not isinstance(order, dict) or set(order) - {"order", "commitment"} or "order" not in order:
        raise ValueError("team_order must contain order and optional commitment")
    if order["order"] not in legal_team_orders(state, slot):
        raise ValueError(f"team order must be one of {'|'.join(legal_team_orders(state, slot))}")
    commitment = order.get("commitment")
    if commitment is not None:
        if order["order"] != "SWAP":
            raise ValueError("only SWAP can carry a commitment")
        if (not isinstance(commitment, dict)
                or set(commitment) != {"objective", "deadline_lap", "give_back_if"}
                or commitment["objective"] != "PASS_CAR_AHEAD"
                or commitment["give_back_if"] != "OBJECTIVE_NOT_MET"
                or isinstance(commitment["deadline_lap"], bool)
                or not isinstance(commitment["deadline_lap"], int)):
            raise ValueError("commitment must be {objective: PASS_CAR_AHEAD, deadline_lap: int, "
                             "give_back_if: OBJECTIVE_NOT_MET}")
        lap = engine._decision_laps(state)[state["step"]]
        if not lap < commitment["deadline_lap"] <= engine.laps_total(state):
            raise ValueError("deadline_lap must be after the current lap and within the race")
        if pair_geometry(state, slot)["car_ahead"] is None:
            raise ValueError("PASS_CAR_AHEAD needs a car ahead of the pair")
    return {**pit, "team_order": {"order": order["order"],
                                  "commitment": copy.deepcopy(commitment)}}


def update_commitments(state: Dict[str, Any]) -> None:
    """Advance commitment statuses at the start of a decision (before the observation)."""
    lap = engine._decision_laps(state)[state["step"]]
    for slot, team in state["integrated"]["teams"].items():
        c = team["commitment"]
        if c is None or c["status"] not in OPEN_COMMITMENT:
            continue
        cars = team_cars(slot)
        order = [x["name"] for x in _order(state)]
        promoted, other = cars[c["promoted"]], cars[c["yielded"]]
        if order.index(promoted) < order.index(c["target"]):
            _transition(c, state, "OBJECTIVE_ACHIEVED", "promoted car is ahead of the target")
        elif order.index(other) < order.index(promoted):
            _transition(c, state, "ORDER_RESTORED_BY_RACING", "the yielded car is ahead again")
        elif lap >= c["deadline_lap"] and c["status"] == "ACTIVE":
            _transition(c, state, "DUE", "deadline reached without the objective")
        geo = exchange_feasibility(state, slot, {})
        c["give_back_feasibility"] = {"executable_if_no_pit": geo["executable"],
                                      "blocking_reasons": geo["blocking_reasons"], "safe": geo["safe"],
                                      "rear_gap_sec": geo["rear_gap_sec"]}


def _transition(c, state, status, reason, **extra):
    lap = engine._decision_laps(state)[min(state["step"], len(state["events"]) - 1)]
    c["transitions"].append({"decision": state["step"] + 1, "lap": lap, "from": c["status"],
                             "to": status, "reason": reason, **extra})
    c["status"] = status


def _rival(state, status, index, decision_count, tyres, remaining):
    variant = state["config"].get("rival_policy")
    if variant not in (None, "public"):
        from .. import rival_policies
        return lambda car: rival_policies.decide(variant, car, state, status, index, decision_count, tyres, remaining)
    return lambda car: engine._rival_action(car, status, index, decision_count, tyres, remaining)


def step(state: Dict[str, Any], team_actions: Dict[str, Any],
         model: Dict[str, Any] = TEAM_ORDER_MODEL) -> Dict[str, Any]:
    """Advance one decision segment. `team_actions` maps every controlled slot to its action.
    Returns a per-team public outcome report of the team orders."""
    if state["complete"]:
        raise ValueError("race is already complete")
    controlled = state["integrated"]["controlled"]
    if set(team_actions) != set(controlled):
        raise ValueError("an action is required for every controlled team")
    clean = {slot: validate_team_action(state, slot, team_actions[slot]) for slot in controlled}
    status, index = state["events"][state["step"]], state["step"]
    config, tyres = state["config"], engine._tyres(state)
    decision_count = len(engine._decision_laps(state))
    remaining = engine.laps_total(state) - engine._decision_laps(state)[index]
    lap = engine._decision_laps(state)[index]
    controlled_cars = {}
    for slot in controlled:
        for key, name in team_cars(slot).items():
            controlled_cars[name] = clean[slot][key]
    rival = _rival(state, status, index, decision_count, tyres, remaining)
    pit_actions = {car["name"]: controlled_cars.get(car["name"]) or rival(car) for car in state["cars"]}

    # Team orders are resolved against the PRE-ACTION state (simultaneous for all teams).
    plans, reports = {}, {}
    for slot in controlled:
        order = clean[slot]["team_order"]
        pits = {k: engine.pit_compound(clean[slot][k]) is not None for k in ("driver_a", "driver_b")}
        plans[slot], reports[slot] = _plan_order(state, slot, order, pits, model, lap)

    pit = engine._pit(state)
    pitting = [car for car in _order(state) if engine.pit_compound(pit_actions[car["name"]]) is not None]
    if pit is not None:
        seen_teams = set()
        for car in pitting:
            if car["team"] in seen_teams:
                car["elapsed"] += pit["double_stack_queue_sec"]
            seen_teams.add(car["team"])
    state["integrated"].setdefault("pit_log", []).append({
        "decision": index + 1, "stops": [{"car": car["name"], "compound": engine.pit_compound(pit_actions[car["name"]])}
                                         for car in pitting]})
    for car in pitting:
        compound = engine.pit_compound(pit_actions[car["name"]])
        car["elapsed"] += engine.pit_loss(state, status)
        car["compound"], car["tyre_age"] = compound, 0
        car["compounds_used"].append(compound)
        if pit is not None:
            car["out_lap"] = True
    neutral = config.get("neutralization")
    if neutral is not None and status != "GREEN":
        engine._neutralized_segment(state, status, neutral)
    else:
        _green_segment(state, plans, model)
    _finish_orders(state, plans, reports)
    state["actions"].append({slot: copy.deepcopy(clean[slot]) for slot in controlled})
    state["step"] += 1
    state["complete"] = state["step"] == decision_count
    if not state["complete"]:
        update_commitments(state)
    else:
        for slot, team in state["integrated"]["teams"].items():
            c = team["commitment"]
            if c is not None and c["status"] in OPEN_COMMITMENT:
                _transition(c, state, "EXPIRED_AT_FINISH", "race ended with the commitment open")
    for slot in controlled:
        state["integrated"]["teams"][slot]["order_log"].append(reports[slot])
    return reports


def _plan_order(state, slot, order, pits, model, lap):
    """Translate a team order into segment modifiers; resolve commitment bookkeeping."""
    name, commitment_req = order["order"], order["commitment"]
    team = state["integrated"]["teams"][slot]
    cars = team_cars(slot)
    feas = exchange_feasibility(state, slot, pits, model)
    plan = {"kind": "RACE", "cars": cars, "feasibility": feas}
    report = {"decision": state["step"] + 1, "lap": lap, "order": name, "status": "APPLIED",
              "feasibility": {k: feas[k] for k in ("executable", "blocking_reasons", "safe", "gap_sec",
                                                   "rear_gap_sec", "adjacent")}}
    c = team["commitment"]
    if name in ("HOLD", "KEEP_ORDER"):
        plan["kind"] = "HOLD"
    elif name == "DEFENSIVE_BUFFER":
        plan["kind"] = "DEFEND"
    elif name in EXCHANGES:
        if name == "REQUEST_GIVE_BACK":
            geo = pair_geometry(state, slot)
            if c is None or geo["leader"] != c["promoted"]:
                report["status"] = "NOT_NEEDED"
                if c is not None and c["status"] in OPEN_COMMITMENT:
                    _transition(c, state, "ORDER_RESTORED_BY_RACING", "the yielded car is already ahead")
                return {"kind": "RACE", "cars": cars, "feasibility": feas}, report
        if feas["executable"]:
            plan = {"kind": "EXCHANGE", "cars": cars, "feasibility": feas, "order": name,
                    "commitment": commitment_req}
            report["status"] = "ATTEMPTED"
        else:
            report["status"] = "DELAYED" if set(feas["blocking_reasons"]) <= {"NEUTRALIZED", "PIT_STOP"} \
                else "INFEASIBLE"
    if c is not None and c["status"] == "DUE" and name == "KEEP_ORDER":
        gb = c.get("give_back_feasibility", {})
        if gb.get("executable_if_no_pit") and gb.get("safe"):
            _transition(c, state, "BROKEN_WHILE_FEASIBLE", "kept order although a safe give-back was possible")
        else:
            reason = ",".join(gb.get("blocking_reasons") or []) or "UNSAFE_REAR_GAP"
            _transition(c, state, "RECONSIDERED", f"give-back not executable or unsafe: {reason}")
    if c is not None and name == "REQUEST_GIVE_BACK":
        c["give_back_attempts"] += 1
    return plan, report


def _green_segment(state, plans, model):
    """engine.step GREEN physics with team-order modifiers (identical when all plans are RACE)."""
    config, tyres = state["config"], engine._tyres(state)
    pit = engine._pit(state)
    order = _order(state)
    positions = {car["name"]: i + 1 for i, car in enumerate(order)}
    deg, overtaking = config["deg_multiplier"], config["overtaking"]
    traffic = {car["name"]: None for car in state["cars"]}
    if overtaking is not None:
        for i, car in enumerate(order):
            close = i > 0 and car["elapsed"] - order[i - 1]["elapsed"] < overtaking["dirty_air_gap_sec"]
            traffic[car["name"]] = overtaking["dirty_air_loss_sec_per_lap"] if close else 0.0
    warmup = pit["out_lap_warmup_sec"] if pit is not None else {}
    seg = engine.segment_laps(state)
    finish = {car["name"]: car["elapsed"] + engine._segment_time(car, positions[car["name"]], deg,
                                                                traffic[car["name"]], tyres, seg)
              + (warmup.get(car["compound"], 0.0) if car.pop("out_lap", False) else 0.0)
              for car in state["cars"]}
    overrides, guarded, bonus = {}, set(), {}
    for slot, plan in plans.items():
        feas = plan["feasibility"]
        lead, trail = plan["cars"][feas["leader"]], plan["cars"][feas["trailer"]]
        if plan["kind"] == "HOLD":
            overrides[(lead, trail)] = float("inf")
            guarded.add(lead)
        elif plan["kind"] == "DEFEND":
            overrides[(lead, trail)] = float("inf")
            guarded.add(lead)
            finish[trail] += model["defensive_buffer"]["loss_sec_per_segment"]
            bonus[trail] = model["defensive_buffer"]["pass_bonus_sec"]
        elif plan["kind"] == "EXCHANGE":
            ex = model["exchange"]
            finish[trail] += ex["pass_loss_sec"]
            needed = finish[trail] + overtaking["min_gap_sec"] - finish[lead] + ex["clearance_sec"]
            lift = max(0.0, needed)
            plan["lift_sec"] = round(min(lift, ex["max_lift_sec"]), 6)
            plan["aborted"] = lift > ex["max_lift_sec"]
            finish[lead] += plan["lift_sec"]
            overrides[(lead, trail)] = 0.0
            guarded.add(lead)
            plan["start"] = {"leader": lead, "trailer": trail, "car_ahead": feas["car_ahead"]}
    if overtaking is not None:
        _resolve(order, finish, overtaking, config["overtaking_difficulty"], overrides, guarded, bonus)
    for car in state["cars"]:
        car["elapsed"] = finish[car["name"]]
        car["tyre_age"] += seg


def _resolve(order, finish, model, difficulty, overrides, guarded, bonus):
    """engine._apply_overtaking plus: (a) per-pair requirements for team orders, (b) a slowed
    (guarded) car can only be passed by a car meeting the pass margin, even if not its neighbour,
    (c) a defending car needs bonus extra margin. With no modifiers this is engine._apply_overtaking."""
    base = model["pass_base_sec"] + difficulty * model["pass_scale_sec"]
    names = [c["name"] for c in order]
    for i in range(1, len(names)):
        car = names[i]
        checks = [j for j in range(i - 1, -1, -1) if j == i - 1 or names[j] in guarded]
        changed = True
        while changed:  # re-check after every hold so two held cars never share a time
            changed = False
            for j in checks:
                ahead = names[j]
                required = overrides.get((ahead, car), base + bonus.get(ahead, 0.0))
                if finish[car] < finish[ahead] + model["min_gap_sec"] and finish[ahead] - finish[car] < required:
                    finish[car] = finish[ahead] + model["min_gap_sec"]
                    changed = True
    if guarded:  # two cars held behind the same slowed car: the later one (start order) drops back
        rank = {name: i for i, name in enumerate(names)}
        while True:
            seen, tie = {}, None
            for name in sorted(finish, key=lambda n: rank[n]):
                key = round(finish[name], 9)
                if key in seen:
                    tie = name
                    break
                seen[key] = name
            if tie is None:
                break
            finish[tie] += model["min_gap_sec"]


def _finish_orders(state, plans, reports):
    order = [c["name"] for c in _order(state)]
    for slot, plan in plans.items():
        if plan["kind"] != "EXCHANGE":
            continue
        team = state["integrated"]["teams"][slot]
        start = plan["start"]
        success = order.index(start["trailer"]) < order.index(start["leader"]) and not plan["aborted"]
        if plan["aborted"] and order.index(start["trailer"]) < order.index(start["leader"]):
            success = True  # passed anyway within the maximum lift
        reports[slot]["status"] = "COMPLETED" if success else "FAILED"
        reports[slot]["lift_sec"] = plan["lift_sec"]
        reports[slot]["aborted"] = plan["aborted"] and not success
        reports[slot]["result_order"] = {"promoted": next(k for k, v in plan["cars"].items() if v == start["trailer"])}
        c = team["commitment"]
        if plan["order"] == "SWAP":
            if plan["commitment"] is not None:
                promoted_key = next(k for k, v in plan["cars"].items() if v == start["trailer"])
                yielded_key = next(k for k, v in plan["cars"].items() if v == start["leader"])
                new = {"objective": "PASS_CAR_AHEAD", "target": start["car_ahead"],
                       "deadline_lap": plan["commitment"]["deadline_lap"], "give_back_if": "OBJECTIVE_NOT_MET",
                       "promoted": promoted_key, "yielded": yielded_key, "status": "PROPOSED",
                       "created_decision": state["step"] + 1, "give_back_attempts": 0, "transitions": []}
                if team["commitment"] is not None:
                    team["closed_commitments"].append(team["commitment"])
                team["commitment"] = new
                _transition(new, state, "ACTIVE" if success else "VOID_SWAP_FAILED",
                            "swap completed" if success else "swap did not complete")
        elif c is not None and c["status"] in OPEN_COMMITMENT:
            if success:
                _transition(c, state, "FULFILLED", "give-back completed")
            else:
                c["transitions"].append({"decision": state["step"] + 1, "event": "GIVE_BACK_FAILED"})


def public_order_view(state: Dict[str, Any], slot: str) -> Dict[str, Any]:
    """Team-private team-order state for that team's observation."""
    team = state["integrated"]["teams"][slot]
    pits = {}
    feas = exchange_feasibility(state, slot, pits)
    return {"legal_team_orders": legal_team_orders(state, slot),
            "exchange_feasibility_if_no_pit": {k: feas[k] for k in (
                "executable", "blocking_reasons", "safe", "leader", "trailer", "adjacent", "gap_sec",
                "car_ahead", "car_behind", "rear_gap_sec")},
            "commitment": copy.deepcopy(team["commitment"]),
            "last_order_outcome": copy.deepcopy(team["order_log"][-1]) if team["order_log"] else None}
