"""B3 level (a) tests: long race format (decision count, laps, grid, tyres, event odds)."""

from __future__ import annotations

import sys
import unittest
from collections import Counter
from pathlib import Path

TASK = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TASK / "src"))

from f1pitwall import coefficients as coef  # noqa: E402
from f1pitwall import engine  # noqa: E402
from f1pitwall.championship_contract import ChampionshipSession  # noqa: E402


def first_race(coeffs=coef.DEFAULT, seed=11):
    session = ChampionshipSession(base_seed=seed, coeffs=coeffs)
    obs = session.observation()
    decisions = [{"driver": d, "component": c, "action": "USE"}
                 for d, s in obs["controlled_drivers"].items() for c in s["components"]]
    session.submit({"type": "COMPONENT_DECISION", "decisions": decisions})
    return session


class RaceFormatTests(unittest.TestCase):
    def test_long_format_has_14_decisions_over_45_laps(self):
        race = first_race()._active_race.race_state
        self.assertEqual(engine._decision_laps(race), list(range(3, 43, 3)))
        self.assertEqual(engine.laps_total(race), 45)
        self.assertEqual(engine.segment_laps(race), 3)
        self.assertTrue(13 <= len(race["events"]) <= 18)

    def test_start_grid_and_tyres_follow_the_format(self):
        race = first_race()._active_race.race_state
        self.assertEqual({car["tyre_age"] for car in race["cars"]}, {3})
        gaps = sorted(car["elapsed"] for car in race["cars"])
        self.assertAlmostEqual(gaps[-1] - gaps[0], (engine.GRID_ELAPSED_SLOTS[-1] - engine.GRID_ELAPSED_SLOTS[0]) * 0.4,
                               delta=0.5)

    def test_event_schedule_follows_published_odds(self):
        probs = coef.race_format(coef.DEFAULT)["event_probs"]
        counts = Counter(e for seed in range(4000) for e in engine._event_schedule(seed, 14, probs))
        total = sum(counts.values())
        for status, p in probs.items():
            self.assertAlmostEqual(counts[status] / total, p, delta=0.01)
        sc_per_race = counts["SC"] / 4000
        self.assertTrue(0.3 < sc_per_race < 0.9)

    def test_short_format_ablation_reproduces_legacy_decision_laps(self):
        race = first_race(coef.ablate(coef.DEFAULT, "long_race_format"))._active_race.race_state
        self.assertEqual(engine._decision_laps(race), list(engine.DECISION_LAPS))
        self.assertEqual(engine.segment_laps(race), engine.SEGMENT_LENGTH)
        self.assertEqual(engine.event_probabilities(race), engine.LEGACY_EVENT_PROBS)

    def test_observation_publishes_odds_life_and_progress(self):
        obs = first_race().observation()["race_progress"]
        self.assertEqual(obs["event_probabilities_per_decision"], coef.race_format(coef.DEFAULT)["event_probs"])
        self.assertEqual(obs["tyre_life_laps"], {"SOFT": 10, "MEDIUM": 16, "HARD": 24})
        self.assertEqual((obs["decision_index"], obs["decision_count"], obs["laps_remaining"]), (1, 14, 42))

    def test_full_long_season_has_120_decisions(self):
        sys.path.insert(0, str(TASK / "solution"))
        from play import component_action, race_action
        session = ChampionshipSession(base_seed=3)
        count = 0
        while session.decision_type != "CHAMPIONSHIP_COMPLETE":
            obs = session.observation()
            session.submit(component_action(obs) if obs["decision_type"] == "COMPONENT_DECISION" else race_action(obs))
            count += 1
        self.assertEqual(count, 8 * 15)


if __name__ == "__main__":
    unittest.main()
