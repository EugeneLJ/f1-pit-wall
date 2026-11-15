#!/usr/bin/env python3
"""Public-information reference for the integrated SOLO_COORDINATION task (2.1.0, also 2.0.1).

Port of solution/reference.py (1.1.0), unchanged in principle:
  * Interface: f1ctl rules / observe / act only. No seed, journal, sidecar file or rival internals.
  * Model: lib/f1pitwall (the published rules as code) driven as an IntegratedSession with a dummy
    seed (0). At every decision the model is checked against the observation (components, rivals'
    public usage, inventory, tyres, elapsed times); the observed track status is copied in; the
    hidden parts of the model (its own future SC/VSC draws and retirement draws) are never read.
  * Race: one-step lookahead over the 16 joint pit actions with team order RACE, each played now and
    with the public baseline heuristic afterwards, over futures sampled from the published SC/VSC
    model conditioned on the observed statuses (the 1.1.0 functions, reused unchanged: with RACE the
    integrated step equals the 1.1.0 step bit for bit).
  * Components (2.1.0): search over season replacement plans valued with the same public model under
    the 2.1.0 rules (per-driver allocation, team stock, cumulative penalties, back of grid), with the
    rivals' published stock-aware rule. Starting plans include per-driver bundles at every race;
    moves include toggling one element, moving it, giving it to the team-mate and moving a driver's
    whole bundle one race earlier/later (penalty bundling and timing).
On any inconsistency or exception it falls back to the published baseline policy for the rest of the
season, so the season always completes.
"""

from __future__ import annotations

import copy
import json
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
for candidate in (HERE / "lib", HERE.parent.parent / "src"):
    if (candidate / "f1pitwall").is_dir():
        sys.path.insert(0, str(candidate))
        break
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent.parent / "solution"))

import reference as R1  # noqa: E402  (the 1.1.0 reference: race-level functions reused unchanged)
from f1pitwall import coefficients as coef  # noqa: E402
from f1pitwall import pu_rules  # noqa: E402
from f1pitwall.championship_adapter import ENGINE_TO_CHAMPIONSHIP_DRIVER, start_prepared_race  # noqa: E402
from f1pitwall.championship_transition import (advance_without_result, available_component_actions,  # noqa: E402
                                               prepare_race, published_rule_decisions)
from f1pitwall.integrated import config as C  # noqa: E402
from f1pitwall.integrated.session import IntegratedSession  # noqa: E402

APEX = ("Apex A", "Apex B")
COMPONENTS = coef.COMPONENTS
TEAM = "Apex"


def coeffs_for(version):
    return pu_rules.with_fia_pu_rules(coef.DEFAULT) if version == "2.1.0" else coef.DEFAULT


def repair(state, wanted, coeffs):
    """{(driver, component): action} -> legal option, respecting the team's stock across drivers."""
    option, used = [], {}
    for driver in APEX:
        legal = available_component_actions(state, driver, coeffs)
        for comp in COMPONENTS:
            action = wanted.get((driver, comp), "USE")
            if action == "REPLACE" and pu_rules.enabled(coeffs):
                stock = state.resource_inventory[TEAM].get(pu_rules.stock_key(comp), 0)
                if stock - used.get(comp, 0) <= 0:
                    action = "USE"
            if action not in legal[comp]:
                action = legal[comp][0]
            if action == "REPLACE":
                used[comp] = used.get(comp, 0) + 1
            option.append((driver, comp, action))
    return tuple(option)


def prepared(state, option, coeffs):
    working = copy.deepcopy(state)
    chosen = {(d, c): a for d, c, a in option}
    prepare_race(working, published_rule_decisions(working, coeffs, {TEAM}, chosen), coeffs)
    return working


class Planner(R1.SeasonPlanner):
    """1.1.0 planner with 2.1.0-aware repair/preparation and bundle moves."""

    def race_value(self, prep):  # same valuation as 1.1.0, under this planner's coeffs
        return super().race_value(prep)

    def plan_value(self, state, plan):
        total, first = 0.0, None
        for wanted in plan:
            option = repair(state, wanted, self.coeffs)
            first = first or option
            prep = prepared(state, option, self.coeffs)
            total += self.race_value(prep)
            state = copy.deepcopy(prep)
            advance_without_result(state, self.coeffs)
        return total, first

    def choose(self, state, warm=None):
        races = len(state.calendar) - state.race_index
        seeds = [[{} for _ in range(races)]]
        threshold = self.coeffs["rival_component_policy"]["threshold"]
        rule, walk = [], copy.deepcopy(state)
        for _ in range(races):  # the published replacement rule as a starting plan
            wanted = {(d, c): "REPLACE" for d in APEX for c in COMPONENTS if walk.power_units[d][c].wear >= threshold}
            rule.append(wanted)
            walk = prepared(walk, repair(walk, wanted, self.coeffs), self.coeffs)
            advance_without_result(walk, self.coeffs)
        seeds.append(rule)
        subsets = [[c for i, c in enumerate(COMPONENTS) if mask >> i & 1] for mask in range(1, 2 ** len(COMPONENTS))]
        for race in range(races):
            for subset in subsets:
                both = [{} for _ in range(races)]
                both[race] = {(d, c): "REPLACE" for d in APEX for c in subset}
                seeds.append(both)
                if pu_rules.enabled(self.coeffs):  # per-driver bundles (penalty bundling / timing)
                    for d in APEX:
                        one = [{} for _ in range(races)]
                        one[race] = {(d, c): "REPLACE" for c in subset}
                        seeds.append(one)
        if warm:
            seeds.append((list(warm) + [{}] * races)[:races])
        best_value, best_plan = float("-inf"), None
        for plan in seeds:
            value, _ = self.plan_value(state, plan)
            if value > best_value + 1e-9:
                best_value, best_plan = value, plan
        pairs = [(d, c) for d in APEX for c in COMPONENTS]
        for _ in range(R1.PLAN_SWEEPS):
            improved = False
            for race in range(races):
                candidates = [m for pair in pairs for m in self._moves(best_plan, race, pair)]
                candidates += self._bundle_moves(best_plan, race)
                for candidate in candidates:
                    value, _ = self.plan_value(state, candidate)
                    if value > best_value + 1e-9:
                        best_value, best_plan, improved = value, candidate, True
            if not improved:
                break
        _, first = self.plan_value(state, best_plan)
        return first, best_plan, best_value

    @staticmethod
    def _bundle_moves(plan, race):
        """Move one driver's whole bundle at `race` one race earlier or later."""
        out = []
        for d in APEX:
            bundle = {k: v for k, v in plan[race].items() if k[0] == d}
            if len(bundle) < 2:
                continue
            for target in (race - 1, race + 1):
                if 0 <= target < len(plan):
                    moved = [dict(step) for step in plan]
                    for k in bundle:
                        moved[race].pop(k, None)
                        moved[target][k] = "REPLACE"
                    out.append(moved)
        return out


class Reference21:
    def __init__(self, rules=None, log=None):
        self.version = (rules or {}).get("benchmark_version", "2.1.0")
        self.ok = self.version in (C.INTEGRATED_VERSION,) + C.OPT_IN_VERSIONS
        self.coeffs = coeffs_for(self.version)
        cfg = C.with_version(C.solo_coordination(engineers="CHIEF_ONLY", chief={"provider": "reference"}),
                             self.version if self.ok else C.INTEGRATED_VERSION)
        self.model = IntegratedSession(cfg, base_seed=0)
        self.planner = Planner(self.coeffs)
        self.warm = None
        self.stats = {"decisions": 0, "fallbacks": 0, "resyncs": 0, "race_decisions": 0, "version": self.version}
        self.log = log
        self.fallback = None

    def decide(self, obs):
        self.stats["decisions"] += 1
        if self.ok:
            try:
                if obs["decision_type"] != self.model.decision_type or obs.get("tick_id") != self.model.tick_id:
                    raise RuntimeError("model out of step with the observation")
                action = self._component(obs) if obs["decision_type"] == "COMPONENT_DECISION" else self._race(obs)
                self.model.submit(TEAM, self.model.tick_id, copy.deepcopy(action))
                return action
            except Exception as exc:  # never lose the season to a reference bug
                self.ok = False
                self.stats["fallbacks"] += 1
                if self.log:
                    self.log(f"fallback to baseline: {type(exc).__name__}: {exc}")
        else:
            self.stats["fallbacks"] += 1
        if self.fallback is None:
            from f1pitwall.integrated.policies import scripted  # the published baseline policy
            self.fallback = scripted("baseline")
        return self.fallback(obs)

    def _component(self, obs):
        mine = self.model.observation(TEAM)
        for key in ("controlled_drivers", "rivals_public", "resource_inventory"):
            if mine[key] != obs[key]:
                raise RuntimeError(f"{key} differs from the observation")
        started = time.time()
        option, plan, value = self.planner.choose(self.model.state, self.warm)
        self.warm = plan[1:]
        if self.log:
            replaced = [f"{d}:{c}" for d, c, a in option if a == "REPLACE"]
            self.log(f"race {obs['championship']['race_index'] + 1}: replace {replaced or 'nothing'} "
                     f"(plan value {value:.1f}, {time.time() - started:.1f}s)")
        return {"type": "COMPONENT_DECISION",
                "decisions": [{"driver": d, "component": c, "action": a} for d, c, a in option]}

    def _race(self, obs):
        self.stats["race_decisions"] += 1
        race = self.model.race_state
        real = obs["race_progress"]
        if race["step"] != real["decision_index"] - 1:
            raise RuntimeError("race step differs from the observation")
        race["events"][race["step"]] = real["track_status"]  # observed now; later entries are never read
        self._sync_cars(race, real)
        action, _ = R1.rollout_action(race)
        legal_orders = obs["team_orders"]["legal_team_orders"]
        order = "RACE" if "RACE" in legal_orders else "KEEP_ORDER"
        return {"type": "RACE_STRATEGY", **action, "team_order": {"order": order}}

    def _sync_cars(self, race, real):
        cars = {ENGINE_TO_CHAMPIONSHIP_DRIVER[car["name"]]: car for car in race["cars"]}
        repaired = False
        for entry in real["classification"]:
            car = cars[entry["driver"]]
            if (car["compound"], car["tyre_age"], sorted(set(car["compounds_used"]))) != (
                    entry["compound"], entry["tyre_age"], entry["compounds_used"]):
                raise RuntimeError("tyre state differs from the observation")
            if abs(car["elapsed"] - entry["elapsed"]) > R1.ELAPSED_TOLERANCE:
                car["elapsed"] = entry["elapsed"]
                repaired = True
        if repaired:
            self.stats["resyncs"] += 1


def call(*args):
    proc = subprocess.run(["f1ctl", *args], capture_output=True, text=True)
    response = json.loads(proc.stdout)
    if not response.get("ok"):
        raise SystemExit(f"f1ctl {args[0]} failed: {response}")
    return response


def main():
    log = lambda message: print(message, file=sys.stderr, flush=True)  # noqa: E731
    rules = call("rules").get("rules", {})
    player = Reference21(rules, log)
    obs = call("observe")["observation"]
    started = time.time()
    while obs["decision_type"] != "CHAMPIONSHIP_COMPLETE":
        action = player.decide(obs)
        obs = call("act", obs["decision_id"], json.dumps(action))["observation"]
    print(json.dumps({"reference": "public-information rollout (2.1.0 port)", "futures": R1.FUTURES,
                      "seconds": round(time.time() - started, 1), **player.stats,
                      "team_standings": obs["championship"]["team_standings"]}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
