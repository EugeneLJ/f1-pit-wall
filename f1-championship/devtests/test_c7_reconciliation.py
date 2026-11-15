import json
import unittest
from pathlib import Path

from analysis.c7_reconcile_counts import (
    historical_c6_class,
    raw_reversal,
    reconcile,
    uncertainty_separated,
    validated_class,
)


ROOT = Path(__file__).parents[1]
RESULT = ROOT / "analysis/results/c7/reconciliation.json"


def row(action_a="STAY/STAY", action_b="PIT_HARD/STAY", gap_a=2.0, gap_b=2.0,
        hash_a="a", hash_b="b"):
    return {"pair": {"condition_a": {"reference_action": action_a, "reference_gap": gap_a},
                     "condition_b": {"reference_action": action_b, "reference_gap": gap_b},
                     "public_evidence_diff": {"baseline_observation_hash": hash_a,
                                              "altered_observation_hash": hash_b}}}


class DefinitionTests(unittest.TestCase):
    def test_raw_reversal_is_not_confirmed_when_either_side_is_near_tie(self):
        candidate = row(gap_b=0.5)
        self.assertTrue(raw_reversal(candidate))
        self.assertFalse(uncertainty_separated(candidate))
        self.assertEqual(historical_c6_class(candidate), "REPORTED_REVERSAL")
        self.assertEqual(validated_class(candidate), "NEAR_TIE")

    def test_only_separated_action_change_is_validated_reversal(self):
        self.assertEqual(validated_class(row()), "VALIDATED_REVERSAL")
        self.assertEqual(validated_class(row(action_b="STAY/STAY")), "NO_CHANGE_CONTROL")

    def test_duplicate_rows_and_unique_public_pairs_are_separate_units(self):
        rows = [row(), row(), row(hash_a="c", hash_b="d")]
        report = reconcile(rows, sampled_states=1)
        self.assertEqual(report["validated_row_counts"]["VALIDATED_REVERSAL"], 3)
        self.assertEqual(report["validated_unique_pair_counts"]["VALIDATED_REVERSAL"], 2)


class FrozenResultTests(unittest.TestCase):
    def test_69_to_1_reconciliation_is_arithmetically_complete(self):
        report = json.loads(RESULT.read_text())
        cross = report["cross_table_rows"]
        self.assertEqual(sum(cross.values()), 431)
        self.assertEqual(cross["RAW_REVERSAL|NEAR_TIE"], 68)
        self.assertEqual(cross["RAW_REVERSAL|SEPARATED"], 1)
        self.assertEqual(report["historical_c6_row_counts"]["REPORTED_REVERSAL"], 69)
        self.assertEqual(report["validated_row_counts"]["VALIDATED_REVERSAL"], 1)
        self.assertEqual(report["validated_row_counts"]["NEAR_TIE"], 289)
        self.assertEqual(report["validated_row_counts"]["NO_CHANGE_CONTROL"], 141)


if __name__ == "__main__":
    unittest.main()
