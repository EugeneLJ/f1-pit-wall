"""1.1.0: explicit driver-name mapping, benchmark version, runtime pin, historical replays."""

from __future__ import annotations

import json
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

TASK = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TASK / "environment" / "sim"))
sys.path.insert(0, str(TASK / "solution"))

from f1pitwall import engine  # noqa: E402
from f1pitwall.championship_adapter import ENGINE_TO_CHAMPIONSHIP_DRIVER  # noqa: E402
from f1pitwall.championship_contract import ChampionshipSession  # noqa: E402
from f1pitwall.version import BENCHMARK_VERSION, RUNTIME_PYTHON  # noqa: E402
from f1sim import server  # noqa: E402

PUBLIC_NAMES = {"Apex A", "Apex B", "Orion A", "Orion B", "Nova A", "Nova B", "Vertex A", "Vertex B"}
HISTORY = TASK / "analysis" / "results" / "rep_runs"


class RulesInterfaceTests(unittest.TestCase):
    def test_rules_carry_the_benchmark_version(self):
        self.assertEqual(server.PUBLIC_RULES["benchmark_version"], BENCHMARK_VERSION)
        self.assertEqual(BENCHMARK_VERSION, "1.1.0")

    def test_base_pace_is_keyed_by_observation_names_with_unchanged_values(self):
        paces = server.PUBLIC_RULES["race_rules_track_a"]["published_base_pace"]
        self.assertEqual(set(paces), PUBLIC_NAMES)
        for internal, public in ENGINE_TO_CHAMPIONSHIP_DRIVER.items():
            self.assertEqual(paces[public], engine.LEGACY_BASE_PACE[internal])

    def test_mapping_is_explicit_and_bijective(self):
        table = server.PUBLIC_RULES["race_rules_track_a"]["driver_identifiers"]["engine_internal_to_public"]
        self.assertEqual(set(table.values()), PUBLIC_NAMES)
        self.assertEqual(len(set(table.values())), len(table))
        self.assertEqual(table, ENGINE_TO_CHAMPIONSHIP_DRIVER)

    def test_internal_names_appear_only_in_the_mapping_table(self):
        rules = json.loads(json.dumps(server.PUBLIC_RULES))
        rules["race_rules_track_a"].pop("driver_identifiers")
        self.assertEqual(re.findall(r"Rival \d", json.dumps(rules)), [])

    def test_rules_expose_no_hidden_state(self):
        text = json.dumps(server.PUBLIC_RULES).lower()
        for word in ("base_seed", "journal", "/var/lib", "secret", "events\"", "dnf_uniform"):
            self.assertNotIn(word, text)


class ObservationUnchangedTests(unittest.TestCase):
    def test_observations_use_only_public_names(self):
        from play import component_action, race_action
        session = ChampionshipSession(base_seed=3)
        while True:
            obs = session.observation()
            self.assertNotRegex(json.dumps(obs), r"Rival \d")
            if session.decision_type == "CHAMPIONSHIP_COMPLETE":
                break
            session.submit(component_action(obs) if obs["decision_type"] == "COMPONENT_DECISION" else race_action(obs))

    def test_instruction_is_unchanged_by_the_interface_fix(self):
        self.assertNotIn("benchmark_version", (TASK / "instruction.md").read_text())


class RuntimePinTests(unittest.TestCase):
    def test_images_analysis_and_version_agree_on_python(self):
        wanted = ".".join(map(str, RUNTIME_PYTHON))
        self.assertEqual((TASK / ".python-version").read_text().strip(), wanted)
        for dockerfile in (TASK / "environment" / "sim" / "Dockerfile", TASK / "tests" / "Dockerfile"):
            self.assertRegex(dockerfile.read_text(), rf"FROM python:{re.escape(wanted)}\.\d+")

    def test_replay_tools_refuse_other_interpreters(self):
        sys.path.insert(0, str(TASK / "analysis"))
        import _runtime
        import os
        if tuple(sys.version_info[:2]) == tuple(RUNTIME_PYTHON):
            _runtime.require_runtime_python()
        else:
            old = os.environ.pop("F1_ALLOW_ANY_PYTHON", None)
            try:
                with self.assertRaises(SystemExit):
                    _runtime.require_runtime_python()
            finally:
                if old is not None:
                    os.environ["F1_ALLOW_ANY_PYTHON"] = old


@unittest.skipUnless(tuple(sys.version_info[:2]) == tuple(RUNTIME_PYTHON), "historical replays need the image interpreter")
class HistoricalReplayTests(unittest.TestCase):
    """The four 1.0.0 Gemini runs still replay and score identically under 1.1.0."""

    EXPECTED = {"r0": 0.69841270, "r1": 0.70384615, "r2": 0.63076923, "r3": 0.68846154}

    def seed(self, run):
        if run == "r0":
            return json.loads((TASK / "tests" / "hidden_seed.json").read_text())["base_seed"]
        seeds = json.loads((HISTORY / "repeat_seeds.json").read_text())["seeds"]
        return seeds[int(run[1]) - 1]

    def test_historical_runs_regrade_exactly(self):
        for run, reward in self.EXPECTED.items():
            with tempfile.TemporaryDirectory() as tmp:
                seed_path = Path(tmp) / "seed.json"
                seed_path.write_text(json.dumps({"schema_version": 1, "base_seed": self.seed(run)}))
                env = {"F1_EVIDENCE_DIR": str(HISTORY / run / "evidence"), "F1_SEED_PATH": str(seed_path),
                       "F1_REWARD_PATH": f"{tmp}/reward.txt", "F1_REPORT_PATH": f"{tmp}/report.json",
                       "PATH": "/usr/bin:/bin"}
                subprocess.run([sys.executable, str(TASK / "tests" / "grade.py")], env=env, check=True)
                report = json.loads(Path(f"{tmp}/report.json").read_text())
                self.assertTrue(report["integrity"]["intact"], run)
                self.assertAlmostEqual(float(Path(f"{tmp}/reward.txt").read_text()), reward, places=8, msg=run)
                self.assertEqual(report["benchmark_version"], BENCHMARK_VERSION)
                self.assertEqual(report["evidence"]["evidence_benchmark_version"], "pre-1.1.0")


if __name__ == "__main__":
    unittest.main()
