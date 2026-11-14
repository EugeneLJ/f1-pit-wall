"""Level (a) tests: each Track A mechanic really changes state or outcomes.

Levels (b) policy value and (c) optimal-action change are measured by the
exact solver experiment (analysis/run_track_a.py) and reported in docs/P1_REPORT.md.
Run from the task directory:  python3 -m unittest discover -s devtests -v
"""

from __future__ import annotations

import copy
import importlib.util
import itertools
import json
import sys
import unittest
from pathlib import Path

TASK = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TASK / "src"))
sys.path.insert(0, str(TASK / "analysis"))

from f1pitwall import coefficients as coef  # noqa: E402
from f1pitwall import engine  # noqa: E402
from f1pitwall.championship import RaceEntry, new_championship_state  # noqa: E402
from f1pitwall.championship_adapter import car_performance, race_config, start_prepared_race  # noqa: E402
from f1pitwall.championship_contract import ChampionshipSession  # noqa: E402
from f1pitwall.championship_transition import (  # noqa: E402
    available_component_actions,
    free_units,
    initial_inventory,
    prepare_race,
    rival_component_decisions,
)
import track_a_solver as ts  # noqa: E402

STAY = {"driver_a": "STAY", "driver_b": "STAY"}


def track(archetype="mixed", stress=0.6, overtaking=0.5, degradation=0.5, name="T"):
    return RaceEntry(name=name, archetype=archetype, power_unit_stress=stress,
                     overtaking_difficulty=overtaking, tyre_degradation=degradation,
                     synthetic_placeholder=True)


def season(races, coeffs=coef.DEFAULT):
    calendar = [track(name=f"T{i}", **r) if isinstance(r, dict) else r for i, r in enumerate(races)]
    return new_championship_state(calendar=calendar, resource_inventory=initial_inventory(coeffs))


def use_all(state, coeffs=coef.DEFAULT, apex=None):
    apex = apex or {}
    out = []
    for driver, comps in state.power_units.items():
        for name in comps:
            out.append({"driver": driver, "component": name, "action": apex.get((driver, name), "USE")})
    rivals = {(d["driver"], d["component"]): d["action"] for d in rival_component_decisions(state, coeffs)}
    for item in out:
        item["action"] = rivals.get((item["driver"], item["component"]), item["action"])
    return out


def set_wear(state, driver, wear):
    for component in state.power_units[driver].values():
        component.wear = wear


def run_race(state, coeffs=coef.DEFAULT, seed=7, events=None, apex=None, actions=None):
    working = copy.deepcopy(state)
    prepare_race(working, use_all(working, coeffs, apex), coeffs)
    race = start_prepared_race(working, seed, coeffs, events=events).race_state
    for action in actions or [STAY] * len(race["events"]):
        engine.step(race, action)
    return race, engine.result(race)


def apex_elapsed(race, name="Apex A"):
    return next(car["elapsed"] for car in race["cars"] if car["name"] == name)


class CoefficientFileTests(unittest.TestCase):
    def test_coefficients_are_marked_synthetic_and_separate_from_code(self):
        raw = json.loads(coef.COEFFICIENT_FIXTURE.read_text())
        self.assertEqual(raw["data_status"], "synthetic_placeholder")

    def test_team_profiles_are_zero_mean(self):
        profiles = coef.DEFAULT["track_performance"]["team_archetype_pace_offset_sec_per_lap"]
        for team in ("Apex", "Orion", "Nova", "Vertex"):
            self.assertAlmostEqual(sum(profiles[team].values()), 0.0, places=9, msg=team)


class LegacyPathTests(unittest.TestCase):
    def test_unconfigured_engine_matches_frozen_legacy_engine(self):
        spec = importlib.util.spec_from_file_location("legacy_engine", TASK.parent / "environment" / "f1pitwall" / "engine.py")
        legacy = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(legacy)
        pairs = [{"driver_a": a, "driver_b": b} for a in ("PIT", "STAY") for b in ("PIT", "STAY")]
        for seed in (engine.SEED, 3):
            for seq in itertools.product(pairs, repeat=3):
                self.assertEqual(legacy.run_episode(list(seq), seed), engine.run_episode(list(seq), seed))


class WearMechanicTests(unittest.TestCase):
    def test_wear_slows_the_car_more_at_high_stress(self):
        wears = {c: 0.8 for c in coef.COMPONENTS}
        low = coef.pace_loss(wears, 0.4, coef.DEFAULT)
        high = coef.pace_loss(wears, 0.9, coef.DEFAULT)
        self.assertGreater(high, low)
        self.assertGreater(low, coef.pace_loss({c: 0.2 for c in coef.COMPONENTS}, 0.4, coef.DEFAULT))

    def test_worn_car_finishes_slower_in_the_same_race(self):
        fresh = season([{}])
        worn = copy.deepcopy(fresh)
        set_wear(worn, "Apex A", 0.85)
        events = ["GREEN"] * 3
        self.assertGreater(apex_elapsed(run_race(worn, events=events)[0]),
                           apex_elapsed(run_race(fresh, events=events)[0]))

    def test_wear_accrues_by_stress_and_ignores_race_actions_and_events(self):
        base = season([{"stress": 0.9}, {}])
        out = []
        for events, actions in ((["GREEN"] * 3, [STAY] * 3), (["SC", "VSC", "SC"], [{"driver_a": "PIT_MEDIUM", "driver_b": "PIT_HARD"}] * 3)):
            session_state = copy.deepcopy(base)
            prepare_race(session_state, use_all(session_state))
            active = start_prepared_race(session_state, 5, events=events)
            for action in actions:
                engine.step(active.race_state, action)
            from f1pitwall.championship_adapter import finish_prepared_race
            finish_prepared_race(session_state, active)
            out.append(session_state.power_units["Apex A"]["ICE"].wear)
        self.assertEqual(out[0], out[1])
        self.assertAlmostEqual(out[0], 0.9 * coef.DEFAULT["components"]["wear_per_unit_stress"]["ICE"])


class ReliabilityTests(unittest.TestCase):
    def test_dnf_probability_rises_with_wear(self):
        probs = [coef.dnf_probability({c: w for c in coef.COMPONENTS}, 0.7, coef.DEFAULT) for w in (0.3, 0.6, 0.85)]
        self.assertEqual(probs[0], coef.DEFAULT["components"]["reliability"]["base"])
        self.assertLess(probs[0], probs[1])
        self.assertLess(probs[1], probs[2])

    def test_retirement_draws_are_action_independent_and_wear_decides(self):
        draws = engine.dnf_uniforms(11)
        self.assertEqual(draws, engine.dnf_uniforms(11))
        state = season([{"stress": 0.9}])
        set_wear(state, "Apex A", 0.89)
        p = car_performance(state, "Apex A")["dnf_probability"]
        seed = next(s for s in range(500) if engine.dnf_uniforms(s)["Apex A"] < p and
                    engine.dnf_uniforms(s)["Apex A"] >= coef.DEFAULT["components"]["reliability"]["base"])
        _, worn = run_race(state, seed=seed)
        _, fresh = run_race(state, seed=seed, apex={("Apex A", c): "REPLACE" for c in coef.COMPONENTS})
        status = lambda result: next(e["status"] for e in result["classification"] if e["driver"] == "Apex A")  # noqa: E731
        self.assertEqual(status(worn), "DNF")
        self.assertEqual(status(fresh), "FINISHED")
        self.assertEqual(next(e["points"] for e in worn["classification"] if e["driver"] == "Apex A"), 0)


class AllocationTests(unittest.TestCase):
    def test_use_is_illegal_above_limit_and_replace_always_legal(self):
        state = season([{}])
        set_wear(state, "Apex A", 0.95)
        self.assertEqual(available_component_actions(state, "Apex A")["ICE"], ["REPLACE"])
        self.assertEqual(available_component_actions(state, "Apex B")["ICE"], ["USE", "REPLACE"])

    def test_free_units_are_shared_and_then_cost_grid_places(self):
        state = season([{}])
        apex = {("Apex A", c): "REPLACE" for c in coef.COMPONENTS}
        apex.update({("Apex B", "ICE"): "REPLACE", ("Apex B", "turbo"): "REPLACE"})
        prepare_race(state, use_all(state, apex=apex))
        self.assertEqual(state.resource_inventory["Apex"]["component_spares"], 0)
        self.assertEqual(state.grid_penalties["Apex A"], 0)
        self.assertEqual(state.grid_penalties["Apex B"],
                         coef.DEFAULT["allocation"]["grid_drop_when_no_free_unit"]["turbo"])

    def test_split_pool_ablation_isolates_drivers(self):
        split = coef.ablate(coef.DEFAULT, "shared_pool")
        state = season([{}], split)
        apex = {("Apex A", c): "REPLACE" for c in coef.COMPONENTS}
        prepare_race(state, use_all(state, split, apex), split)
        self.assertEqual(free_units(state, "Apex B", split), 2)
        self.assertGreater(state.grid_penalties["Apex A"], 0)

    def test_grid_penalty_moves_driver_back(self):
        state = season([{}])
        state.resource_inventory["Apex"]["component_spares"] = 0
        working = copy.deepcopy(state)
        prepare_race(working, use_all(working, apex={("Apex A", "ICE"): "REPLACE"}))
        active = start_prepared_race(working, 3)
        qualifying = [ts_name for ts_name in race_config(working)["grid"]]
        self.assertEqual(active.starting_grid.index("Apex A") - qualifying.index("Apex A"),
                         coef.DEFAULT["allocation"]["grid_drop_when_no_free_unit"]["ICE"])

    def test_grid_drop_cost_is_positive_and_depends_on_overtaking_difficulty(self):
        """Level (a): the expected cost of a penalty changes with the track. Its direction is
        not imposed (difficulty both blocks recovery and protects the penalised car); the
        measured direction is reported by the experiment."""
        def expected_loss(overtaking, driver):
            state = season([{"overtaking": overtaking, "stress": 0.5}])
            state.resource_inventory["Apex"]["component_spares"] = 0
            solver = ts.Solver()
            base = solver.race_value(ts.prepare(state, solver.choose(state, "always_use"), coef.DEFAULT))
            option = tuple((d, c, "REPLACE" if (d == driver and c == "ICE") else "USE")
                           for d in ts.APEX for c in ts.COMPONENTS)
            return base - solver.race_value(ts.prepare(state, option, coef.DEFAULT))
        for driver in ("Apex A", "Apex B"):
            easy, hard = expected_loss(0.1, driver), expected_loss(0.9, driver)
            self.assertGreater(easy, 0.5)
            self.assertGreater(hard, 0.5)
            self.assertGreater(abs(hard - easy), 0.2)


class TrackPerformanceTests(unittest.TestCase):
    def test_team_profile_changes_qualifying_order_by_archetype(self):
        street = race_config(season([{"archetype": "street"}]))["grid"]
        fast = race_config(season([{"archetype": "high_speed"}]))["grid"]
        self.assertLess(street.index("Apex A"), fast.index("Apex A"))

    def test_overtaking_threshold_depends_on_difficulty(self):
        model = coef.DEFAULT["track_performance"]["overtaking"]
        order = [{"name": "lead"}, {"name": "chaser"}]
        for difficulty, held in ((0.1, False), (0.9, True)):
            finish = {"lead": 100.0, "chaser": 99.0}  # chaser would finish 1.0 s ahead
            engine._apply_overtaking(order, finish, model, difficulty)
            if held:
                self.assertAlmostEqual(finish["chaser"], 100.0 + model["min_gap_sec"])
            else:
                self.assertEqual(finish["chaser"], 99.0)

    def test_dirty_air_applies_only_within_gap(self):
        config = {"grid": list(engine.LEGACY_CAR_NAMES), "pace": engine.LEGACY_BASE_PACE,
                  "overtaking": coef.DEFAULT["track_performance"]["overtaking"],
                  "overtaking_difficulty": 0.5, "events": ["GREEN"] * 3}
        state = engine.new_state(1, config)
        legacy = engine.new_state(1)
        engine.step(state, STAY)
        engine.step(legacy, STAY)
        self.assertNotEqual([c["elapsed"] for c in state["cars"]], [c["elapsed"] for c in legacy["cars"]])

    def test_overtaking_ablation_fixes_difficulty_across_tracks(self):
        ablated = coef.ablate(coef.DEFAULT, "overtaking")
        hard = race_config(season([{"overtaking": 0.9}], ablated), ablated)["overtaking_difficulty"]
        easy = race_config(season([{"overtaking": 0.1}], ablated), ablated)["overtaking_difficulty"]
        self.assertEqual(hard, easy)

    def test_tyre_degradation_scales_lap_time(self):
        car = {"compound": "SOFT", "tyre_age": 10, "base_pace": 90.0}
        self.assertGreater(engine._segment_time(car, 1, 1.4), engine._segment_time(car, 1, 0.8))


class PublicInformationTests(unittest.TestCase):
    def test_observation_exposes_planning_inputs_without_hidden_state(self):
        obs = ChampionshipSession(base_seed=99).observation()
        self.assertIn("power_unit_stress", obs["championship"]["remaining_calendar"][-1])
        self.assertIn("projection_if_all_used", obs["controlled_drivers"]["Apex A"])
        self.assertIn("published_pace_estimate", obs["rivals_public"]["Orion A"])
        text = json.dumps(obs)
        for word in ("seed", "events", "dnf_uniform"):
            self.assertNotIn(word, text)
        self.assertNotIn("wear", json.dumps(obs["rivals_public"]))


class SolverCorrectnessTests(unittest.TestCase):
    def test_expected_finish_points_match_brute_force(self):
        race = engine.new_state(5, {"grid": list(engine.LEGACY_CAR_NAMES), "pace": engine.LEGACY_BASE_PACE,
                                    "dnf_prob": {n: 0.1 + 0.05 * i for i, n in enumerate(engine.LEGACY_CAR_NAMES)},
                                    "events": ["GREEN"] * 3})
        order = sorted(race["cars"], key=lambda c: (c["elapsed"], c["name"]))
        p = race["config"]["dnf_prob"]
        brute = 0.0
        for mask in itertools.product((0, 1), repeat=8):
            prob, rank, pts = 1.0, 0, 0
            for car, out in zip(order, mask):
                prob *= p[car["name"]] if out else 1 - p[car["name"]]
            for car, out in zip(order, mask):
                if not out:
                    if car["team"] == "Apex":
                        pts += engine.POINTS[rank]
                    rank += 1
            brute += prob * pts
        self.assertAlmostEqual(ts.expected_apex_points_at_finish(race), brute, places=9)

    def test_event_tree_expectation_matches_enumeration(self):
        state = season([{}])
        prepared = ts.prepare(state, ts.Solver().choose(state, "always_use"), coef.DEFAULT)
        race = ts.prepared_race_state(prepared, coef.DEFAULT)
        probs = dict(ts.EVENT_PROBS)
        brute = 0.0
        for events in itertools.product(probs, repeat=3):
            branch = ts._copy_race(race)
            branch["events"] = list(events)
            while branch["step"] < 3:
                engine.step(branch, ts.baseline_race_action(engine.observation(branch)))
            brute += probs[events[0]] * probs[events[1]] * probs[events[2]] * ts.expected_apex_points_at_finish(branch)
        self.assertAlmostEqual(ts.expected_race_value(race), brute, places=9)

    def test_final_race_greedy_equals_optimal(self):
        state = season([{"stress": 0.9}])
        set_wear(state, "Apex A", 0.8)
        solver = ts.Solver()
        self.assertAlmostEqual(solver.evaluate(state, "greedy"), solver.optimal(state)[0], places=9)

    def test_solver_realized_path_matches_live_session(self):
        state = season([{}, {"archetype": "street"}])
        solver = ts.Solver()
        session = ChampionshipSession(state=state, base_seed=4242)
        while session.decision_type != "CHAMPIONSHIP_COMPLETE":
            obs = session.observation()
            if obs["decision_type"] == "COMPONENT_DECISION":
                option = solver.choose(session.state, "rival_rule")
                session.submit({"type": "COMPONENT_DECISION", "decisions": [
                    {"driver": d, "component": c, "action": a} for d, c, a in option]})
            else:
                action = ts.baseline_race_action(obs["race_progress"])
                session.submit({"type": "RACE_STRATEGY", **action})
        self.assertEqual(session.state.team_points["Apex"], solver.realized(state, "rival_rule", 4242))


if __name__ == "__main__":
    unittest.main()
