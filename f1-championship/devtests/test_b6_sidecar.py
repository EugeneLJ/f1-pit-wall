"""B6 sidecar tests: the generated integrated Harbor task (SOLO_COORDINATION, 2.0.0).

Builds the task with scripts/make_integrated_task.sh into a temp dir, then exercises the
sidecar's request handler in a subprocess (no Docker): restart by verified replay, sealing,
tamper rejection, secrecy of seed/state, and the verifier's reward on a full season.
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

TASK = Path(__file__).resolve().parents[1]

SCRIPT = textwrap.dedent('''
    import json, os, sys
    from pathlib import Path
    root, state = Path(sys.argv[1]), Path(sys.argv[2])
    sys.path.insert(0, str(root / "environment" / "sim")); sys.path.insert(0, str(root / "solution"))
    from f1sim.integrated_server import IntegratedSimulator, load_mode
    from f1pitwall.integrated import policies as P
    mode = load_mode(root / "environment" / "sim" / "secret" / "mode.json")
    seed = json.loads((root / "environment" / "sim" / "secret" / "seed.json").read_text())["base_seed"]
    out = {}
    sim = IntegratedSimulator(state, seed, mode)
    pol = P.scripted("coordinator")
    obs = sim.handle({"cmd": "observe"})["observation"]
    text = json.dumps(obs) + json.dumps(sim.handle({"cmd": "rules"}))
    out["leaks"] = [w for w in ('"base_seed"', str(seed), '"events"', "journal") if w in text]
    for _ in range(20):
        reply = sim.handle({"cmd": "act", "decision_id": obs["decision_id"], "action": pol(obs)})
        obs = reply["observation"]
    out["stale"] = sim.handle({"cmd": "act", "decision_id": "t001", "action": pol(obs)})["error_code"]
    out["bad"] = sim.handle({"cmd": "act", "decision_id": obs["decision_id"], "action": {"type": "X"}})["error_code"]
    before = sim.handle({"cmd": "observe"})["observation"]
    restarted = IntegratedSimulator(state, seed, mode)
    out["restart_same"] = restarted.handle({"cmd": "observe"})["observation"] == before
    obs = before
    while obs["decision_type"] != "CHAMPIONSHIP_COMPLETE":
        a = pol(obs)
        if obs.get("engineer_reports"):
            a["consumed_reports"] = [r["record_hash"] for r in obs["engineer_reports"]][:1]
        obs = restarted.handle({"cmd": "act", "decision_id": obs["decision_id"], "action": a})["observation"]
    (state / "SEALED").write_text("x")
    out["sealed"] = restarted.handle({"cmd": "act", "decision_id": "t200", "action": {}})["error_code"]
    out["state_mode"] = oct(os.stat(state).st_mode & 0o777)
    print(json.dumps(out))
''')

GRADE = textwrap.dedent('''
    import os, sys, json
    from pathlib import Path
    root, state, ev, logs = map(Path, sys.argv[1:5])
    sys.path.insert(0, str(root / "environment" / "sim"))
    os.environ["F1SIM_STATE_DIR"], os.environ["F1SIM_EVIDENCE_DIR"] = str(state), str(ev)
    os.environ["F1SIM_MODE_PATH"] = str(root / "environment" / "sim" / "secret" / "mode.json")
    from f1sim import export as legacy_export
    legacy_export.STATE_DIR, legacy_export.EVIDENCE_DIR = state, ev
    from f1sim.export_integrated import export_integrated
    export_integrated(state, ev)
    print("exported")
''')


class IntegratedSidecarTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.root = Path(cls.tmp.name) / "task"
        subprocess.run(["bash", str(TASK / "scripts" / "make_integrated_task.sh"), str(cls.root), "MOCK_ENGINEERS"],
                       check=True, capture_output=True)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def run_py(self, code, *args):
        proc = subprocess.run([sys.executable, "-c", code, *map(str, args)], capture_output=True, text=True)
        self.assertEqual(proc.returncode, 0, proc.stderr[-2000:])
        return proc.stdout.strip().splitlines()[-1]

    def test_task_files_and_legacy_untouched(self):
        toml = (self.root / "task.toml").read_text()
        self.assertIn('version = "2.0.1"', toml)
        self.assertIn("f1sim.export_integrated", toml)
        self.assertIn("f1sim.integrated_server", (self.root / "environment/sim/Dockerfile").read_text())
        self.assertIn('version = "1.1.0"', (TASK / "task.toml").read_text())
        self.assertIn('"f1sim.server"', (TASK / "environment/sim/Dockerfile").read_text())
        self.assertFalse((TASK / "environment/sim/f1sim/integrated_server.py").exists())

    def test_sidecar_restart_seal_and_grade(self):
        state, ev, logs = (Path(self.tmp.name) / n for n in ("state", "evidence", "logs"))
        result = json.loads(self.run_py(SCRIPT, self.root, state))
        self.assertEqual(result["leaks"], [])
        self.assertEqual(result["stale"], "out_of_order_decision")
        self.assertEqual(result["bad"], "invalid_action")
        self.assertTrue(result["restart_same"])
        self.assertEqual(result["sealed"], "sealed")
        self.assertEqual(result["state_mode"], "0o700")
        self.run_py(GRADE, self.root, state, ev, logs)
        logs.mkdir(exist_ok=True)
        env = {"F1_EVIDENCE_DIR": str(ev), "F1_SEED_PATH": str(self.root / "tests/hidden_seed.json"),
               "F1_MODE_PATH": str(self.root / "tests/mode.json"), "F1_REWARD_PATH": str(logs / "reward.txt"),
               "F1_REPORT_PATH": str(logs / "report.json")}
        import os
        subprocess.run([sys.executable, str(self.root / "tests/grade_integrated.py")], check=True,
                       env={**os.environ, **env})
        report = json.loads((logs / "report.json").read_text())
        self.assertTrue(report["integrity"]["intact"], report["integrity"])
        self.assertTrue(report["completion"]["complete"])
        self.assertGreater(report["reward"], 0)
        self.assertEqual(report["integrity"]["rejected_requests_logged"], 2)
        # tampering with one Engineer record breaks integrity
        rec = next((ev / "engineers").rglob("*.jsonl"))
        lines = rec.read_text().splitlines()
        lines[3] = lines[3].replace('"self_reported"', '"calibrated"')
        rec.write_text("\n".join(lines) + "\n")
        subprocess.run([sys.executable, str(self.root / "tests/grade_integrated.py")], check=True,
                       env={**os.environ, **env})
        tampered = json.loads((logs / "report.json").read_text())
        self.assertFalse(tampered["integrity"]["intact"])
        self.assertEqual(tampered["reward"], 0.0)


if __name__ == "__main__":
    unittest.main()
