import copy
import unittest

from v22_helpers import assert_no_secrets
from track_c.v22 import V22Config
from track_c.v22 import rival_tendencies as m2
from track_c.v22.common import reject_public_secrets


def context(**updates):
    base = {"car": "Rival 1", "m3_active": False, "defence_applicable": False,
            "attack_legal": True, "gap_ahead": None, "lap_index": 0}
    base.update(updates)
    return base


def values(stay, pit, se=0.0):
    return {
        "STAY": {kind: {"mean": stay[kind], "se": se} for kind in stay},
        "PIT_HARD": {kind: {"mean": pit[kind], "se": se} for kind in pit},
    }


class M2TypeAndEvidenceTests(unittest.TestCase):
    def test_per_race_draw_is_exact_stable_and_action_independent(self):
        model = m2.load_model()
        assignments = {car: m2.draw_tendency(1234, "race-0", car, model)
                       for car in ("R1", "R2", "R3", "R4")}
        for _ in range(12):
            for car, expected in assignments.items():
                self.assertEqual(m2.draw_tendency(1234, "race-0", car, model), expected)
        races = {m2.draw_tendency(seed, "race-0", "R1", model) for seed in range(64)}
        self.assertGreater(len(races), 1, "independent keys need not make every assignment distinct")
        self.assertFalse(V22Config().m2_enabled)

    def test_literal_reaction_table_and_threshold_equality(self):
        model = m2.load_model()
        m = "DEFENDER"
        self.assertEqual(m2.reaction(m, context(defence_applicable=True, attack_legal=True), model), "DEFEND")
        self.assertEqual(m2.reaction("OPPORTUNIST", context(m3_active=False), model), "INHERIT_BASELINE")
        self.assertEqual(m2.reaction("OPPORTUNIST", context(m3_active=True), model), "ATTACK")
        self.assertEqual(m2.reaction("OPPORTUNIST", context(m3_active=True, attack_legal=False), model), "INHERIT_BASELINE")
        self.assertEqual(m2.reaction("CONSERVATIVE", context(gap_ahead=1.01, m3_active=True), model), "NO_ATTACK")
        self.assertEqual(m2.reaction("CONSERVATIVE", context(gap_ahead=1.0, m3_active=True), model), "INHERIT_BASELINE")
        self.assertEqual(m2.reaction("CONSERVATIVE", context(gap_ahead=None, m3_active=True), model), "INHERIT_BASELINE")

    def test_public_event_and_posterior_replay_are_joint_not_direct_type_lookup(self):
        event = m2.observable_lap(22, "race-0", "OPPORTUNIST", context(m3_active=True))
        replay = m2.observable_lap(22, "race-0", "OPPORTUNIST", context(m3_active=True))
        next_event = m2.observable_lap(22, "race-0", "OPPORTUNIST", context(m3_active=True, lap_index=1))
        self.assertEqual(event, replay)
        self.assertNotIn("tendency", event)
        model = m2.load_model()
        prior = {kind: model["prior"][kind]["value"] for kind in model["types"]}
        belief = m2.posterior(prior, [event, next_event], model)
        self.assertAlmostEqual(sum(belief.values()), 1.0)
        self.assertGreater(belief["OPPORTUNIST"], belief["DEFENDER"])
        projection = m2.public_projection(prior, [event], model)
        self.assertEqual(projection["interpretation"].split(" ")[0], "derived")
        assert_no_secrets(self, projection)
        earlier = m2.posterior(prior, [event], model)
        later = m2.posterior(prior, [event, next_event], model)
        self.assertEqual(earlier, m2.posterior(prior, [event], model))
        self.assertNotEqual(earlier, later)

    def test_duplicate_event_and_private_projection_content_fail_closed(self):
        model = m2.load_model()
        event = m2.observable_lap(22, "race-0", "DEFENDER", context(defence_applicable=True))
        with self.assertRaisesRegex(ValueError, "duplicate"):
            m2.posterior({kind: model["prior"][kind]["value"] for kind in model["types"]}, [event, event], model)
        with self.assertRaisesRegex(ValueError, "private"):
            reject_public_secrets({"tendency_assignment": "DEFENDER"})
        self.assertEqual(m2.disabled_projection(), {"schema_version": 1, "m2_enabled": False, "effects": "none"})

    def test_reaction_sensor_uses_published_confusion_not_direct_assignment(self):
        events = [m2.observable_lap(seed, "sensor", "DEFENDER",
                                    context(defence_applicable=True, lap_index=seed)) for seed in range(80)]
        # Determinism is preserved while observation, not type, drives this row.
        self.assertTrue(all(event["lap_index"] == seed for seed, event in enumerate(events)))
        self.assertEqual(events, [m2.observable_lap(seed, "sensor", "DEFENDER",
                                                    context(defence_applicable=True, lap_index=seed))
                                  for seed in range(80)])
        self.assertLess(sum(event["observed_reaction"] != "DEFEND" for event in events), 30)

    def test_behavior_and_residual_differ_with_hidden_tendency(self):
        defender = m2.observable_lap(88, "race-0", "DEFENDER", context(m3_active=True, defence_applicable=True))
        opportunist = m2.observable_lap(88, "race-0", "OPPORTUNIST", context(m3_active=True, defence_applicable=True))
        self.assertNotEqual(defender["lap_residual"], opportunist["lap_residual"])
        for event in (defender, opportunist):
            self.assertIn(event["observed_reaction"], m2.REACTIONS)


class M2DecisionReferenceTests(unittest.TestCase):
    def test_type_specific_legal_values_change_optimal_action_not_only_behavior(self):
        stay = {"DEFENDER": 10.0, "OPPORTUNIST": 0.0, "CONSERVATIVE": 5.0}
        pit = {"DEFENDER": 0.0, "OPPORTUNIST": 10.0, "CONSERVATIVE": 5.0}
        map_values = values(stay, pit)
        dominant_defender = m2.expected_values(
            {"DEFENDER": 0.98, "OPPORTUNIST": 0.01, "CONSERVATIVE": 0.01}, map_values)
        dominant_opportunist = m2.expected_values(
            {"DEFENDER": 0.01, "OPPORTUNIST": 0.98, "CONSERVATIVE": 0.01}, map_values)
        self.assertEqual(dominant_defender["chosen_action"], "STAY")
        self.assertEqual(dominant_opportunist["chosen_action"], "PIT_HARD")
        self.assertEqual(dominant_defender["classification"], "SEPARATED")
        self.assertEqual(dominant_opportunist["classification"], "SEPARATED")

    def test_near_tie_then_uncertainty_precedes_a_reversal_claim(self):
        stay = {"DEFENDER": 5.0, "OPPORTUNIST": 5.0, "CONSERVATIVE": 5.0}
        slightly_better = {kind: value + 0.5 for kind, value in stay.items()}
        near = m2.expected_values(
            {"DEFENDER": 1.0, "OPPORTUNIST": 0.0, "CONSERVATIVE": 0.0},
            values(stay, slightly_better))
        self.assertEqual(near["classification"], "NEAR_TIE")
        larger_gap = {kind: value + 2.0 for kind, value in stay.items()}
        uncertain = m2.expected_values(
            {"DEFENDER": 1.0, "OPPORTUNIST": 0.0, "CONSERVATIVE": 0.0},
            values(stay, larger_gap, se=10.0))
        self.assertEqual(uncertain["classification"], "UNCERTAIN")
        separated = m2.expected_values(
            {"DEFENDER": 1.0, "OPPORTUNIST": 0.0, "CONSERVATIVE": 0.0},
            values(stay, larger_gap, se=0.1))
        self.assertEqual(separated["classification"], "SEPARATED")
        self.assertNotEqual(uncertain["chosen_action"], "STAY")

    def test_no_change_control_and_value_validation(self):
        stable = {kind: 5.0 for kind in m2.load_model()["types"]}
        result = m2.expected_values(
            {"DEFENDER": 0.2, "OPPORTUNIST": 0.7, "CONSERVATIVE": 0.1}, values(stable, stable))
        self.assertEqual(result["classification"], "NEAR_TIE")
        self.assertEqual(result["estimated_difference"], 0.0)
        with self.assertRaises(ValueError):
            m2.expected_values({"DEFENDER": 0.2, "OPPORTUNIST": 0.7, "CONSERVATIVE": 0.1},
                               {"STAY": {"DEFENDER": {"mean": 1.0, "se": 0.0}}})
        with self.assertRaises(ValueError):
            m2.expected_values({"DEFENDER": 0.2, "OPPORTUNIST": 0.7, "CONSERVATIVE": 0.1}, {})


if __name__ == "__main__":
    unittest.main()
