"""2.1.0 reference port and 2.1.0 Harbor task generation."""

from __future__ import annotations

import copy
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

TASK = Path(__file__).resolve().parents[1]
SRC = TASK / "integrated_task" / "solution" / "reference_v21.py"


class StaticBoundaryTests(unittest.TestCase):
    def test_reference_reads_no_private_source(self):
        text = SRC.read_text()
        for forbidden in ("seed.json", "hidden_seed", "journal.jsonl", "/var/lib/f1sim", "F1SIM_STATE",
                          "_base_seed", "dnf_uniforms", "neutralization_schedule", "rival_policy_variant"):
            self.assertNotIn(forbidden, text, forbidden)
        self.assertIn('call("rules")', text)


class BuiltTaskTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.root = Path(cls.tmp.name) / "task"
        subprocess.run(["bash", str(TASK / "scripts" / "make_integrated_task.sh"), str(cls.root), "CHIEF_ONLY", "2.1.0"],
                       check=True, capture_output=True)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_task_metadata(self):
        self.assertIn('version = "2.1.0"', (self.root / "task.toml").read_text())
        mode = json.loads((self.root / "environment/sim/secret/mode.json").read_text())
        self.assertEqual(mode, json.loads((self.root / "tests/mode.json").read_text()))
        self.assertEqual(mode["benchmark_version"], "2.1.0")
        self.assertIn("Power-unit rules (benchmark 2.1.0)", (self.root / "instruction.md").read_text())
        self.assertTrue((self.root / "solution/reference_v21.py").exists())
        self.assertIn("reference_v21.py", (self.root / "solution/solve.sh").read_text())

    def run_in_task(self, code):
        """Run `code` in a fresh interpreter with the BUILT task's sim and solution on the path."""
        prelude = (f"import sys, json; sys.path[:0] = [{str(self.root / 'solution')!r}, "
                   f"{str(self.root / 'environment' / 'sim')!r}]\n"
                   "from f1sim.integrated_server import load_mode, public_rules, task_config\n"
                   f"cfg = task_config(load_mode(__import__('pathlib').Path({str(self.root / 'environment/sim/secret/mode.json')!r})))\n")
        proc = subprocess.run([sys.executable, "-c", prelude + code], capture_output=True, text=True)
        self.assertEqual(proc.returncode, 0, proc.stderr[-3000:])
        return json.loads(proc.stdout.strip().splitlines()[-1])

    def test_rules_publish_pu_rules_and_supersede_pool(self):
        out = self.run_in_task("r = public_rules(cfg); print(json.dumps({'v': r['benchmark_version'], "
                               "'pu': 'verified_source' in r['power_unit_rules'], "
                               "'sup': 'superseded_by' in r['track_a_model']['allocation']}))")
        self.assertEqual(out, {"v": "2.1.0", "pu": True, "sup": True})

    def test_reference_is_seed_blind_and_syncs(self):
        """Two seeds whose observations agree produce identical actions (no hidden input is used)."""
        out = self.run_in_task('''
import reference_v21
from f1pitwall.integrated.session import IntegratedSession
rules = json.loads(json.dumps(public_rules(cfg)))
runs = []
for seed in (11, 12):
    session, player, seen = IntegratedSession(cfg, seed), reference_v21.Reference21(rules), []
    for _ in range(4):
        obs = json.loads(json.dumps(session.observation("Apex"))); obs["decision_id"] = obs["tick_id"]
        action = player.decide(obs)
        seen.append([obs.get("race_progress", {}).get("track_status"), json.dumps(action, sort_keys=True)])
        session.submit("Apex", session.tick_id, action)
    runs.append({"seen": seen, "fallbacks": player.stats["fallbacks"]})
print(json.dumps(runs))
''')
        self.assertEqual([r["fallbacks"] for r in out], [0, 0])
        if all(a[0] == b[0] for a, b in zip(out[0]["seen"], out[1]["seen"])):
            self.assertEqual(out[0]["seen"], out[1]["seen"])

    def test_no_legal_action_deadlock_is_gone(self):
        from f1pitwall import coefficients as coef, pu_rules
        from f1pitwall.championship import new_championship_state
        from f1pitwall.championship_transition import available_component_actions, initial_inventory, prepare_race
        fia = pu_rules.with_fia_pu_rules(coef.DEFAULT)
        state = new_championship_state(resource_inventory=initial_inventory(fia))
        state.resource_inventory["Apex"]["stock:ICE"] = 1
        for d in ("Apex A", "Apex B"):
            state.power_units[d]["ICE"].wear = 0.95
            self.assertEqual(available_component_actions(state, d, fia)["ICE"], ["USE", "REPLACE"])
        decisions = [{"driver": d, "component": c, "action": "REPLACE" if (d, c) == ("Apex A", "ICE") else "USE"}
                     for d, comps in state.power_units.items() for c in comps]
        prepare_race(copy.deepcopy(state), decisions, fia)  # one replaced, the other runs on: legal


if __name__ == "__main__":
    unittest.main()
