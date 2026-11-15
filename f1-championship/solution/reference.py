#!/usr/bin/env python3
"""Reference player: public-information rollout (the B4/B5 analysis reference, made executable).

It plays through the same interface as an agent (`observe` / `act`) and reads nothing else.

Information
  * Public observations and the published rules only. No seed, no journal, no simulator state.
  * It carries a *model* of the championship: `lib/f1pitwall`, the published rules as executable
    code. The model is started with a dummy seed (0) and is re-synchronised to every observation:
    the track status of each decision is copied from the observation, and the model's race
    observation is compared with the real one at every decision. Component wear, grids and race
    dynamics are deterministic given public information, so the model never needs hidden data;
    the hidden parts (future SC/VSC, retirement draws) are never read from it.
  * An agent has the same rules (`f1ctl rules`) but must build the model itself. That modelling
    advantage is the documented difference between this reference and an agent.

Policy
  * Race strategy: at every decision, each of the 16 joint actions is played now and the public
    baseline heuristic (play.py) afterwards, over FUTURES futures sampled from the published
    SC/VSC model conditioned on the statuses observed so far. Value = exact expected Apex points
    over the published retirement probabilities. The best mean is submitted. One-step lookahead:
    budget-limited, not optimal.
  * Components: a fixed-budget search over season replacement plans (see `component_plan`),
    scored by the same public model.

If anything is inconsistent (unknown benchmark version, model/observation mismatch that cannot be
repaired, any exception) it falls back to the public baseline heuristic for that decision, so the
season always completes.
"""

from __future__ import annotations

import copy
import json
import os
import random
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
for candidate in (HERE / "lib", HERE.parent / "src"):
    if (candidate / "f1pitwall").is_dir():
        sys.path.insert(0, str(candidate))
        break
sys.path.insert(0, str(HERE))

import play  # noqa: E402  (public baseline heuristic)
from f1pitwall import coefficients as coef  # noqa: E402
from f1pitwall import engine  # noqa: E402
from f1pitwall.championship_adapter import ENGINE_TO_CHAMPIONSHIP_DRIVER, start_prepared_race  # noqa: E402
from f1pitwall.championship_contract import ChampionshipSession  # noqa: E402
from f1pitwall.championship_transition import (  # noqa: E402
    advance_without_result,
    available_component_actions,
    prepare_race,
    rival_component_decisions,
)
from f1pitwall.version import BENCHMARK_VERSION  # noqa: E402

FUTURES = int(os.environ.get("F1_REF_FUTURES", "32"))
PLAN_PATHS = int(os.environ.get("F1_REF_PLAN_PATHS", "48"))
PLAN_SWEEPS = int(os.environ.get("F1_REF_PLAN_SWEEPS", "4"))
ELAPSED_TOLERANCE = 0.002  # observations round elapsed time to 3 decimals
APEX = ("Apex A", "Apex B")
COMPONENTS = coef.COMPONENTS


# ------------------------------------------------------------------ race model helpers

def copy_race(race):
    out = dict(race)
    out["cars"] = [{**car, "compounds_used": list(car["compounds_used"])} for car in race["cars"]]
    out["events"] = list(race["events"])
    out["actions"] = list(race["actions"])
    return out


def expected_points(race):
    """Exact expected Apex points at the finish over the published retirement probabilities."""
    order = sorted(race["cars"], key=lambda car: (car["elapsed"] + engine.finish_penalty(race, car), car["name"]))
    p_dnf = race["config"]["dnf_prob"]
    total = 0.0
    for index, car in enumerate(order):
        if car["team"] != "Apex":
            continue
        dist = [1.0]
        for ahead in order[:index]:
            q = 1.0 - p_dnf[ahead["name"]]
            nxt = [0.0] * (len(dist) + 1)
            for k, mass in enumerate(dist):
                nxt[k] += mass * (1.0 - q)
                nxt[k + 1] += mass * q
            dist = nxt
        total += (1.0 - p_dnf[car["name"]]) * sum(mass * engine.POINTS[k] for k, mass in enumerate(dist))
    return total


def baseline_action(race):
    action = play.race_action({"race_progress": engine.observation(race)})
    return {"driver_a": action["driver_a"], "driver_b": action["driver_b"]}


def finish_with_baseline(race):
    while race["step"] < len(race["events"]):
        engine.step(race, baseline_action(race))
    return expected_points(race)


def rollout_action(race, futures=FUTURES):
    """Best joint action by one-step lookahead; futures depend only on observed statuses."""
    seen = race["events"][:race["step"] + 1]
    rng = random.Random(f"rollout|{len(race['events'])}|{race['step']}|{seen}")
    paths = engine.sample_future_statuses(rng, race, futures)
    legal = engine.legal_actions(race)
    best, best_value, table = None, float("-inf"), {}
    for a in legal:
        for b in legal:
            action = {"driver_a": a, "driver_b": b}
            total = 0.0
            for future in paths:
                child = copy_race(race)
                engine.step(child, action)
                child["events"][child["step"]:] = future
                total += finish_with_baseline(child)
            table[f"{a}/{b}"] = total / len(paths)
            if total > best_value + 1e-9:
                best, best_value = action, total
    return best, table


# ------------------------------------------------------------------ component planning

def _prepared(state, option, coeffs):
    working = copy.deepcopy(state)
    apex = [{"driver": d, "component": c, "action": a} for d, c, a in option]
    prepare_race(working, apex + rival_component_decisions(state, coeffs), coeffs)
    return working


def _repair(state, wanted, coeffs):
    """{(driver, component): action} -> legal option (REPLACE is forced above the wear limit)."""
    option = []
    for driver in APEX:
        legal = available_component_actions(state, driver, coeffs)
        for comp in COMPONENTS:
            action = wanted.get((driver, comp), "USE")
            if action not in legal[comp]:
                action = legal[comp][0]
            option.append((driver, comp, action))
    return tuple(option)


class SeasonPlanner:
    """Coordinate search over season replacement plans, scored with the public model.

    A plan's value is the sum over the remaining races of the expected Apex points of that race
    when it is played with the public baseline heuristic, averaged over PLAN_PATHS event paths
    drawn from the published SC/VSC model with a public seed. Component wear does not depend on
    race events, so the season path of a plan is deterministic. Search: simple starting plans
    (no replacement, the rivals' public rule, one service stop), then at most PLAN_SWEEPS sweeps of
    single-replacement moves, each accepted only if it improves the plan. Not proven optimal."""

    def __init__(self, coeffs=coef.DEFAULT):
        self.coeffs = coeffs
        self.cache = {}
        self.evaluations = 0

    def race_value(self, prepared):
        track = prepared.calendar[prepared.race_index]
        key = json.dumps([prepared.race_index, track.name,
                          {d: {c: round(v.wear, 9) for c, v in comps.items()}
                           for d, comps in prepared.power_units.items()},
                          prepared.grid_penalties], sort_keys=True)
        if key not in self.cache:
            self.evaluations += 1
            race = start_prepared_race(copy.deepcopy(prepared), 0, self.coeffs).race_state
            model = race["config"]["neutralization"]
            rng = random.Random(f"plan|{len(race['events'])}")
            total = 0.0
            for _ in range(PLAN_PATHS):
                branch = copy_race(race)
                branch["events"] = engine._continue_schedule(rng, [], len(race["events"]), model)
                total += finish_with_baseline(branch)
            self.cache[key] = total / PLAN_PATHS
        return self.cache[key]

    def plan_value(self, state, plan):
        total, first = 0.0, None
        for wanted in plan:
            option = _repair(state, wanted, self.coeffs)
            first = first or option
            prepared = _prepared(state, option, self.coeffs)
            total += self.race_value(prepared)
            state = copy.deepcopy(prepared)
            advance_without_result(state, self.coeffs)
        return total, first

    def choose(self, state, warm=None):
        races = len(state.calendar) - state.race_index
        seeds = [[{} for _ in range(races)]]
        threshold = self.coeffs["rival_component_policy"]["threshold"]
        rule, walk = [], copy.deepcopy(state)
        for _ in range(races):  # the public rivals' replacement rule as a starting plan
            wanted = {(d, c): "REPLACE" for d in APEX for c in COMPONENTS
                      if walk.power_units[d][c].wear >= threshold}
            rule.append(wanted)
            walk = _prepared(walk, _repair(walk, wanted, self.coeffs), self.coeffs)
            advance_without_result(walk, self.coeffs)
        seeds.append(rule)
        subsets = [[c for i, c in enumerate(COMPONENTS) if mask >> i & 1] for mask in range(1, 2 ** len(COMPONENTS))]
        for race in range(races):  # one service stop: the same parts on both cars before one race
            for subset in subsets:
                plan = [{} for _ in range(races)]
                plan[race] = {(d, c): "REPLACE" for d in APEX for c in subset}
                seeds.append(plan)
        if warm:
            seeds.append((list(warm) + [{}] * races)[:races])
        best_value, best_plan = float("-inf"), None
        for plan in seeds:
            value, _ = self.plan_value(state, plan)
            if value > best_value + 1e-9:
                best_value, best_plan = value, plan
        pairs = [(d, c) for d in APEX for c in COMPONENTS]
        for _ in range(PLAN_SWEEPS):
            improved = False
            for race in range(races):
                for pair in pairs:
                    for candidate in self._moves(best_plan, race, pair):
                        value, _ = self.plan_value(state, candidate)
                        if value > best_value + 1e-9:
                            best_value, best_plan, improved = value, candidate, True
            if not improved:
                break
        _, first = self.plan_value(state, best_plan)
        return first, best_plan, best_value

    @staticmethod
    def _moves(plan, race, pair):
        """Toggle one replacement; move it one race earlier or later; give it to the team-mate."""
        toggled = [dict(step) for step in plan]
        if toggled[race].pop(pair, None) is None:
            toggled[race][pair] = "REPLACE"
            return [toggled]
        out = [toggled]
        for target in (race - 1, race + 1):
            if 0 <= target < len(plan):
                moved = [dict(step) for step in toggled]
                moved[target][pair] = "REPLACE"
                out.append(moved)
        mate = [dict(step) for step in toggled]
        mate[race][("Apex B" if pair[0] == "Apex A" else "Apex A", pair[1])] = "REPLACE"
        out.append(mate)
        return out


# ------------------------------------------------------------------ the player

class Reference:
    def __init__(self, rules=None, log=None):
        self.ok = rules is None or rules.get("benchmark_version") == BENCHMARK_VERSION
        self.model = ChampionshipSession(base_seed=0)
        self.planner = SeasonPlanner()
        self.warm = None
        self.stats = {"decisions": 0, "fallbacks": 0, "resyncs": 0, "race_decisions": 0}
        self.log = log

    def decide(self, obs):
        self.stats["decisions"] += 1
        try:
            if not self.ok or obs["decision_type"] != self.model.decision_type:
                raise RuntimeError("model out of step with the observation")
            if obs["decision_type"] == "COMPONENT_DECISION":
                action = self._component(obs)
            else:
                action = self._race(obs)
            self.model.submit(copy.deepcopy(action))
            return action
        except Exception as exc:  # never lose the season to a reference bug
            self.ok = False
            self.stats["fallbacks"] += 1
            if self.log:
                self.log(f"fallback to baseline: {type(exc).__name__}: {exc}")
            return (play.component_action(obs) if obs["decision_type"] == "COMPONENT_DECISION"
                    else play.race_action(obs))

    def _component(self, obs):
        mine = self.model.observation()
        if mine["controlled_drivers"] != obs["controlled_drivers"] or mine["rivals_public"] != obs["rivals_public"]:
            raise RuntimeError("component state differs from the observation")
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
        race = self.model._active_race.race_state
        real = obs["race_progress"]
        if race["step"] != real["decision_index"] - 1:
            raise RuntimeError("race step differs from the observation")
        race["events"][race["step"]] = real["track_status"]  # observed now; later entries are never read
        self._sync_cars(race, real)
        action, _ = rollout_action(race)
        return {"type": "RACE_STRATEGY", **action}

    def _sync_cars(self, race, real):
        """The model must reproduce the public race state; repair it from the observation if not."""
        cars = {ENGINE_TO_CHAMPIONSHIP_DRIVER[car["name"]]: car for car in race["cars"]}
        repaired = False
        for entry in real["classification"]:
            car = cars[entry["driver"]]
            if (car["compound"], car["tyre_age"], sorted(set(car["compounds_used"]))) != (
                    entry["compound"], entry["tyre_age"], entry["compounds_used"]):
                raise RuntimeError("tyre state differs from the observation")
            if abs(car["elapsed"] - entry["elapsed"]) > ELAPSED_TOLERANCE:
                car["elapsed"] = entry["elapsed"]
                repaired = True
        if repaired:
            self.stats["resyncs"] += 1


# ------------------------------------------------------------------ f1ctl driver

def call(*args):
    proc = subprocess.run(["f1ctl", *args], capture_output=True, text=True)
    response = json.loads(proc.stdout)
    if not response.get("ok"):
        raise SystemExit(f"f1ctl {args[0]} failed: {response}")
    return response


def main():
    log = lambda message: print(message, file=sys.stderr, flush=True)  # noqa: E731
    rules = call("rules").get("rules", {})
    player = Reference(rules, log)
    obs = call("observe")["observation"]
    started = time.time()
    while obs["decision_type"] != "CHAMPIONSHIP_COMPLETE":
        action = player.decide(obs)
        obs = call("act", obs["decision_id"], json.dumps(action))["observation"]
    print(json.dumps({"reference": "public-information rollout", "futures": FUTURES,
                      "seconds": round(time.time() - started, 1), **player.stats,
                      "team_standings": obs["championship"]["team_standings"]}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
