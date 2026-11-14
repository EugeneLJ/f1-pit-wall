"""Budgeted receding-horizon (MPC) planner for full 8-race Track A seasons.

At every race the planner searches component plans for the next H races and
executes only the first decision, then replans at the next race.

* Plan value = sum of exact expected race values (track_a_solver.Solver.race_value)
  along the deterministic wear/inventory path. No terminal value beyond the window.
* Search = deterministic first-improvement local search over the plan, seeded
  with simple public plans, under a fixed budget of race evaluations (cache
  misses). H = 1 is exhaustive (it is the greedy policy).
* Information: identical to the fair 3-race solver (public state, public rival
  rule, published probabilities and formulas). No seeds or future events.

Because component decisions never depend on race outcomes, the executed season
path of any of these policies is deterministic, so a policy's season value is
an exact expectation (in-race PIT/STAY play uses the public baseline policy).
This is a planner, not a proof of optimality.
"""

from __future__ import annotations

import random
import time
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

import track_a_solver as ts
from f1pitwall import coefficients as coef
from f1pitwall.championship import ChampionshipState
from f1pitwall.championship_transition import available_component_actions

PAIRS = [(d, c) for d in ts.APEX for c in ts.COMPONENTS]
# Compute budget per decision: race evaluations (exact expected race values) and plan rollouts.
DEFAULT_RACE_BUDGET = 1500
PLAN_EVALUATION_CAP = 6000


class BudgetExceeded(Exception):
    pass


class Evaluator:
    """Counts race evaluations (cache misses) against a per-decision budget."""

    def __init__(self, solver: ts.Solver):
        self.solver = solver
        self.budget: Optional[int] = None
        self.used = 0
        self._transitions: Dict[Tuple[str, Tuple], Tuple[float, ChampionshipState]] = {}

    def step(self, state: ChampionshipState, option: Tuple, coeffs) -> Tuple[float, ChampionshipState]:
        """(expected race value, next state) for one decision; transitions are cached."""
        key = (ts.state_key(state), option)
        if key not in self._transitions:
            prepared = ts.prepare(state, option, coeffs)
            self._transitions[key] = (self.race_value(prepared), ts.after_race(prepared, coeffs))
        return self._transitions[key]

    def race_value(self, prepared: ChampionshipState) -> float:
        before = self.solver.race_evaluations
        if self.budget is not None and self.used >= self.budget:
            key = ts.race_key(prepared)
            if key not in self.solver._race_cache:
                raise BudgetExceeded
        value = self.solver.race_value(prepared)
        self.used += self.solver.race_evaluations - before
        return value


def repair(state: ChampionshipState, decision: Dict[Tuple[str, str], str], coeffs) -> Tuple:
    """Turn a {pair: action} dict into a legal option (forced REPLACE above the wear limit)."""
    option = []
    for driver, comp in PAIRS:
        action = decision.get((driver, comp), "USE")
        if action == "USE" and "USE" not in available_component_actions(state, driver, coeffs)[comp]:
            action = "REPLACE"
        option.append((driver, comp, action))
    return tuple(option)


def rollout(ev: Evaluator, state: ChampionshipState, plan: Sequence[Dict], coeffs) -> Tuple[float, List]:
    """Value of executing plan (list of decision dicts) from state; returns value and options."""
    total, options = 0.0, []
    for decision in plan:
        if state.race_index >= len(state.calendar):
            break
        option = repair(state, decision, coeffs)
        value, state = ev.step(state, option, coeffs)
        total += value
        options.append(option)
    return total, options


def _rule_plan(state, horizon, rule, ev, coeffs) -> List[Dict]:
    plan = []
    for _ in range(horizon):
        if state.race_index >= len(state.calendar):
            break
        option = ev.solver.choose(state, rule)
        plan.append({(d, c): a for d, c, a in option})
        state = ts.after_race(ts.prepare(state, option, coeffs), coeffs)
    return plan


def search(ev: Evaluator, state: ChampionshipState, horizon: int, budget: int,
           warm: Optional[List[Dict]] = None, coeffs=coef.DEFAULT) -> Tuple[float, List[Dict], Dict[str, Any]]:
    """Best plan found for the next `horizon` races within `budget` race evaluations."""
    horizon = min(horizon, len(state.calendar) - state.race_index)
    ev.used, ev.budget = 0, budget
    started = time.time()
    if horizon == 1:
        ev.budget = None  # exhaustive greedy
        best = max(((ev.race_value(ts.prepare(state, o, coeffs)), o) for o in ts.apex_options(state, coeffs)),
                   key=lambda item: (round(item[0], 9), -sum(a == "REPLACE" for *_, a in item[1])))
        info = {"evaluations": ev.used, "seconds": round(time.time() - started, 3), "plan_evaluations": 0,
                "budget_exhausted": False}
        return best[0], [{(d, c): a for d, c, a in best[1]}], info

    seeds = [[{} for _ in range(horizon)]]
    try:
        seeds.append(_rule_plan(state, horizon, "rival_rule", ev, coeffs))
        seeds.append(_rule_plan(state, horizon, "greedy", ev, coeffs))
    except BudgetExceeded:
        pass
    if warm:
        seeds.append((list(warm) + [{}] * horizon)[:horizon])
    best_value, best_plan, plan_evals, exhausted = float("-inf"), None, 0, False
    rng = random.Random(ts.state_key(state) + f"|H{horizon}")
    counter = {"plans": 0}
    incumbent = {"value": float("-inf"), "plan": None}

    def evaluate(plan):
        if counter["plans"] >= PLAN_EVALUATION_CAP:
            raise BudgetExceeded
        counter["plans"] += 1
        value, options = rollout(ev, state, plan, coeffs)
        plan = [{(d, c): a for d, c, a in o} for o in options]
        if value > incumbent["value"] + 1e-9:  # best plan seen so far, kept even if the budget runs out
            incumbent["value"], incumbent["plan"] = value, plan
        return value, plan

    def local_search(value, plan):
        improved = True
        while improved:
            improved = False
            # block move: every legal option at one race, the rest of the plan held fixed
            for race in range(len(plan)):
                for candidate in _block_candidates(state, plan, race, coeffs):
                    v, p = evaluate(candidate)
                    if v > value + 1e-9:
                        value, plan, improved = v, p, True
            # single-pair moves: toggle, shift one race earlier/later, give to teammate
            for race in range(len(plan)):
                for pair in PAIRS:
                    for candidate in _neighbours(plan, race, pair):
                        v, p = evaluate(candidate)
                        if v > value + 1e-9:
                            value, plan, improved = v, p, True
        return value, plan

    try:
        for seed in seeds:
            value, plan = local_search(*evaluate(seed))
            if value > best_value + 1e-9:
                best_value, best_plan = value, plan
        while True:  # iterated local search: random kicks until the budget is spent
            kicked = [dict(step) for step in best_plan]
            for _ in range(rng.randint(2, 4)):
                race, pair = rng.randrange(len(kicked)), rng.choice(PAIRS)
                kicked[race][pair] = "USE" if kicked[race].get(pair, "USE") == "REPLACE" else "REPLACE"
            value, plan = local_search(*evaluate(kicked))
            if value > best_value + 1e-9:
                best_value, best_plan = value, plan
            if horizon == 1 or ev.budget is None:
                break
    except BudgetExceeded:
        exhausted = True
    if incumbent["value"] > best_value:
        best_value, best_plan = incumbent["value"], incumbent["plan"]
    plan_evals = counter["plans"]
    info = {"evaluations": ev.used, "seconds": round(time.time() - started, 3),
            "plan_evaluations": plan_evals, "budget_exhausted": exhausted}
    ev.budget = None
    return best_value, best_plan, info


def _block_candidates(state, plan: List[Dict], race: int, coeffs) -> List[List[Dict]]:
    """All legal options at `race` (state reached by the current plan prefix)."""
    prefix_state = state
    for step in plan[:race]:
        option = repair(prefix_state, step, coeffs)
        prefix_state = ts.after_race(ts.prepare(prefix_state, option, coeffs), coeffs)
    out = []
    for option in ts.apex_options(prefix_state, coeffs):
        candidate = [dict(step) for step in plan]
        candidate[race] = {(d, c): a for d, c, a in option}
        out.append(candidate)
    return out


def _neighbours(plan: List[Dict], race: int, pair) -> List[List[Dict]]:
    """Toggle one action; move a replacement one race earlier/later; give it to the teammate."""
    out = []
    current = plan[race].get(pair, "USE")
    toggled = [dict(step) for step in plan]
    toggled[race][pair] = "USE" if current == "REPLACE" else "REPLACE"
    out.append(toggled)
    if current == "REPLACE":
        for shift in (-1, 1):
            target = race + shift
            if 0 <= target < len(plan):
                moved = [dict(step) for step in plan]
                moved[race][pair] = "USE"
                moved[target][pair] = "REPLACE"
                out.append(moved)
        mate = ("Apex B" if pair[0] == "Apex A" else "Apex A", pair[1])
        swapped = [dict(step) for step in plan]
        swapped[race][pair] = "USE"
        swapped[race][mate] = "REPLACE"
        out.append(swapped)
    return out


def run_season(state: ChampionshipState, policy: str, budget: int = DEFAULT_RACE_BUDGET,
               solver: Optional[ts.Solver] = None, coeffs=coef.DEFAULT,
               forced_prefix: Optional[List[Tuple]] = None) -> Dict[str, Any]:
    """Execute a policy over the rest of the season; returns the exact expected path.

    policy: always_use | rival_rule | greedy | mpc:H | exact3 (receding exact 3-race DP).
    forced_prefix: options executed at the first races before the policy takes over
    (cross-world tests); illegal USE is repaired to REPLACE.
    """
    solver = solver or ts.Solver(coeffs)
    ev = Evaluator(solver)
    path, warm = [], None
    started = time.time()
    while state.race_index < len(state.calendar):
        info: Dict[str, Any] = {}
        if forced_prefix is not None and len(path) < len(forced_prefix):
            option = repair(state, {(d, c): a for d, c, a in forced_prefix[len(path)]}, coeffs)
        elif policy in ("always_use", "rival_rule", "greedy"):
            option = solver.choose(state, policy)
        elif policy == "exact3":
            before = solver.race_evaluations
            t0 = time.time()
            window = _window(state, 3)
            option = solver.optimal(window)[1]
            info = {"evaluations": solver.race_evaluations - before, "seconds": round(time.time() - t0, 3)}
        elif policy.startswith("mpc:"):
            horizon = int(policy.split(":")[1])
            _, plan, info = search(ev, state, horizon, budget, warm, coeffs)
            option = repair(state, plan[0], coeffs)
            warm = plan[1:]
        else:
            raise ValueError(policy)
        prepared = ts.prepare(state, option, coeffs)
        value = ev.solver.race_value(prepared)
        path.append({"race": state.race_index, "track": state.calendar[state.race_index].name,
                     "archetype": state.calendar[state.race_index].archetype,
                     "option": ts.option_label(option),
                     "replacements": [f"{d}:{c}" for d, c, a in option if a == "REPLACE"],
                     "free_units_before": state.resource_inventory["Apex"].get("component_spares"),
                     "grid_drops": {d: prepared.grid_penalties[d] for d in ts.APEX},
                     "expected_points": value, **({"search": info} if info else {})})
        state = ts.after_race(prepared, coeffs)
    return {"policy": policy, "expected_points": sum(step["expected_points"] for step in path),
            "path": path, "seconds": round(time.time() - started, 2)}


def _window(state: ChampionshipState, horizon: int) -> ChampionshipState:
    """Truncate the calendar so a DP sees only the next `horizon` races (no terminal value)."""
    import copy
    window = copy.deepcopy(state)
    window.calendar = window.calendar[:min(len(window.calendar), state.race_index + horizon)]
    return window


def realized_path_points(state: ChampionshipState, path_options: List[Tuple], base_seed: int,
                         solver: ts.Solver, coeffs=coef.DEFAULT) -> List[int]:
    """Realized per-race Apex points of a fixed component path on one seed."""
    out = []
    for option in path_options:
        prepared = ts.prepare(state, option, coeffs)
        out.append(ts.realized_race_value(solver._seeded_race(prepared, base_seed)))
        state = ts.after_race(prepared, coeffs)
    return out


def options_from_path(state: ChampionshipState, path: List[Dict], coeffs=coef.DEFAULT) -> List[Tuple]:
    options = []
    for step in path:
        decision = {tuple(item.split(":")): "REPLACE" for item in step["replacements"]}
        option = repair(state, decision, coeffs)
        options.append(option)
        state = ts.after_race(ts.prepare(state, option, coeffs), coeffs)
    return options
