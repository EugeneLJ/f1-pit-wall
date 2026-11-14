import copy
import json
import os
import tempfile
import unittest
from pathlib import Path

from track_c.engineer_runtime import (
    DEFAULT_GEMINI_ENGINEER_MODEL,
    EngineerRuntimeHarness,
    GeminiEngineerProvider,
    ImmutableRecommendationStore,
    MockRuntimeProvider,
    build_runtime_record,
    format_runtime_observation,
    measure_engineer_usage,
    observation_hash,
    redact_secrets,
    run_provider_safely,
    validate_runtime_recommendation,
)


def chief_observation():
    return {
        "schema_version": 1,
        "decision_type": "RACE_STRATEGY",
        "current_track": {"track_id": "round_3", "tyre_degradation": 0.7},
        "race_progress": {
            "lap": 12,
            "laps_total": 20,
            "decision_index": 2,
            "decision_count": 3,
            "track_status": "GREEN",
            "drivers": {
                "driver_a": {
                    "position": 2, "compound": "SOFT", "tyre_age": 13,
                    "elapsed": 721.125, "component_wear": {"ice": 0.41},
                    "relative_pace": -0.12,
                },
                "driver_b": {
                    "position": 4, "compound": "MEDIUM", "tyre_age": 8,
                    "elapsed": 724.875, "component_wear": {"ice": 0.33},
                    "relative_pace": 0.08,
                },
            },
            "classification": [
                {"position": 1, "driver": "Orion A", "team": "Orion", "gap": 0.0},
                {"position": 2, "driver": "Apex A", "team": "Apex", "gap": 1.2},
                {"position": 3, "driver": "Vela A", "team": "Vela", "gap": 2.1},
                {"position": 4, "driver": "Apex B", "team": "Apex", "gap": 3.7},
            ],
            "legal_actions": ["PIT", "STAY"],
        },
        "team_context": {
            "public_instructions": ["optimize Constructors' points"],
            "public_commitments": [
                {"driver_id": "driver_a", "objective": "protect track position"},
                {"driver_id": "driver_b", "objective": "extend stint"},
            ],
        },
    }


class FakeTransport:
    def __init__(self, response_factory):
        self.response_factory = response_factory
        self.calls = []

    def generate(self, **kwargs):
        self.calls.append(kwargs)
        return self.response_factory(kwargs)


class ObservationAndSchemaTests(unittest.TestCase):
    def test_driver_local_observation_includes_allowed_driver_state_and_own_commitment(self):
        observation_a = format_runtime_observation(chief_observation(), "engineer_a")
        observation_b = format_runtime_observation(chief_observation(), "engineer_b")
        serialized_a = json.dumps(observation_a, sort_keys=True)
        serialized_b = json.dumps(observation_b, sort_keys=True)

        self.assertEqual(
            observation_a["race_context"]["assigned_driver_state"]["component_wear"]["ice"],
            0.41,
        )
        self.assertNotIn("724.875", serialized_a)
        self.assertNotIn("721.125", serialized_b)
        self.assertIn("protect track position", serialized_a)
        self.assertNotIn("extend stint", serialized_a)
        self.assertIn("extend stint", serialized_b)
        self.assertNotIn("protect track position", serialized_b)

    def test_mock_recommendation_is_structured_and_self_reported(self):
        observation = format_runtime_observation(chief_observation(), "engineer_a")
        recommendation = MockRuntimeProvider("engineer_a").recommend(observation)
        validated = validate_runtime_recommendation(
            recommendation, observation, "engineer_a"
        )
        self.assertEqual(validated["proposed_action"]["choice"], "PIT")
        self.assertEqual(validated["confidence"]["kind"], "self_reported")
        self.assertEqual(validated["observation_hash"], observation_hash(observation))

    def test_invented_telemetry_is_rejected_not_repaired(self):
        observation = format_runtime_observation(chief_observation(), "engineer_a")
        recommendation = MockRuntimeProvider("engineer_a").recommend(observation)
        recommendation["supporting_evidence"][0]["observed_value"] = 999
        with self.assertRaisesRegex(ValueError, "existing observation field"):
            validate_runtime_recommendation(recommendation, observation, "engineer_a")


class LiveAdapterTests(unittest.TestCase):
    def setUp(self):
        self.previous_google = os.environ.pop("GOOGLE_API_KEY", None)
        self.previous_gemini = os.environ.pop("GEMINI_API_KEY", None)

    def tearDown(self):
        os.environ.pop("GOOGLE_API_KEY", None)
        os.environ.pop("GEMINI_API_KEY", None)
        if self.previous_google is not None:
            os.environ["GOOGLE_API_KEY"] = self.previous_google
        if self.previous_gemini is not None:
            os.environ["GEMINI_API_KEY"] = self.previous_gemini

    def test_live_adapter_uses_env_secret_and_records_no_secret(self):
        observation = format_runtime_observation(chief_observation(), "engineer_a")

        def response(kwargs):
            recommendation = MockRuntimeProvider("engineer_a").recommend(observation)
            return {
                "text": json.dumps(recommendation),
                "model_revision": "test-revision",
                "usage": {"input_tokens": 20, "output_tokens": 40, "total_tokens": 60},
                "estimated_cost_usd": 0.001,
            }

        transport = FakeTransport(response)
        provider = GeminiEngineerProvider("engineer_a", transport=transport)
        os.environ["GEMINI_API_KEY"] = "unit-test-secret"
        record = run_provider_safely(provider, observation, source="LIVE_MODEL")

        self.assertEqual(record["status"], "VALID")
        self.assertEqual(record["runtime"]["model"], DEFAULT_GEMINI_ENGINEER_MODEL)
        self.assertEqual(transport.calls[0]["api_key"], "unit-test-secret")
        self.assertNotIn("unit-test-secret", json.dumps(record, sort_keys=True))
        self.assertEqual(record["runtime"]["usage"]["total_tokens"], 60)
        self.assertEqual(record["runtime"]["model_revision"], "test-revision")
        self.assertTrue(record["runtime"]["prompt_hash"])
        self.assertEqual(record["runtime"]["sampling"]["temperature"], 0.0)
        self.assertEqual(record["runtime"]["retries"], 0)
        self.assertEqual(record["runtime"]["estimated_cost_usd"], 0.001)
        # the model cannot compute SHA-256: the exact hash to echo is part of the prompt
        self.assertIn(observation_hash(observation), transport.calls[0]["prompt"])

    def test_missing_key_and_invalid_response_remain_invalid(self):
        observation = format_runtime_observation(chief_observation(), "engineer_a")
        missing_key = run_provider_safely(
            GeminiEngineerProvider("engineer_a", transport=FakeTransport(lambda _: {})),
            observation,
            source="LIVE_MODEL",
        )
        self.assertEqual(missing_key["source"], "INVALID")
        self.assertIsNone(missing_key["recommendation"])

        os.environ["GEMINI_API_KEY"] = "unit-test-secret"
        invalid = run_provider_safely(
            GeminiEngineerProvider(
                "engineer_a",
                transport=FakeTransport(lambda _: {"text": "not-json"}),
            ),
            observation,
            source="LIVE_MODEL",
        )
        self.assertEqual(invalid["status"], "INVALID")
        self.assertIsNone(invalid["recommendation"])
        self.assertIn("JSONDecodeError", invalid["runtime"]["error_detail"])
        self.assertNotIn("unit-test-secret", json.dumps(invalid))

    def test_secret_redaction_is_recursive(self):
        value = redact_secrets({
            "api_key": "one", "nested": {"authorization": "two"},
            "safe": "visible",
        })
        self.assertEqual(value["api_key"], "[REDACTED]")
        self.assertEqual(value["nested"]["authorization"], "[REDACTED]")
        self.assertEqual(value["safe"], "visible")


class StoreReplayAndUsageTests(unittest.TestCase):
    def test_append_only_store_replays_exact_observation_and_detects_tampering(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "recommendations.jsonl"
            store = ImmutableRecommendationStore(path)
            observation = format_runtime_observation(chief_observation(), "engineer_a")
            recommendation = MockRuntimeProvider("engineer_a").recommend(observation)
            record = build_runtime_record(
                engineer_id="engineer_a", observation=observation, source="MOCK",
                recommendation=recommendation,
            )
            stored = store.append(record)
            replay = store.replay("engineer_a", observation)
            self.assertEqual(replay["source"], "RECORDED_REPLAY")
            self.assertEqual(replay["recommendation"], stored["recommendation"])

            changed = copy.deepcopy(observation)
            changed["race_context"]["assigned_driver_state"]["tyre_age"] += 1
            with self.assertRaises(KeyError):
                store.replay("engineer_a", changed)

            text = path.read_text(encoding="utf-8")
            path.write_text(text.replace('"status": "VALID"', '"status": "INVALID"'), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "chain"):
                store.read_all()

    def test_replay_condition_does_not_synthesize_missing_record(self):
        with tempfile.TemporaryDirectory() as directory:
            store = ImmutableRecommendationStore(Path(directory) / "records.jsonl")
            harness = EngineerRuntimeHarness(store=store)
            with self.assertRaises(KeyError):
                harness.collect(chief_observation(), "RECORDED_RECOMMENDATIONS")

    def test_usage_does_not_infer_ignored_from_missing_reference(self):
        with tempfile.TemporaryDirectory() as directory:
            store = ImmutableRecommendationStore(Path(directory) / "records.jsonl")
            harness = EngineerRuntimeHarness(store=store)
            records = harness.collect(chief_observation(), "NOMINAL_CONFIDENCE_CONTROL")
            hashes = {record["record_hash"] for record in records}
            metrics = measure_engineer_usage(
                records,
                delivered_record_hashes=hashes,
                explicitly_referenced_record_hashes=set(),
                chief_action={"driver_a": "PIT", "driver_b": "STAY"},
                outcome={"deterministic_points_regret": 0},
            )
            self.assertTrue(all(item["delivered_to_chief"] for item in metrics))
            self.assertTrue(all(not item["explicitly_referenced_or_consumed"] for item in metrics))
            self.assertTrue(all(
                item["consumption_observability"] == "not_observed_do_not_infer_ignored"
                for item in metrics
            ))
            self.assertTrue(all(item["chief_action_matches"] for item in metrics))

    def test_harness_conditions_preserve_chief_only_and_confidence_controls(self):
        harness = EngineerRuntimeHarness()
        self.assertEqual(harness.collect(chief_observation(), "CHIEF_ONLY"), [])
        nominal = harness.collect(chief_observation(), "NOMINAL_CONFIDENCE_CONTROL")
        high = harness.collect(
            chief_observation(), "HIGH_SELF_REPORTED_CONFIDENCE_CONTROL"
        )
        self.assertEqual(len(nominal), 2)
        self.assertTrue(all(
            item["recommendation"]["confidence"]["value"] == 0.7 for item in nominal
        ))
        self.assertTrue(all(
            item["recommendation"]["confidence"]["value"] == 0.95 for item in high
        ))
        self.assertTrue(all(
            item["runtime"]["confidence_condition"] == "high_self_reported_uncalibrated"
            for item in high
        ))
        conflicting = harness.collect(
            chief_observation(), "CONFLICTING_LOCAL_RECOMMENDATIONS"
        )
        self.assertEqual(
            [item["recommendation"]["proposed_action"]["choice"] for item in conflicting],
            ["PIT", "STAY"],
        )

    def test_harness_replays_two_exact_records(self):
        with tempfile.TemporaryDirectory() as directory:
            store = ImmutableRecommendationStore(Path(directory) / "records.jsonl")
            recording = EngineerRuntimeHarness(store=store)
            original = recording.collect(chief_observation(), "NOMINAL_CONFIDENCE_CONTROL")
            replayed = recording.collect(chief_observation(), "RECORDED_RECOMMENDATIONS")
            self.assertEqual(len(replayed), 2)
            self.assertTrue(all(item["source"] == "RECORDED_REPLAY" for item in replayed))
            self.assertEqual(
                [item["recommendation"] for item in replayed],
                [item["recommendation"] for item in original],
            )


if __name__ == "__main__":
    unittest.main()
