"""B4 tests: SC/VSC state model (frequency, duration, cooldown), effects, public information."""

from __future__ import annotations

import json
import random
import sys
import unittest
from collections import Counter
from pathlib import Path

TASK = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TASK / "src"))

from f1pitwall import coefficients as coef  # noqa: E402
from f1pitwall import engine  # noqa: E402
from f1pitwall.championship_contract import ChampionshipSession  # noqa: E402

MODEL = coef.race_format(coef.DEFAULT)["neutralization"]
N = len(coef.race_format(coef.DEFAULT)["decision_laps"])
STAY = {"driver_a": "STAY", "driver_b": "STAY"}


def episodes(schedule):
    """[(status, duration, start_index)] for one schedule."""
    out, i = [], 0
    while i < len(schedule):
        if schedule[i] == "GREEN":
            i += 1
            continue
        j = i
        while j < len(schedule) and schedule[j] == schedule[i]:
            j += 1
        out.append((schedule[i], j - i, i))
        i = j
    return out


def race(events, coeffs=coef.DEFAULT):
    fmt = coef.race_format(coeffs)
    config = {"grid": list(engine.LEGACY_CAR_NAMES), "pace": dict(engine.LEGACY_BASE_PACE),
              "overtaking": coeffs["track_performance"]["overtaking"], "overtaking_difficulty": 0.5,
              "tyres": coef.tyre_model(coeffs), "pit": coef.pit_model("mixed", coeffs), **fmt,
              "events": list(events)}
    return engine.new_state(9, config)


def gaps(state):
    order = sorted(state["cars"], key=lambda c: (c["elapsed"], c["name"]))
    return [b["elapsed"] - a["elapsed"] for a, b in zip(order, order[1:])], [c["name"] for c in order]


class ScheduleDistributionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.schedules = [engine.neutralization_schedule(seed, N, MODEL) for seed in range(6000)]

    def test_deterministic_and_action_independent(self):
        self.assertEqual(engine.neutralization_schedule(42, N, MODEL), engine.neutralization_schedule(42, N, MODEL))
        state = race(["GREEN"] * N)
        self.assertEqual(len(state["events"]), N)

    def test_start_rate_matches_model_per_eligible_decision(self):
        starts, eligible = Counter(), 0
        for schedule in self.schedules:
            cooldown, i = 0, 0
            prev = "GREEN"
            for i, status in enumerate(schedule):
                if prev == "GREEN" and cooldown == 0:
                    eligible += 1
                    if status != "GREEN":
                        starts[status] += 1
                if prev != "GREEN" and status == "GREEN":
                    cooldown = MODEL["cooldown"]
                elif status == "GREEN" and cooldown:
                    cooldown -= 1
                if status != "GREEN" and prev == status:
                    pass
                prev = status
        for status in ("SC", "VSC"):
            self.assertAlmostEqual(starts[status] / eligible, MODEL["start"][status], delta=0.004)

    def test_duration_distribution_matches_model(self):
        counts = {"SC": Counter(), "VSC": Counter()}
        for schedule in self.schedules:
            for status, duration, start in episodes(schedule):
                if start + duration < N:  # uncensored (did not run into the end of the race)
                    counts[status][duration] += 1
        for status in ("SC", "VSC"):
            total = sum(counts[status].values())
            self.assertGreater(total, 1000)
            for duration, p in MODEL["duration"][status].items():
                self.assertAlmostEqual(counts[status][duration] / total, p, delta=0.04, msg=f"{status} {duration}")

    def test_cooldown_separates_neutralizations(self):
        for schedule in self.schedules:
            eps = episodes(schedule)
            for (_, d1, s1), (_, _, s2) in zip(eps, eps[1:]):
                self.assertGreaterEqual(s2 - (s1 + d1), MODEL["cooldown"])

    def test_per_race_rates_are_plausible(self):
        sc = sum(sum(1 for e in episodes(s) if e[0] == "SC") for s in self.schedules) / len(self.schedules)
        vsc = sum(sum(1 for e in episodes(s) if e[0] == "VSC") for s in self.schedules) / len(self.schedules)
        self.assertTrue(0.25 < sc < 0.7, sc)
        self.assertTrue(0.25 < vsc < 0.7, vsc)


class ConditionalFutureTests(unittest.TestCase):
    def test_futures_respect_observed_neutralization_and_duration_tail(self):
        state = race(["GREEN", "SC"] + ["GREEN"] * (N - 2))
        engine.step(state, STAY)  # now at decision 2, SC with 1 segment so far
        futures = engine.sample_future_statuses(random.Random(1), state, 20000)
        cont = sum(f[0] == "SC" for f in futures) / len(futures)
        table = MODEL["duration"]["SC"]
        self.assertAlmostEqual(cont, (table[2] + table[3]) / sum(table.values()), delta=0.015)
        for f in futures:
            if f[0] == "GREEN":
                self.assertEqual(f[:MODEL["cooldown"]], ["GREEN"] * MODEL["cooldown"])  # cooldown after the SC ends
            self.assertLessEqual(sum(1 for s in [ "SC" ] + f[:2] if s == "SC"), 3)

    def test_futures_ignore_the_true_schedule(self):
        a = race(["GREEN"] * N)
        b = race(["GREEN"] + ["SC"] * 3 + ["GREEN"] * (N - 4))
        fa = engine.sample_future_statuses(random.Random(5), a, 50)
        fb = engine.sample_future_statuses(random.Random(5), b, 50)
        self.assertEqual(fa, fb)  # same observed history (one GREEN) -> same futures


class EffectTests(unittest.TestCase):
    def test_sc_compresses_gaps_keeps_order_and_slows_tyre_ageing(self):
        state = race(["SC"] + ["GREEN"] * (N - 1))
        _, before_order = gaps(state)
        age = {c["name"]: c["tyre_age"] for c in state["cars"]}
        engine.step(state, STAY)
        after, after_order = gaps(state)
        self.assertEqual(before_order, after_order)
        self.assertTrue(all(g <= MODEL["sc_gap"] + 1e-9 for g in after))
        self.assertTrue(all(c["tyre_age"] - age[c["name"]] == MODEL["tyre_age_laps"]["SC"] for c in state["cars"]))

    def test_vsc_preserves_gaps(self):
        state = race(["VSC"] + ["GREEN"] * (N - 1))
        before, order = gaps(state)
        engine.step(state, STAY)
        after, order_after = gaps(state)
        self.assertEqual(order, order_after)
        for g0, g1 in zip(before, after):
            self.assertAlmostEqual(g0, g1, places=9)

    def test_pit_is_cheaper_in_time_under_neutralization(self):
        def cost(status):
            stay, pit = race([status] + ["GREEN"] * (N - 1)), race([status] + ["GREEN"] * (N - 1))
            engine.step(stay, STAY)
            engine.step(pit, {"driver_a": "STAY", "driver_b": "PIT_HARD"})
            car = lambda s: next(c for c in s["cars"] if c["name"] == "Apex B")  # noqa: E731
            return car(pit)["elapsed"] - car(stay)["elapsed"]
        self.assertLess(cost("SC"), cost("VSC"))
        self.assertLess(cost("VSC"), cost("GREEN"))

    def test_a_stop_under_sc_costs_track_position_in_the_compressed_train(self):
        """Structural check only. Whether an SC stop pays off is measured by the B4 analysis
        (an always-pit-under-SC policy is evaluated there), not asserted here."""
        events = ["SC"] + ["GREEN"] * (N - 1)
        stay, pit = race(events), race(events)
        engine.step(stay, STAY)
        engine.step(pit, {"driver_a": "STAY", "driver_b": "PIT_HARD"})
        position = lambda s: gaps(s)[1].index("Apex B")  # noqa: E731
        self.assertGreater(position(pit), position(stay))
        tail = gaps(pit)[0]
        self.assertTrue(all(g <= MODEL["sc_gap"] + 1e-9 for g in tail))

    def test_ablation_restores_b3_independent_events(self):
        ablated = coef.ablate(coef.DEFAULT, "neutralization_dynamics")
        self.assertIsNone(coef.race_format(ablated)["neutralization"])
        state = race(["SC"] + ["GREEN"] * (N - 1), ablated)
        before, _ = gaps(state)
        engine.step(state, STAY)
        after, _ = gaps(state)
        self.assertNotEqual([round(g, 3) for g in after], [round(min(g, MODEL["sc_gap"]), 3) for g in before])


class PublicInformationTests(unittest.TestCase):
    def test_observation_shows_status_and_elapsed_but_not_remaining_or_future(self):
        session = ChampionshipSession(base_seed=77)
        obs = session.observation()
        decisions = [{"driver": d, "component": c, "action": "USE"}
                     for d, s in obs["controlled_drivers"].items() for c in s["components"]]
        obs = session.submit({"type": "COMPONENT_DECISION", "decisions": decisions})["race_progress"]
        self.assertIn("neutralization", obs)
        self.assertEqual(set(obs["neutralization"]), {"status", "segments_so_far"})
        self.assertIn("event_model", obs)
        text = json.dumps(session.observation())
        for word in ('"events"', "remaining_duration", "seed", "future_track_status"):
            self.assertNotIn(word, text)


if __name__ == "__main__":
    unittest.main()
