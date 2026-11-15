import unittest

from analysis.c7_adaptive_expansion import aggregate, select_live


def row(pair_id, kind, a_hash, b_hash):
    reversal = kind == "VALIDATED_REVERSAL"
    near = kind == "NEAR_TIE"
    return {"pair": {"pair_id": pair_id,
                     "condition_a": {"reference_action": "STAY/STAY", "reference_gap": 0.1 if near else 2.0},
                     "condition_b": {"reference_action": "PIT_HARD/STAY" if reversal else "STAY/STAY",
                                     "reference_gap": 2.0},
                     "public_evidence_diff": {"baseline_observation_hash": a_hash,
                                              "altered_observation_hash": b_hash}}}


class ExpansionTests(unittest.TestCase):
    def test_aggregate_separates_rows_unique_pairs_and_class_conflicts(self):
        rows = [row("r1", "VALIDATED_REVERSAL", "a", "b"),
                row("r2", "VALIDATED_REVERSAL", "a", "b"),
                row("n1", "NEAR_TIE", "a", "b")]
        result = aggregate(rows)
        self.assertEqual(result["row_counts"]["VALIDATED_REVERSAL"], 2)
        self.assertEqual(result["unique_pair_counts"]["VALIDATED_REVERSAL"], 1)
        self.assertEqual(result["pairs_with_conflicting_reference_classes"], 1)

    def test_live_selection_requires_disjoint_public_prompts(self):
        rows = []
        for kind, count in (("VALIDATED_REVERSAL", 3), ("NO_CHANGE_CONTROL", 3), ("NEAR_TIE", 2)):
            for index in range(count):
                rows.append(row(f"{kind}-{index}", kind, f"{kind}-a-{index}", f"{kind}-b-{index}"))
        selected, blocker = select_live(rows, {"VALIDATED_REVERSAL": 3, "NO_CHANGE_CONTROL": 3, "NEAR_TIE": 2})
        self.assertIsNone(blocker)
        self.assertEqual(len(selected), 8)
        rows[1]["pair"]["public_evidence_diff"]["baseline_observation_hash"] = \
            rows[0]["pair"]["public_evidence_diff"]["baseline_observation_hash"]
        selected, blocker = select_live(rows, {"VALIDATED_REVERSAL": 3, "NO_CHANGE_CONTROL": 3, "NEAR_TIE": 2})
        self.assertFalse(selected)
        self.assertIn("VALIDATED_REVERSAL", blocker)


if __name__ == "__main__":
    unittest.main()
