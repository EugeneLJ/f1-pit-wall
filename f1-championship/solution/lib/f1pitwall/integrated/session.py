"""Authoritative integrated championship session (benchmark 2.0.0).

One session owns the world state. Each controlled team sees only a team-local observation
built from one immutable pre-action snapshot per tick, submits one sealed action per tick,
and the tick resolves only when every team has submitted or the tick is closed on timeout
(missing teams get the published fallback). No team can read another team's same-tick
action, team orders, commitments or Engineer reports. Every resolved tick is appended to a
hash-chained journal (journal_version 2) that a trusted verifier replays from the seed.
"""

from __future__ import annotations

import copy
import time
from typing import Any, Callable, Dict, List, Optional

from .. import coefficients as coef
from .. import engine
from ..championship import TEAM_DRIVERS, new_championship_state
from ..championship_adapter import (ENGINE_TO_CHAMPIONSHIP_DRIVER, car_performance, finish_prepared_race,
                                    start_prepared_race)
from ..championship_transition import (available_component_actions, default_component_decisions, driver_team,
                                       free_units, initial_inventory, prepare_race, replacement_cost)
from ..journal import GENESIS_HASH, canonical, observation_hash, seal_entry, sha256_text
from . import race as ir
from .config import INTEGRATED_VERSION, SLOTS, IntegratedConfig

CONTRACT_VERSION = 2
JOURNAL_VERSION = 2
COMPONENT_DECISION = "COMPONENT_DECISION"
RACE_STRATEGY = "RACE_STRATEGY"
CHAMPIONSHIP_COMPLETE = "CHAMPIONSHIP_COMPLETE"
SUBMITTED, TIMEOUT, INVALID = "SUBMITTED", "TIMEOUT", "INVALID_FALLBACK"
PUBLIC_RESOLUTION_RULE = ("Actions of all teams are applied simultaneously to the same pre-action state. "
                          "Pit-lane order, shared-crew queues and on-track interactions are resolved by "
                          "the race engine in road order (elapsed time, then car name). Team orders act "
                          "only on their own two cars. A missing or invalid action is replaced by the "
                          "published fallback and recorded as such.")


class TickError(ValueError):
    """Submission rejected (wrong tick, wrong team, already sealed, or invalid action)."""


class IntegratedSession:
    def __init__(self, config: IntegratedConfig, base_seed: int, coeffs: Optional[dict] = None,
                 engineer_broker: Any = None, clock: Callable[[], float] = time.time) -> None:
        config.validate()
        if isinstance(base_seed, bool) or not isinstance(base_seed, int):
            raise ValueError("base_seed must be an integer")
        self.config = config
        self.coeffs = copy.deepcopy(coeffs if coeffs is not None else coef.DEFAULT)
        if config.rival_policy_variant:
            self.coeffs = coef.with_rival_policy(self.coeffs, config.rival_policy_variant)
        if config.benchmark_version == "2.1.0":  # opt-in FIA-based PU rules (B8)
            from .. import pu_rules
            self.coeffs = pu_rules.with_fia_pu_rules(self.coeffs)
        self._base_seed = base_seed
        self._broker = engineer_broker
        self._clock = clock
        self.teams = {t.label: t for t in config.teams}
        self.slot_of = {t.label: t.slot for t in config.teams}
        self.label_of_slot = {s: s for s in SLOTS}
        self.short_of_slot = {s: s for s in SLOTS}
        for t in config.teams:
            self.label_of_slot[t.slot], self.short_of_slot[t.slot] = t.label, t.short
        self.state = new_championship_state(resource_inventory=initial_inventory(self.coeffs))
        self.decision_type = COMPONENT_DECISION
        self.race_state: Optional[Dict[str, Any]] = None
        self._active = None
        self.journal: List[Dict[str, Any]] = []
        self.race_results: List[Dict[str, Any]] = []
        self._tick = 0
        self._open_tick()

    # ------------------------------------------------------------------ naming
    def public_driver(self, championship_driver: str) -> str:
        slot, letter = championship_driver.rsplit(" ", 1)
        return f"{self.short_of_slot[slot]} {letter}"

    def _engine_public(self, engine_name: str) -> str:
        return self.public_driver(ENGINE_TO_CHAMPIONSHIP_DRIVER[engine_name])

    # ------------------------------------------------------------------ ticks
    @property
    def tick_id(self) -> str:
        return f"t{self._tick:03d}"

    def _open_tick(self) -> None:
        self._tick += 1
        self._sealed: Dict[str, Dict[str, Any]] = {}
        self._snapshots = {label: self._build_observation(label) for label in self.teams}
        self._engineer_records: Dict[str, List[Dict[str, Any]]] = {}
        if self.decision_type == RACE_STRATEGY and self._broker is not None:
            for label, team in self.teams.items():
                if team.engineers != "CHIEF_ONLY":
                    records = self._broker.collect(label, team.engineers, self._snapshots[label], self.tick_id)
                    self._engineer_records[label] = records
                    self._snapshots[label]["engineer_reports"] = [
                        {"record_hash": r.get("record_hash"), "engineer_id": r["engineer_id"],
                         "status": r["status"], "source": r["source"],
                         "recommendation": copy.deepcopy(r.get("recommendation"))} for r in records]
        self._obs_hash = {label: observation_hash(obs) for label, obs in self._snapshots.items()}

    def observation(self, label: str) -> Dict[str, Any]:
        if label not in self.teams:
            raise TickError("unknown team")
        return copy.deepcopy(self._snapshots[label])

    def submission_status(self, label: str) -> Dict[str, Any]:
        """Only the caller's own status: whether the other team has submitted is not revealed."""
        own = self._sealed.get(label)
        return {"tick_id": self.tick_id, "sealed": own is not None,
                "action_sha256": own["action_sha256"] if own else None}

    def submit(self, label: str, tick_id: str, action: Any, submitted_via: str = "api") -> Dict[str, Any]:
        if self.decision_type == CHAMPIONSHIP_COMPLETE:
            raise TickError("championship is complete")
        if label not in self.teams:
            raise TickError("unknown team")
        error = (f"stale or unknown tick (current {self.tick_id})" if tick_id != self.tick_id
                 else "action already sealed for this tick" if label in self._sealed else None)
        if error:
            self._append({"kind": "rejected", "tick_id": str(tick_id), "team": label,
                          "action_sha256": sha256_text(canonical(_json_safe(action))), "error": error})
            raise TickError(error)
        try:
            clean = self._validate(label, action)
        except ValueError as exc:
            self._append({"kind": "rejected", "tick_id": tick_id, "team": label,
                          "action_sha256": sha256_text(canonical(_json_safe(action))), "error": str(exc)})
            raise TickError(str(exc)) from exc
        self._sealed[label] = {"status": SUBMITTED, "action": clean, "submitted_via": submitted_via,
                               "action_sha256": sha256_text(canonical(clean)), "t_received": self._clock()}
        receipt = {"tick_id": tick_id, "action_sha256": self._sealed[label]["action_sha256"]}
        if set(self._sealed) == set(self.teams):
            self._resolve()
        return receipt

    def close_tick(self, tick_id: str, reason: str = TIMEOUT) -> None:
        """Resolve the tick with the published fallback for every team that has not submitted."""
        if tick_id != self.tick_id or self.decision_type == CHAMPIONSHIP_COMPLETE:
            raise TickError("no such open tick")
        for label in self.teams:
            if label not in self._sealed:
                fallback = self.fallback_action(label)
                self._sealed[label] = {"status": reason, "action": fallback, "submitted_via": "fallback",
                                       "action_sha256": sha256_text(canonical(fallback)), "t_received": self._clock()}
        self._resolve()

    def fallback_action(self, label: str) -> Dict[str, Any]:
        slot = self.slot_of[label]
        if self.decision_type == COMPONENT_DECISION:
            decisions = []
            for driver in TEAM_DRIVERS[slot]:
                legal = available_component_actions(self.state, driver, self.coeffs)
                for name in self.state.power_units[driver]:
                    decisions.append({"driver": self.public_driver(driver), "component": name,
                                      "action": "USE" if "USE" in legal[name] else "REPLACE"})
            return {"type": COMPONENT_DECISION, "decisions": decisions}
        order = "KEEP_ORDER" if "RACE" not in ir.legal_team_orders(self.race_state, slot) else "RACE"
        return {"type": RACE_STRATEGY, "driver_a": "STAY", "driver_b": "STAY",
                "team_order": {"order": order}}

    # ------------------------------------------------------------------ validation
    def _validate(self, label: str, action: Any) -> Dict[str, Any]:
        slot = self.slot_of[label]
        if not isinstance(action, dict) or action.get("type") != self.decision_type:
            raise ValueError(f"action type must be {self.decision_type}")
        if self.decision_type == COMPONENT_DECISION:
            if set(action) - {"type", "decisions", "consumed_reports"}:
                raise ValueError("component action must contain type and decisions")
            names = {self.public_driver(d): d for d in TEAM_DRIVERS[slot]}
            decisions = action.get("decisions")
            if not isinstance(decisions, list):
                raise ValueError("decisions must be a list")
            expected = {(p, c) for p, d in names.items() for c in self.state.power_units[d]}
            seen, clean = set(), []
            for item in decisions:
                if not isinstance(item, dict) or set(item) != {"driver", "component", "action"}:
                    raise ValueError("each decision needs driver, component and action")
                key = (item["driver"], item["component"])
                if key not in expected or key in seen:
                    raise ValueError("decision is for a driver/component this team does not own, or duplicated")
                internal = names[item["driver"]]
                if item["action"] not in available_component_actions(self.state, internal, self.coeffs)[item["component"]]:
                    raise ValueError("component action is not legal")
                seen.add(key)
                clean.append(dict(item))
            if seen != expected:
                raise ValueError("every own driver/component pair needs exactly one decision")
            from .. import pu_rules
            if pu_rules.enabled(self.coeffs):
                counts = {}
                for item in clean:
                    if item["action"] == "REPLACE":
                        counts[item["component"]] = counts.get(item["component"], 0) + 1
                pu_rules.check_team_stock(self.state, slot, counts)
            return {"type": COMPONENT_DECISION, "decisions": clean,
                    "consumed_reports": _reports(action)}
        if set(action) - {"type", "driver_a", "driver_b", "team_order", "consumed_reports"}:
            raise ValueError("race action has unknown fields")
        team_order = action.get("team_order")
        if team_order is None:
            raise ValueError("team_order is required in integrated modes ({'order': 'RACE'} for none)")
        clean = ir.validate_team_action(self.race_state, slot, {"driver_a": action.get("driver_a"),
                                                                 "driver_b": action.get("driver_b"),
                                                                 "team_order": team_order})
        reports = _reports(action)
        known = {r.get("record_hash") for r in self._engineer_records.get(label, [])}
        if set(reports) - known:
            raise ValueError("consumed_reports must reference this tick's Engineer record hashes")
        return {"type": RACE_STRATEGY, **clean, "consumed_reports": reports}

    # ------------------------------------------------------------------ resolution
    def _resolve(self) -> None:
        phase, tick = self.decision_type, self.tick_id
        before_hash = dict(self._obs_hash)
        sealed = copy.deepcopy(self._sealed)
        engineer_hashes = {label: [r.get("record_hash") for r in recs] for label, recs in self._engineer_records.items()}
        result = None
        if phase == COMPONENT_DECISION:
            self._apply_components({label: s["action"] for label, s in sealed.items()})
        else:
            actions = {self.slot_of[label]: {k: s["action"][k] for k in ("driver_a", "driver_b", "team_order")}
                       for label, s in sealed.items()}
            reports = ir.step(self.race_state, actions)
            if self.race_state["complete"]:
                result = self._finish_race()
            self._last_order_reports = reports
        t_done = self._clock()
        self._open_tick()
        entry = {"kind": "resolved", "tick_id": tick, "decision_type": phase,
                 "submissions": {label: {k: s[k] for k in ("status", "action", "action_sha256", "submitted_via",
                                                           "t_received")} for label, s in sealed.items()},
                 "engineer_record_hashes": engineer_hashes, "obs_before_sha256": before_hash,
                 "obs_after_sha256": dict(self._obs_hash), "t_done": t_done}
        if result is not None:
            entry["race_result"] = {"race_index": result["race_index"], "team_points": result["team_points"]}
        self._append(entry)

    def _append(self, entry: Dict[str, Any]) -> None:
        body = {"journal_version": JOURNAL_VERSION, "seq": len(self.journal) + 1, **_json_safe(entry)}
        prev = self.journal[-1]["entry_hash"] if self.journal else GENESIS_HASH
        self.journal.append(seal_entry(body, prev))

    def _apply_components(self, by_label: Dict[str, Dict[str, Any]]) -> None:
        working = copy.deepcopy(self.state)
        decisions = default_component_decisions(working)
        chosen = {}
        controlled_slots = set(self.slot_of.values())
        for label, action in by_label.items():
            slot = self.slot_of[label]
            names = {self.public_driver(d): d for d in TEAM_DRIVERS[slot]}
            for item in action["decisions"]:
                chosen[(names[item["driver"]], item["component"])] = item["action"]
        threshold = self.coeffs["rival_component_policy"]["threshold"]
        limit = coef.max_wear_for_use(self.coeffs)
        for item in decisions:
            key = (item["driver"], item["component"])
            if driver_team(item["driver"]) in controlled_slots:
                item["action"] = chosen[key]
            else:  # published threshold rule for every uncontrolled team (incl. Apex if uncontrolled)
                wear = working.power_units[item["driver"]][item["component"]].wear
                want = "REPLACE" if wear >= threshold or wear > limit else "USE"
                legal = available_component_actions(working, item["driver"], self.coeffs)[item["component"]]
                if want == "REPLACE" and "REPLACE" in legal:
                    from .. import pu_rules
                    if pu_rules.enabled(self.coeffs):  # stock is shared by the team's two drivers
                        team = driver_team(item["driver"])
                        key = pu_rules.stock_key(item["component"])
                        used = sum(1 for d in decisions if d is not item and d.get("action") == "REPLACE"
                                   and d["component"] == item["component"] and driver_team(d["driver"]) == team
                                   and decisions.index(d) < decisions.index(item))
                        if working.resource_inventory[team].get(key, 0) - used <= 0:
                            want = "USE"
                item["action"] = want if want in legal else legal[0]
        prepare_race(working, decisions, self.coeffs)
        self._active = start_prepared_race(working, self._base_seed + working.race_index, self.coeffs)
        self.state = working
        self.race_state = ir.attach(self._active.race_state, [t.slot for t in self.config.teams])
        ir.update_commitments(self.race_state)
        self.decision_type = RACE_STRATEGY

    def _finish_race(self) -> Dict[str, Any]:
        integrated_part = copy.deepcopy(self.race_state["integrated"])
        result = finish_prepared_race(self.state, self._active, self.coeffs)
        record = {"race_index": result.race_index, "race_name": result.race_name,
                  "classification": [{**e, "driver": self.public_driver(e["driver"]),
                                      "team": self.label_of_slot[driver_team(e["driver"])]}
                                     for e in result.race_result["classification"]],
                  "driver_points": {self.public_driver(d): p for d, p in result.awarded_points.items()},
                  "team_points": {self.label_of_slot[s]: sum(result.awarded_points[d] for d in TEAM_DRIVERS[s])
                                  for s in SLOTS},
                  "events": list(self.race_state["events"]),
                  "team_orders": {self.label_of_slot[s]: self._map_names(v) for s, v in integrated_part["teams"].items()}}
        self.race_results.append(record)
        self._active, self.race_state = None, None
        self.decision_type = (CHAMPIONSHIP_COMPLETE if self.state.race_index == len(self.state.calendar)
                              else COMPONENT_DECISION)
        return record

    # ------------------------------------------------------------------ observations
    def _build_observation(self, label: str) -> Dict[str, Any]:
        state, slot = self.state, self.slot_of[label]
        teams = sorted(((self.label_of_slot[s], p) for s, p in state.team_points.items()), key=lambda x: (-x[1], x[0]))
        drivers = sorted(((self.public_driver(d), p) for d, p in state.driver_points.items()), key=lambda x: (-x[1], x[0]))
        from ..championship_contract import _track_public
        obs: Dict[str, Any] = {
            "contract_version": CONTRACT_VERSION, "benchmark_version": self.config.benchmark_version,
            "mode": self.config.mode, "team": label, "tick_id": self.tick_id, "decision_type": self.decision_type,
            "championship": {"race_index": state.race_index, "races_total": len(state.calendar),
                             "team_standings": [{"team": t, "points": p} for t, p in teams],
                             "driver_standings": [{"driver": d, "points": p} for d, p in drivers],
                             "completed_calendar": [_track_public(r, self.coeffs) for r in state.calendar[:state.race_index]],
                             "remaining_calendar": [_track_public(r, self.coeffs) for r in state.calendar[state.race_index:]]},
            "public_resolution_rule": PUBLIC_RESOLUTION_RULE,
        }
        if self.decision_type == CHAMPIONSHIP_COMPLETE:
            obs["race_progress"] = {"status": "CHAMPIONSHIP_COMPLETE"}
            obs["action_schema"] = None
            return obs
        track = state.calendar[state.race_index]
        obs["current_track"] = {"name": track.name, "archetype": track.archetype,
                                "power_unit_stress": track.power_unit_stress,
                                "overtaking_difficulty": track.overtaking_difficulty,
                                "tyre_degradation": track.tyre_degradation, "data_status": "synthetic_placeholder"}
        obs["controlled_drivers"] = {
            self.public_driver(d): {
                "components": {n: {"wear": round(c.wear, 6), "replacements": c.replacements,
                                   "legal_actions": available_component_actions(state, d, self.coeffs)[n],
                                   "replace_cost_if_only_replacement": replacement_cost(state, d, n, self.coeffs)}
                               for n, c in state.power_units[d].items()},
                "free_units_available": free_units(state, d, self.coeffs),
                "projection_if_all_used": {k: round(v, 6) for k, v in car_performance(state, d, self.coeffs).items()},
            } for d in TEAM_DRIVERS[slot]}
        obs["resource_inventory"] = copy.deepcopy(state.resource_inventory[slot])
        obs["rivals_public"] = {
            self.public_driver(d): {"team": self.label_of_slot[driver_team(d)],
                                    "components_replaced": sum(c.replacements for c in state.power_units[d].values()),
                                    "team_free_units": free_units(state, d, self.coeffs),
                                    "grid_drop_this_race": state.grid_penalties[d] if state.race_prepared else None,
                                    "published_pace_estimate": round(car_performance(state, d, self.coeffs)["pace"], 6)}
            for d in state.power_units if driver_team(d) != slot}
        if self.decision_type == COMPONENT_DECISION:
            obs["race_progress"] = {"status": "PRE_RACE", "completed_decisions": 0}
            first = TEAM_DRIVERS[slot][0]
            obs["action_schema"] = {
                "type": COMPONENT_DECISION,
                "decisions": ("a LIST with exactly one {driver, component, action} object per own driver/component "
                              "pair; action is USE or REPLACE (see controlled_drivers.*.components.*.legal_actions)"),
                "consumed_reports": "optional top-level list of Engineer record hashes used",
                "format_example": {"type": COMPONENT_DECISION, "decisions": [
                    {"driver": self.public_driver(first), "component": "ICE", "action": "USE"},
                    "...one object per own driver/component pair..."]}}
            return obs
        obs["race_progress"] = self._race_view(slot)
        obs["starting_grid"] = [self.public_driver(d) for d in self._active.starting_grid]
        obs["team_orders"] = self._map_names(ir.public_order_view(self.race_state, slot))
        legal = "|".join(engine.legal_actions(self.race_state))
        obs["action_schema"] = {"type": RACE_STRATEGY, "driver_a": legal, "driver_b": legal,
                                "team_order": {"order": "|".join(obs["team_orders"]["legal_team_orders"]),
                                               "commitment": "optional with SWAP: {objective: PASS_CAR_AHEAD, "
                                                             "deadline_lap: int, give_back_if: OBJECTIVE_NOT_MET}"},
                                "consumed_reports": "optional top-level list of Engineer record hashes used",
                                "format_example": {"type": RACE_STRATEGY, "driver_a": "PIT_HARD", "driver_b": "STAY",
                                                   "team_order": {"order": "RACE"}}}
        return obs

    def _race_view(self, slot: str) -> Dict[str, Any]:
        return team_race_view(self.race_state, slot, self._engine_public, self.label_of_slot,
                              self.state.calendar[self.state.race_index].name)

    def _map_names(self, view: Dict[str, Any]) -> Dict[str, Any]:
        """Replace internal engine car names in a team-order view by public driver names."""
        engine_names = set(ENGINE_TO_CHAMPIONSHIP_DRIVER)

        def walk(value):
            if isinstance(value, dict):
                return {k: walk(v) for k, v in value.items()}
            if isinstance(value, list):
                return [walk(v) for v in value]
            if isinstance(value, str) and value in engine_names:
                return self._engine_public(value)
            return value
        return walk(view)

    # ------------------------------------------------------------------ results
    def standings(self) -> Dict[str, Any]:
        return {"team_points": {self.label_of_slot[s]: p for s, p in self.state.team_points.items()},
                "driver_points": {self.public_driver(d): p for d, p in self.state.driver_points.items()}}


def team_race_view(rs: Dict[str, Any], slot: str, public_name: Callable[[str], str],
                   label_of_slot: Dict[str, str], race_name: str) -> Dict[str, Any]:
    """Team-local race view: own cars in full, every car's public running state, published models.
    Usable on any integrated race state (rollouts use the same view as the live session)."""
    base = engine.observation(rs)
    cars = ir.team_cars(slot)
    by_name = {c["name"]: c for c in rs["cars"]}
    positions = {e["driver"]: e["position"] for e in base["classification"]}
    drivers = {}
    for key, name in cars.items():
        car = by_name[name]
        drivers[key] = {"name": public_name(name), "position": positions[name],
                        "compound": car["compound"], "tyre_age": car["tyre_age"],
                        "elapsed": round(car["elapsed"], 3), "compounds_used": sorted(set(car["compounds_used"]))}
    a, b = by_name[cars["driver_a"]], by_name[cars["driver_b"]]
    first = "driver_a" if (a["elapsed"], a["name"]) <= (b["elapsed"], b["name"]) else "driver_b"
    view = {k: copy.deepcopy(base[k]) for k in ("lap", "laps_total", "decision_index", "decision_count",
                                                "track_status", "legal_actions", "submitted_actions",
                                                "event_model", "neutralization", "segment_laps", "tyre_life_laps",
                                                "laps_remaining")
            if k in base}
    view["race"] = race_name
    view["drivers"] = drivers
    view["classification"] = [{**e, "driver": public_name(e["driver"]), "team": label_of_slot[e["team"]]}
                              for e in base["classification"]]
    if "pit" in base:
        view["pit"] = {**copy.deepcopy(base["pit"]), "if_both_pit_serviced_first": first}
    view["public_pit_history"] = [{"decision": p["decision"], "stops": [
        {"driver": public_name(s["car"]), "compound": s["compound"]} for s in p["stops"]]}
        for p in rs["integrated"].get("pit_log", [])]
    return view


def _reports(action: Dict[str, Any]) -> List[str]:
    value = action.get("consumed_reports", [])
    if not isinstance(value, list) or not all(isinstance(x, str) for x in value):
        raise ValueError("consumed_reports must be a list of record hashes")
    return list(value)


def _json_safe(value: Any) -> Any:
    try:
        return __import__("json").loads(canonical(value))
    except (TypeError, ValueError):
        return repr(value)
