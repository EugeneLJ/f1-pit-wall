"""P0 boundary tests: sealed sidecar, journal integrity, and verifier behaviour.

Run from the task directory:  python3 -m unittest discover -s devtests -v
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path

TASK = Path(__file__).resolve().parents[1]
SIM = TASK / "environment" / "sim"
sys.path.insert(0, str(SIM))
sys.path.insert(0, str(TASK / "solution"))

from f1pitwall.journal import JournalError, seal_entry, GENESIS_HASH  # noqa: E402
from f1sim import export as export_mod  # noqa: E402
from f1sim import server as server_mod  # noqa: E402
from play import component_action, race_action  # noqa: E402

SEED = json.loads((SIM / "secret" / "seed.json").read_text())["base_seed"]


def next_action(obs, policy="heuristic"):
    if obs["decision_type"] == "COMPONENT_DECISION":
        return component_action(obs)
    if policy == "nothing":
        return {"type": "RACE_STRATEGY", "driver_a": "STAY", "driver_b": "STAY"}
    return race_action(obs)


class Harness:
    """A Simulator on a temp private state dir plus a temp evidence dir."""

    def __init__(self):
        self.root = Path(tempfile.mkdtemp(prefix="f1p0"))
        self.state = self.root / "state"
        self.evidence = self.root / "evidence"
        self.sim = server_mod.Simulator(self.state, SEED)

    def act(self, decision_id, action):
        return self.sim.handle({"cmd": "act", "decision_id": decision_id, "action": action})

    def observe(self):
        return self.sim.handle({"cmd": "observe"})["observation"]

    def play(self, limit=None, policy="heuristic"):
        obs, count = self.observe(), 0
        while obs["decision_type"] != "CHAMPIONSHIP_COMPLETE" and (limit is None or count < limit):
            response = self.act(obs["decision_id"], next_action(obs, policy))
            assert response["ok"], response
            obs, count = response["observation"], count + 1
        return obs

    def export(self):
        return export_mod.export(self.state, self.evidence)

    def grade(self, seed_path=None):
        reward = self.root / "reward.txt"
        report = self.root / "report.json"
        env = dict(os.environ, F1_EVIDENCE_DIR=str(self.evidence), F1_REWARD_PATH=str(reward),
                   F1_REPORT_PATH=str(report))
        if seed_path is not None:
            env["F1_SEED_PATH"] = str(seed_path)
        subprocess.run([sys.executable, str(TASK / "tests" / "grade.py")], env=env, check=True)
        return float(reward.read_text()), json.loads(report.read_text())

    def rewrite_journal(self, mutate):
        """Attacker with full write access: mutate entries, then re-seal chain and manifest."""
        path = self.evidence / "journal.jsonl"
        entries = [json.loads(line) for line in path.read_text().splitlines()]
        entries = mutate(entries)
        prev, lines = GENESIS_HASH, []
        for index, entry in enumerate(entries):
            entry["seq"] = index + 1
            sealed = seal_entry(entry, prev)
            prev = sealed["entry_hash"]
            lines.append(json.dumps(sealed, sort_keys=True, separators=(",", ":")))
        path.write_text("".join(line + "\n" for line in lines))
        manifest = json.loads((self.evidence / "manifest.json").read_text())
        manifest.update(journal_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                        journal_entries=len(lines), head_hash=prev)
        (self.evidence / "manifest.json").write_text(json.dumps(manifest))

    def close(self):
        shutil.rmtree(self.root, ignore_errors=True)


class LayoutTests(unittest.TestCase):
    def test_engine_copies_are_identical(self):
        canonical = _tree(TASK / "src" / "f1pitwall")
        for target in (SIM / "f1pitwall", TASK / "tests" / "f1pitwall"):
            self.assertEqual(canonical, _tree(target), f"{target} drifted; run scripts/sync_engine.py")

    def test_seed_only_in_sim_and_verifier(self):
        self.assertEqual(json.loads((TASK / "tests" / "hidden_seed.json").read_text())["base_seed"], SEED)
        agent_side = [TASK / "environment" / "Dockerfile", TASK / "environment" / "client" / "f1ctl",
                      TASK / "instruction.md", TASK / "solution" / "play.py"]
        for path in agent_side:
            self.assertNotIn(str(SEED), path.read_text())
        self.assertIn("sim", (TASK / "environment" / ".dockerignore").read_text().split())
        main_dockerfile = (TASK / "environment" / "Dockerfile").read_text()
        self.assertNotIn("COPY sim", main_dockerfile)
        self.assertNotIn("f1pitwall", main_dockerfile)

    def test_shared_volume_holds_only_socket_dir(self):
        compose = (TASK / "environment" / "docker-compose.yaml").read_text()
        mounts = [line.strip() for line in compose.splitlines() if line.strip().startswith("- ")]
        self.assertEqual(mounts, ["- f1sock:/run/f1sim", "- f1sock:/run/f1sim"])
        self.assertIn("network_mode: none", compose)
        sim_dockerfile = (SIM / "Dockerfile").read_text()
        self.assertIn("/var/lib/f1sim", sim_dockerfile)
        self.assertEqual(server_mod.STATE_DIR.as_posix(), "/var/lib/f1sim")
        self.assertEqual(server_mod.SOCKET_PATH.parent.as_posix(), "/run/f1sim")


def _tree(root: Path) -> dict:
    return {p.relative_to(root).as_posix(): p.read_bytes() for p in sorted(root.rglob("*"))
            if p.is_file() and "__pycache__" not in p.parts}


class SimulatorProtocolTests(unittest.TestCase):
    def setUp(self):
        self.h = Harness()

    def tearDown(self):
        self.h.close()

    def test_observation_exposes_decision_id_but_no_hidden_state(self):
        response = self.h.sim.handle({"cmd": "observe"})
        obs = response["observation"]
        self.assertEqual(obs["decision_id"], "d001")
        text = json.dumps(response) + json.dumps(self.h.sim.handle({"cmd": "rules"}))
        self.assertNotIn(str(SEED), text)
        for word in ('"seed"', '"events"', '"event_history"', '"cars"', "base_seed"):
            self.assertNotIn(word, text)

    def test_no_reset_rewind_or_seed_commands(self):
        for payload in (b'{"cmd":"reset"}', b'{"cmd":"rewind"}', b'{"cmd":"seed"}',
                        b'{"cmd":"observe","seed":1}', b'{"cmd":"act","decision_id":"d001"}'):
            request, error = server_mod.parse_request(payload)
            self.assertIsNone(request)
            self.assertIn(error["error_code"], {"unknown_command", "malformed_request"})
        self.assertEqual(server_mod.parse_request(b"{bad")[1]["error_code"], "malformed_request")
        self.assertEqual(server_mod.parse_request(b"\xff\xfe")[1]["error_code"], "malformed_request")
        big = b'{"cmd":"observe","x":"' + b"a" * 20000 + b'"}'
        self.assertEqual(server_mod.parse_request(big)[1]["error_code"], "request_too_large")

    def test_wrong_phase_action_is_rejected_without_state_change(self):
        before = self.h.observe()
        response = self.h.act("d001", {"type": "RACE_STRATEGY", "driver_a": "PIT", "driver_b": "PIT"})
        self.assertFalse(response["ok"])
        self.assertEqual(response["error_code"], "invalid_action")
        self.assertEqual(self.h.observe(), before)

    def test_duplicate_and_out_of_order_ids_are_rejected(self):
        obs = self.h.observe()
        self.assertEqual(self.h.act("d999", component_action(obs))["error_code"], "out_of_order_decision")
        self.assertEqual(self.h.act(1, component_action(obs))["error_code"], "bad_decision_id")
        self.assertTrue(self.h.act("d001", component_action(obs))["ok"])
        duplicate = self.h.act("d001", component_action(obs))
        self.assertEqual(duplicate["error_code"], "duplicate_decision")
        self.assertEqual(duplicate["decision_id"], "d002")
        self.assertEqual(self.h.observe()["decision_id"], "d002")

    def test_restart_resumes_without_rewind(self):
        self.h.play(limit=6)
        before = self.h.observe()
        restarted = server_mod.Simulator(self.h.state, SEED)
        self.assertEqual(restarted.handle({"cmd": "observe"})["observation"], before)

    def test_tampered_private_journal_fails_closed_on_restart(self):
        self.h.play(limit=3)
        path = self.h.state / "journal.jsonl"
        lines = path.read_text().splitlines()
        entry = json.loads(lines[1])
        entry["action"]["driver_a"] = "STAY" if entry["action"]["driver_a"] == "PIT" else "PIT"
        lines[1] = json.dumps(entry)
        path.write_text("\n".join(lines) + "\n")
        with self.assertRaises(JournalError):
            server_mod.Simulator(self.h.state, SEED)

    def test_sealed_session_rejects_actions(self):
        self.h.export()
        obs = self.h.observe()
        self.assertEqual(self.h.act(obs["decision_id"], component_action(obs))["error_code"], "sealed")

    def test_act_after_completion_is_rejected(self):
        obs = self.h.play()
        self.assertIsNone(obs["decision_id"])
        response = self.h.act("d033", {"type": "RACE_STRATEGY", "driver_a": "STAY", "driver_b": "STAY"})
        self.assertEqual(response["error_code"], "championship_complete")


class SocketServerTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="f1s"))
        self.sock = self.root / "s.sock"
        seed_file = self.root / "seed.json"
        seed_file.write_text(json.dumps({"base_seed": SEED}))
        self.server = server_mod.serve(self.sock, self.root / "state", seed_file)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        shutil.rmtree(self.root, ignore_errors=True)

    def send(self, payload: bytes):
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as conn:
            conn.settimeout(10)
            conn.connect(str(self.sock))
            conn.sendall(payload)
            data = b""
            while not data.endswith(b"\n"):
                chunk = conn.recv(65536)
                if not chunk:
                    break
                data += chunk
        return json.loads(data)

    def test_socket_is_world_connectable_and_client_works(self):
        self.assertEqual(self.sock.stat().st_mode & 0o777, 0o666)
        env = dict(os.environ, F1SIM_SOCKET=str(self.sock))
        client = TASK / "environment" / "client" / "f1ctl"
        out = subprocess.run([sys.executable, str(client), "observe"], env=env, capture_output=True, text=True)
        obs = json.loads(out.stdout)["observation"]
        out = subprocess.run([sys.executable, str(client), "act", obs["decision_id"],
                              json.dumps(component_action(obs))], env=env, capture_output=True, text=True)
        self.assertTrue(json.loads(out.stdout)["ok"])
        out = subprocess.run([sys.executable, str(client), "act", obs["decision_id"],
                              json.dumps(component_action(obs))], env=env, capture_output=True, text=True)
        self.assertEqual(json.loads(out.stdout)["error_code"], "duplicate_decision")
        self.assertEqual(out.returncode, 1)

    def test_oversized_and_garbage_requests(self):
        try:
            outcome = self.send(b'{"cmd":"observe","p":"' + b"x" * 1_000_000 + b'"}\n')["error_code"]
        except (BrokenPipeError, ConnectionResetError):
            outcome = "connection_closed"
        self.assertIn(outcome, {"request_too_large", "connection_closed"})
        self.assertEqual(self.send(b"\xff\xfe\x00\n")["error_code"], "malformed_request")
        self.assertTrue(self.send(b'{"cmd":"observe"}\n')["ok"])

    def test_concurrent_submissions_accept_exactly_one(self):
        obs = self.send(b'{"cmd":"observe"}\n')["observation"]
        payload = (json.dumps({"cmd": "act", "decision_id": obs["decision_id"],
                               "action": component_action(obs)}) + "\n").encode()
        results = []
        threads = [threading.Thread(target=lambda: results.append(self.send(payload))) for _ in range(20)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(len(results), 20)
        self.assertEqual(sum(1 for r in results if r["ok"]), 1)
        self.assertEqual({r["error_code"] for r in results if not r["ok"]}, {"duplicate_decision"})


class VerifierTests(unittest.TestCase):
    def setUp(self):
        self.h = Harness()

    def tearDown(self):
        self.h.close()

    def test_complete_heuristic_season_is_scored(self):
        self.h.play()
        self.h.export()
        reward, report = self.h.grade()
        self.assertTrue(report["completion"]["complete"])
        self.assertTrue(report["integrity"]["intact"])
        self.assertEqual(report["completion"]["accepted_decisions"], 32)
        self.assertGreaterEqual(reward, 0.0)
        self.assertLessEqual(reward, 1.0)
        norm = report["normalization"]
        self.assertEqual(norm["U_theoretical_max_points"], 43 * 8)
        expected = max(0.0, (norm["P_apex_points"] - norm["D_do_nothing_points_same_seed"])
                       / (norm["U_theoretical_max_points"] - norm["D_do_nothing_points_same_seed"]))
        self.assertAlmostEqual(reward, expected)

    def test_do_nothing_scores_zero(self):
        self.h.play(policy="nothing")
        self.h.export()
        reward, report = self.h.grade()
        self.assertTrue(report["completion"]["complete"])
        self.assertEqual(reward, 0.0)

    def test_stop_early_scores_zero(self):
        self.h.play(limit=20)
        self.h.export()
        reward, report = self.h.grade()
        self.assertTrue(report["integrity"]["intact"])
        self.assertFalse(report["completion"]["complete"])
        self.assertEqual(reward, 0.0)

    def test_nop_agent_scores_zero(self):
        self.h.export()
        reward, report = self.h.grade()
        self.assertEqual(report["completion"]["accepted_decisions"], 0)
        self.assertEqual(reward, 0.0)

    def test_missing_evidence_scores_zero(self):
        reward, report = self.h.grade()
        self.assertEqual(reward, 0.0)
        self.assertEqual(report["integrity"]["error"], "missing sidecar evidence")

    def test_rejected_requests_are_evidenced_and_harmless(self):
        obs = self.h.observe()
        self.h.act("d009", component_action(obs))
        self.h.act("d001", {"type": "RACE_STRATEGY", "driver_a": "PIT", "driver_b": "PIT"})
        self.h.play()
        self.h.export()
        reward, report = self.h.grade()
        self.assertTrue(report["integrity"]["intact"])
        self.assertEqual(report["integrity"]["rejected_requests_logged"], 2)
        clean = Harness()
        try:
            clean.play()
            clean.export()
            self.assertEqual(clean.grade()[0], reward)
        finally:
            clean.close()

    def test_edited_journal_without_resealing_fails(self):
        self.h.play()
        self.h.export()
        path = self.h.evidence / "journal.jsonl"
        path.write_text(path.read_text().replace('"STAY"', '"PIT"', 1))
        reward, report = self.h.grade()
        self.assertEqual(reward, 0.0)
        self.assertFalse(report["integrity"]["intact"])

    def test_fully_resealed_forged_actions_fail_replay(self):
        self.h.play()
        self.h.export()

        def flip(entries):
            for entry in entries:
                if entry["decision_type"] == "RACE_STRATEGY":
                    entry["action"]["driver_a"] = "PIT_MEDIUM" if entry["action"]["driver_a"] == "STAY" else "STAY"
                    break
            return entries

        self.h.rewrite_journal(flip)
        reward, report = self.h.grade()
        self.assertEqual(reward, 0.0)
        self.assertIn("mismatch", report["integrity"]["error"])

    def test_forged_rejection_of_legal_action_fails(self):
        self.h.play()
        self.h.export()

        def inject(entries):
            legal = dict(entries[0])
            legal.update(kind="rejected", error_code="invalid_action", obs_after_sha256=None)
            return [legal] + entries

        self.h.rewrite_journal(inject)
        reward, report = self.h.grade()
        self.assertEqual(reward, 0.0)
        self.assertIn("legal under replay", report["integrity"]["error"])

    def test_wrong_seed_fails_replay(self):
        self.h.play()
        self.h.export()
        other = self.h.root / "other_seed.json"
        other.write_text(json.dumps({"base_seed": SEED + 1}))
        reward, report = self.h.grade(seed_path=other)
        self.assertEqual(reward, 0.0)
        self.assertFalse(report["integrity"]["intact"])

    def test_timing_is_reported(self):
        self.h.play()
        self.h.export()
        _, report = self.h.grade()
        self.assertEqual(report["timing"]["accepted_decisions"], 32)
        self.assertIn("decision_span_sec", report["timing"])


if __name__ == "__main__":
    unittest.main()
