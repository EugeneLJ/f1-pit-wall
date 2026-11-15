"""Runtime axes for the 2.2.0 candidate: engineers x rival, with fake providers (no network)."""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

TASK = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(TASK / "src"), str(TASK)]

from f1pitwall.integrated import config as C  # noqa: E402
from f1pitwall.integrated import policies as P  # noqa: E402
from f1pitwall.integrated import providers as PR  # noqa: E402
from f1pitwall.integrated import runtime as R  # noqa: E402
from track_c.engineer_runtime import MockRuntimeProvider  # noqa: E402

SEED = 11


class FakeEngineers:
    """Returns a valid structured recommendation for the exact driver-local observation in the prompt."""

    def __init__(self):
        self.calls = 0

    def generate(self, *, prompt, **kw):
        self.calls += 1
        eid = "engineer_a" if "You are engineer_a" in prompt else "engineer_b"
        obs = json.loads(prompt.split("OBSERVATION=", 1)[1])
        rec = MockRuntimeProvider(eid).recommend(obs)
        return {"text": json.dumps(rec), "model_revision": "fake-lite", "usage": {"input_tokens": 500, "output_tokens": 80}}


class FakeChief:
    """A chat transport that answers with the published scripted policy for the observation it was given."""

    def __init__(self, name="baseline", model="fake-model"):
        self.policy, self.model, self.calls = P.scripted(name), model, 0

    def complete(self, *, prompt, **kw):
        self.calls += 1
        obs = json.loads(prompt.split("OBSERVATION=", 1)[1])
        if obs["decision_type"] == "PRACTICE":
            action = {"type": "PRACTICE", "driver_a": {"program": "QUALI_SIM", "setup_id": "low_drag", "laps": 4},
                      "driver_b": {"program": "LONG_RUN", "setup_id": "high_downforce", "laps": 4}}
        elif obs["decision_type"] == "QUALIFYING":
            action = {"type": "QUALIFYING", "driver_a": {"setup_id": "high_downforce", "run_plan": "TWO_RUN"},
                      "driver_b": {"setup_id": "high_downforce", "run_plan": "TWO_RUN"}}
        else:
            action = self.policy(obs)
        return {"text": json.dumps(action), "model": self.model, "request_id": f"r{self.calls}", "status": 200,
                "usage": {"input_tokens": 2000, "output_tokens": 100}}


class RuntimeAxes(unittest.TestCase):
    def setUp(self):
        os.environ["RT_TEST_GEMINI"] = "fake-gemini-key"
        os.environ["RT_TEST_VERDA"] = "fake-verda-key"
        os.environ["GEMINI_API_KEY"] = os.environ.get("GEMINI_API_KEY", "fake-engineer-key")
        self.tmp = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.tmp.cleanup()

    def run_spec(self, spec, max_ticks=None, **kw):
        kw.setdefault("chief_transport", FakeChief())
        return R.run(spec, SEED, Path(self.tmp.name) / spec.label().replace("|", "_"), PR.CostGuard(5.0),
                     max_ticks=max_ticks, chief_key_env="RT_TEST_GEMINI", rival_key_env="RT_TEST_VERDA", **kw)

    def test_config_matrix(self):
        expected = {("CHIEF_ONLY", "SCRIPTED"): (C.SOLO_COORDINATION, 1, "ADAPTIVE"),
                    ("GEMINI_LITE_ENGINEERS", "SCRIPTED"): (C.SOLO_COORDINATION, 1, "ADAPTIVE"),
                    ("CHIEF_ONLY", "ADAPTIVE_LLM"): (C.TWO_TEAM_COMPETITION, 2, "ADAPTIVE"),
                    ("GEMINI_LITE_ENGINEERS", "ADAPTIVE_LLM"): (C.TWO_TEAM_COMPETITION, 2, "ADAPTIVE"),
                    ("CHIEF_ONLY", "FIXED_REPLAY"): (C.TWO_TEAM_COMPETITION, 2, "FIXED_REPLAY")}
        for (eng, rival), (mode, teams, cond) in expected.items():
            for c5 in (False, True):
                spec = R.RuntimeSpec(eng, rival, c5_weekend=c5, replay_journal="x" if rival == "FIXED_REPLAY" else None)
                cfg = R.build_config(spec)
                self.assertEqual((cfg.mode, len(cfg.teams), cfg.rival_condition), (mode, teams, cond))
                self.assertEqual(cfg.teams[0].engineers, eng)
                self.assertEqual((cfg.benchmark_version, cfg.c5_weekend), ("2.2.0", c5))
        with self.assertRaises(ValueError):
            R.RuntimeSpec("CHIEF_ONLY", "FIXED_REPLAY").validate()
        with self.assertRaises(ValueError):
            R.RuntimeSpec("SOMETHING", "SCRIPTED").validate()

    def test_scripted_rival_full_season_with_c5_replays(self):
        out = self.run_spec(R.RuntimeSpec(c5_weekend=True))
        self.assertTrue(out["complete"])
        self.assertTrue(out["replay"]["ok"], out["replay"])
        self.assertEqual(out["replay"]["resolved_ticks"], 144)
        self.assertEqual(out["provenance_status"]["Apex"], {"SUBMITTED": 144})

    def test_live_engineers_reach_the_chief_and_replay_exactly(self):
        fake = FakeEngineers()
        out = self.run_spec(R.RuntimeSpec("GEMINI_LITE_ENGINEERS", "SCRIPTED", c5_weekend=True), max_ticks=8,
                            engineer_transport=fake)
        self.assertTrue(out["replay"]["ok"], out["replay"])
        race_ticks = [e for e in out["journal"] if e["kind"] == "resolved" and e["decision_type"] == "RACE_STRATEGY"]
        self.assertTrue(race_ticks and all(len(e["engineer_record_hashes"]["Apex"]) == 2 for e in race_ticks))
        weekend = [e for e in out["journal"] if e.get("decision_type") in ("PRACTICE", "QUALIFYING")]
        self.assertTrue(all(e["engineer_record_hashes"] == {} for e in weekend))  # reports only on race ticks
        # reports are collected when a race tick opens; the tick open at the limit was never resolved
        self.assertEqual(fake.calls, 2 * (len(race_ticks) + 1))

    def test_adaptive_llm_rival_two_teams_and_isolation(self):
        rival = FakeChief("long_stint", model="fake-deepseek")
        out = self.run_spec(R.RuntimeSpec("CHIEF_ONLY", "ADAPTIVE_LLM", c5_weekend=True), max_ticks=10,
                            rival_transport=rival)
        self.assertTrue(out["replay"]["ok"], out["replay"])
        self.assertEqual(out["rival_condition"], "ADAPTIVE")
        self.assertEqual(set(out["provenance_status"]), {"McLearn Racing", "Red Bool Racing"})
        self.assertGreater(rival.calls, 0)
        with self.assertRaises(ValueError):  # same credential variable for both Chiefs is refused
            R.build_runtime(R.RuntimeSpec("CHIEF_ONLY", "ADAPTIVE_LLM"), Path(self.tmp.name), PR.CostGuard(1.0),
                            chief_transport=FakeChief(), rival_transport=FakeChief(),
                            chief_key_env="RT_TEST_GEMINI", rival_key_env="RT_TEST_GEMINI")

    def test_fixed_replay_rival_reuses_a_recorded_journal(self):
        live = self.run_spec(R.RuntimeSpec("CHIEF_ONLY", "ADAPTIVE_LLM"), max_ticks=20, rival_transport=FakeChief("long_stint"))
        path = Path(self.tmp.name) / "rival_journal.jsonl"
        path.write_text("".join(json.dumps(e) + "\n" for e in live["journal"]))
        fixed = self.run_spec(R.RuntimeSpec("CHIEF_ONLY", "FIXED_REPLAY", replay_journal=str(path)), max_ticks=20)
        self.assertTrue(fixed["replay"]["ok"], fixed["replay"])
        self.assertEqual(fixed["rival_condition"], "FIXED_REPLAY")
        self.assertNotEqual(fixed["config_hash"], live["config_hash"])  # different estimand label
        same = [a["submissions"]["Red Bool Racing"]["action"] == b["submissions"]["Red Bool Racing"]["action"]
                for a, b in zip(live["journal"], fixed["journal"]) if a["kind"] == b["kind"] == "resolved"]
        self.assertTrue(all(same))  # same Chief behaviour on the same seed -> identical replayed actions

    def test_provider_failure_falls_back_and_replays(self):
        class Down:
            def complete(self, **kw):
                raise PR.ProviderError("http_error", 503)
        out = self.run_spec(R.RuntimeSpec("CHIEF_ONLY", "ADAPTIVE_LLM", c5_weekend=True), max_ticks=6,
                            rival_transport=Down())
        self.assertTrue(out["replay"]["ok"], out["replay"])
        self.assertEqual(set(out["provenance_status"]["Red Bool Racing"]), {"POLICY_ERROR"})

    def test_tick_limit_stops_cleanly(self):
        out = self.run_spec(R.RuntimeSpec(), max_ticks=5)
        self.assertFalse(out["complete"])
        self.assertIn("tick limit", out["aborted"]["reason"])
        self.assertEqual(out["replay"]["resolved_ticks"], 5)


if __name__ == "__main__":
    unittest.main()
