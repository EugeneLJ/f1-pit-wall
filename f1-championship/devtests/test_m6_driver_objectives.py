import copy
import unittest

from track_c.driver_objectives import (
    SUPPORTED_ORDERS,
    compliance_probability,
    load_m6_config,
    public_compliance_observation,
    resolve_order_compliance,
    wdc_standings,
)


class M6DriverObjectivesTest(unittest.TestCase):
    def setUp(self):
        self.config = load_m6_config()
        self.points = {"Apex A": 120, "Apex B": 88, "Rival A": 105, "Rival B": 70}
        self.teams = {"Apex": ["Apex A", "Apex B"], "Rival": ["Rival A", "Rival B"]}

    def test_wdc_standings_teammate_gaps_and_horizon(self):
        result = wdc_standings(self.points, self.teams, 3)
        rows = {row["driver"]: row for row in result["drivers"]}
        self.assertEqual([row["driver"] for row in result["drivers"]],
                         ["Apex A", "Rival A", "Apex B", "Rival B"])
        self.assertEqual(rows["Apex A"]["gap_to_teammate"], 32)
        self.assertEqual(rows["Apex B"]["gap_to_teammate"], -32)
        self.assertEqual(result["races_remaining"], 3)

    def test_probability_bounds_and_public_dependencies(self):
        values = [compliance_probability(gap, remaining, order, self.config)
                  for gap in (-50, 0, 15, 100)
                  for remaining in (0, 1, 4, 8, 20)
                  for order in SUPPORTED_ORDERS]
        self.assertTrue(all(0.0 <= value <= 1.0 for value in values))
        early = compliance_probability(30, 8, "HOLD", self.config)
        late = compliance_probability(30, 1, "HOLD", self.config)
        small_gap = compliance_probability(5, 1, "HOLD", self.config)
        self.assertGreater(early, late)
        self.assertGreater(small_gap, late)

    def test_fixed_draw_is_deterministic_and_private(self):
        first = resolve_order_compliance("KEEP_ORDER", "Apex A", .4,
                                         enabled=True, seeded_draw=.39)
        second = resolve_order_compliance("KEEP_ORDER", "Apex A", .4,
                                          enabled=True, seeded_draw=.39)
        self.assertEqual(first, second)
        self.assertTrue(first["complied"])
        self.assertNotIn("seeded_draw", repr(first))

    def test_disabled_means_full_compliance_without_draw(self):
        result = resolve_order_compliance("REQUEST_GIVE_BACK", "Apex A", .2, enabled=False)
        self.assertTrue(result["complied"])
        self.assertEqual(result["effective_order"], "REQUEST_GIVE_BACK")
        self.assertEqual(result["compliance_probability"], 1.0)
        self.assertIsNone(result["event"])

    def test_decline_emits_structured_event_and_falls_back_to_race(self):
        result = resolve_order_compliance("REQUEST_GIVE_BACK", "Apex A", .25,
                                          enabled=True, seeded_draw=.6)
        self.assertFalse(result["complied"])
        self.assertEqual(result["effective_order"], "RACE")
        self.assertEqual(result["event"], {
            "type": "ORDER_DECLINED", "driver": "Apex A",
            "order": "REQUEST_GIVE_BACK", "effective_order": "RACE",
            "public_reason": "WDC_COMPLIANCE_PROFILE", "compliance_probability": .25,
        })

    def test_agent_visible_observation_has_no_draw_or_hidden_seed(self):
        standings = wdc_standings(self.points, self.teams, 1)
        observation = public_compliance_observation(standings, self.config, True)
        serialized = repr(observation).lower()
        self.assertNotIn("draw", serialized)
        self.assertNotIn("seed", serialized)
        self.assertEqual(observation["profile_inputs"],
                         ["public_gap_to_teammate", "public_races_remaining", "order"])

    def test_does_not_mutate_reward_or_constructors_inputs(self):
        external = {"constructors_points": {"Apex": 42}, "reward": .75}
        before = copy.deepcopy(external)
        standings = wdc_standings(self.points, self.teams, 2)
        public_compliance_observation(standings, self.config, True)
        resolve_order_compliance("HOLD", "Apex A", .5, enabled=True, seeded_draw=.1)
        self.assertEqual(external, before)

    def test_scope_rejects_unrelated_orders_and_fixture_is_provisional(self):
        self.assertEqual(self.config["data_status"],
                         "synthetic_provisional_not_fia_calibrated")
        with self.assertRaises(ValueError):
            compliance_probability(10, 2, "SWAP", self.config)
        with self.assertRaises(ValueError):
            resolve_order_compliance("RACE", "Apex A", .5, enabled=True, seeded_draw=.1)


if __name__ == "__main__":
    unittest.main()
