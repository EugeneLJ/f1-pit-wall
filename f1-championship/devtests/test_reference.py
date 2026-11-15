"""The executable reference (solution/reference.py) uses public observations only."""

import ast
import json
import sys
import unittest
from pathlib import Path

TASK = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TASK / "src"))
sys.path.insert(0, str(TASK / "solution"))

import reference  # noqa: E402
from f1pitwall.championship_contract import ChampionshipSession  # noqa: E402

SEED_A, SEED_B = 1111, 2222


def _play(seed, decisions, futures=4):
    old = reference.FUTURES, reference.PLAN_PATHS, reference.PLAN_SWEEPS
    reference.FUTURES, reference.PLAN_PATHS, reference.PLAN_SWEEPS = futures, 2, 0  # small budgets: fast
    try:
        session, player, log = ChampionshipSession(base_seed=seed), reference.Reference(), []
        for index in range(decisions):
            obs = json.loads(json.dumps(session.observation()))
            obs["decision_id"] = f"d{index + 1:03d}"
            action = player.decide(obs)
            log.append((obs, action))
            session.submit(action)
        return player, log
    finally:
        reference.FUTURES, reference.PLAN_PATHS, reference.PLAN_SWEEPS = old


class ReferenceInformationTests(unittest.TestCase):
    def test_source_never_touches_seed_or_evidence(self):
        source = (TASK / "solution" / "reference.py").read_text()
        for token in ("_base_seed", "seed.json", "hidden_seed", "/opt/f1sim", "/var/lib/f1sim",
                      "/evidence", "journal", "dnf_uniforms", "neutralization_schedule"):
            self.assertNotIn(token, source.split('"""', 2)[2], token)
        seeds = [node for node in ast.walk(ast.parse(source))
                 if isinstance(node, ast.keyword) and node.arg == "base_seed"]
        self.assertTrue(all(isinstance(k.value, ast.Constant) and k.value.value == 0 for k in seeds))

    def test_model_tracks_the_real_race_without_fallback(self):
        player, log = _play(SEED_A, 15)  # component decision + one full race
        self.assertEqual(player.stats["fallbacks"], 0)
        self.assertEqual(player.stats["resyncs"], 0)
        self.assertEqual(player.stats["race_decisions"], 14)

    def test_actions_depend_only_on_observations(self):
        """Two seeds: while the observations agree, the actions agree (no hidden-future access)."""
        _, a = _play(SEED_A, 15)
        _, b = _play(SEED_B, 15)
        agreed = 0
        for (obs_a, act_a), (obs_b, act_b) in zip(a, b):
            if obs_a != obs_b:
                break
            self.assertEqual(act_a, act_b)
            agreed += 1
        self.assertGreaterEqual(agreed, 2)

    def test_unknown_version_falls_back_to_the_public_heuristic(self):
        player = reference.Reference({"benchmark_version": "0.0.0"})
        session = ChampionshipSession(base_seed=SEED_A)
        action = player.decide(session.observation())
        session.submit(action)
        self.assertEqual(player.stats["fallbacks"], 1)


if __name__ == "__main__":
    unittest.main()
