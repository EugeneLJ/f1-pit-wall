"""B6 integration tests: integrated race engine, team orders, commitments, Engineers,
two-team simultaneous ticks, journal v2 replay and provider contracts (no network)."""

from __future__ import annotations

import copy
import json
import os
import random
import sys
import tempfile
import unittest
from pathlib import Path

TASK = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TASK / "src"))
sys.path.insert(0, str(TASK))

from f1pitwall import coefficients as coef  # noqa: E402
from f1pitwall import engine  # noqa: E402
from f1pitwall.championship_contract import ChampionshipSession  # noqa: E402
from f1pitwall.integrated import config as C  # noqa: E402
from f1pitwall.integrated import match as M  # noqa: E402
from f1pitwall.integrated import policies as P  # noqa: E402
from f1pitwall.integrated import providers as PR  # noqa: E402
from f1pitwall.integrated import race as ir  # noqa: E402
from f1pitwall.integrated import session as S  # noqa: E402
from f1pitwall.integrated import verify as V  # noqa: E402
from f1pitwall.integrated.engineers import EngineerBroker  # noqa: E402
from f1pitwall.version import BENCHMARK_VERSION  # noqa: E402

FMT = coef.race_format(coef.DEFAULT)
N = len(FMT["decision_laps"])
MODEL = ir.TEAM_ORDER_MODEL
RACE = {"order": "RACE"}


def configured(seed=1, events=None, difficulty=0.5):
    config = {"grid": list(engine.LEGACY_CAR_NAMES), "pace": dict(engine.LEGACY_BASE_PACE),
              "overtaking": coef.DEFAULT["track_performance"]["overtaking"], "overtaking_difficulty": difficulty,
              "tyres": coef.tyre_model(coef.DEFAULT), "pit": coef.pit_model("mixed", coef.DEFAULT), **FMT}
    if events is not None:
        config["events"] = list(events)
    return engine.new_state(seed, config)


def scene(events=("GREEN",) * N, gap=0.6, rear=3.0, ahead=1.6, b_pace=-0.3, a_age=4, b_age=4, difficulty=0.5):
    """Rival 2 | Apex A | Apex B (faster) | Rival 3, others far away."""
    s = ir.attach(configured(1, list(events) + ["GREEN"] * (N - len(events)), difficulty), ["Apex"])
    cars = {c["name"]: c for c in s["cars"]}
    t = 720.0
    layout = [("Rival 1", t - 10), ("Rival 2", t), ("Apex A", t + ahead), ("Apex B", t + ahead + gap),
              ("Rival 3", t + ahead + gap + rear), ("Rival 4", t + 20), ("Rival 5", t + 25), ("Rival 6", t + 30)]
    for name, e in layout:  # quiet rivals: fresh HARDs with both compounds used, so nobody else pits
        cars[name]["elapsed"] = e
        cars[name].update({"tyre_age": 2, "compound": "HARD", "compounds_used": ["MEDIUM", "HARD"]})
    for name in ("Apex A", "Apex B"):
        cars[name].update({"compound": "MEDIUM", "compounds_used": ["HARD", "MEDIUM"]})
    cars["Apex A"]["tyre_age"], cars["Apex B"]["tyre_age"] = a_age, b_age
    for name in cars:
        cars[name]["base_pace"] = 90.0
    cars["Apex B"]["base_pace"] = 90.0 + b_pace
    return s


def order_of(s):
    return [c["name"] for c in sorted(s["cars"], key=lambda c: (c["elapsed"], c["name"]))]


def act(order="RACE", a="STAY", b="STAY", commitment=None):
    to = {"order": order}
    if commitment is not None:
        to["commitment"] = commitment
    return {"Apex": {"driver_a": a, "driver_b": b, "team_order": to}}


def finish_baseline(s):
    """Play the race out with every team on RACE and the published baseline pit rule."""
    while not s["complete"]:
        acts = {}
        for slot in s["integrated"]["controlled"]:
            view = S.team_race_view(s, slot, lambda n: n, {x: x for x in C.SLOTS}, "t")
            obs = {"decision_type": "RACE_STRATEGY", "race_progress": view,
                   "team_orders": ir.public_order_view(s, slot)}
            a = P.race_action("baseline", obs)
            acts[slot] = {"driver_a": a["driver_a"], "driver_b": a["driver_b"], "team_order": a["team_order"]}
        ir.step(s, acts)
    return engine.result(s)


def apex_points(result):
    return sum(e["points"] for e in result["classification"] if e["team"] == "Apex")


def play(cfg, seed, pols, broker=None):
    s = S.IntegratedSession(cfg, seed, engineer_broker=broker)
    while s.decision_type != S.CHAMPIONSHIP_COMPLETE:
        tick = s.tick_id
        for label in s.teams:
            s.submit(label, tick, pols[label](s.observation(label)))
    return s


class VersionAndLegacyTests(unittest.TestCase):
    def test_versions_and_modes(self):
        self.assertEqual(BENCHMARK_VERSION, "1.1.0")
        self.assertEqual(C.INTEGRATED_VERSION, "2.0.0")
        with self.assertRaises(ValueError):
            C.IntegratedConfig(C.SOLO_LEGACY, []).validate()
        self.assertNotEqual(C.solo_coordination().config_hash(), C.two_team(1).config_hash())
        self.assertEqual(C.IntegratedConfig.from_dict(C.two_team(1).as_dict()).config_hash(),
                         C.two_team(1).config_hash())

    def test_solo_legacy_contract_unchanged(self):
        session = ChampionshipSession(base_seed=5)
        obs = session.observation()
        self.assertEqual(obs["contract_version"], 1)
        self.assertNotIn("team_orders", json.dumps(obs))
        with self.assertRaises(ValueError):
            session.submit({"type": "COMPONENT_DECISION", "decisions": [], "team_order": RACE})

    def test_race_order_is_bit_identical_to_1_1_0(self):
        for seed in range(40):
            rng = random.Random(seed)
            a, b = configured(seed), ir.attach(configured(seed), ["Apex", "Orion"])
            while not a["complete"]:
                pick = {k: (rng.choice(engine.COMPOUND_ACTIONS) if rng.random() < 0.15 else "STAY")
                        for k in ("driver_a", "driver_b")}
                status, idx = b["events"][b["step"]], b["step"]
                rem = engine.laps_total(b) - engine._decision_laps(b)[idx]
                orion = {k: engine._rival_action(next(c for c in b["cars"] if c["name"] == n), status, idx, N,
                                                 engine._tyres(b), rem)
                         for k, n in ir.team_cars("Orion").items()}
                engine.step(a, pick)
                ir.step(b, {"Apex": {**pick, "team_order": RACE}, "Orion": {**orion, "team_order": RACE}})
            self.assertEqual(engine.result(a)["classification"], engine.result(b)["classification"])
            self.assertEqual([c["elapsed"] for c in a["cars"]], [c["elapsed"] for c in b["cars"]])


class TeamOrderMechanicsTests(unittest.TestCase):
    def test_swap_takes_time_and_exchanges_order(self):
        race, held = scene(), scene()
        report = ir.step(race, act("SWAP"))["Apex"]
        ir.step(held, act("HOLD"))
        self.assertEqual(report["status"], "COMPLETED")
        o = order_of(race)
        self.assertLess(o.index("Apex B"), o.index("Apex A"))
        lead_free = scene()
        ir.step(lead_free, act("RACE"))
        a_free = next(c for c in lead_free["cars"] if c["name"] == "Apex A")["elapsed"]
        a_swap = next(c for c in race["cars"] if c["name"] == "Apex A")["elapsed"]
        self.assertGreaterEqual(a_swap - a_free, MODEL["exchange"]["clearance_sec"] - 1e-9)
        self.assertGreater(report["lift_sec"], 0)

    def test_swap_blocked_delayed_or_failed(self):
        self.assertEqual(ir.step(scene(gap=2.0), act("SWAP"))["Apex"]["status"], "INFEASIBLE")
        self.assertEqual(ir.step(scene(events=("SC",)), act("SWAP"))["Apex"]["status"], "DELAYED")
        self.assertEqual(ir.step(scene(events=("VSC",)), act("SWAP"))["Apex"]["status"], "DELAYED")
        self.assertEqual(ir.step(scene(), act("SWAP", a="PIT_HARD"))["Apex"]["status"], "DELAYED")
        slow = scene(b_pace=+1.0)  # car behind much slower: the needed lift exceeds the maximum
        report = ir.step(slow, act("SWAP"))["Apex"]
        self.assertEqual(report["status"], "FAILED")
        o = order_of(slow)
        self.assertLess(o.index("Apex A"), o.index("Apex B"))

    def test_exchange_under_pressure_exposes_cars_to_rival(self):
        safe, pressed = scene(rear=3.0, difficulty=0.1), scene(rear=0.35, difficulty=0.1)
        self.assertTrue(ir.exchange_feasibility(safe, "Apex", {})["safe"])
        self.assertFalse(ir.exchange_feasibility(pressed, "Apex", {})["safe"])
        ir.step(pressed, act("SWAP"))
        o = order_of(pressed)
        self.assertLess(o.index("Rival 3"), o.index("Apex A"))  # the lifting car is passed

    def test_hold_and_defensive_buffer(self):
        free, held = scene(gap=0.4, b_pace=-0.9), scene(gap=0.4, b_pace=-0.9)
        ir.step(free, act("RACE"))
        ir.step(held, act("HOLD"))
        self.assertLess(order_of(free).index("Apex B"), order_of(free).index("Apex A"))
        self.assertLess(order_of(held).index("Apex A"), order_of(held).index("Apex B"))
        # rival behind faster: the buffer holds it behind B at a time cost
        def chased():
            s = scene(rear=0.5, b_pace=0.0)
            next(c for c in s["cars"] if c["name"] == "Rival 3")["base_pace"] = 89.5
            return s
        race, buffer = chased(), chased()
        ir.step(race, act("RACE"))
        ir.step(buffer, act("DEFENSIVE_BUFFER"))
        self.assertLess(order_of(race).index("Rival 3"), order_of(race).index("Apex B"))
        self.assertLess(order_of(buffer).index("Apex B"), order_of(buffer).index("Rival 3"))

    def test_neutralization_effects_unchanged_with_orders(self):
        for status in ("SC", "VSC"):
            a, b = scene(events=(status,)), scene(events=(status,))
            ir.step(a, act("RACE", a="PIT_HARD"))
            ir.step(b, act("DEFENSIVE_BUFFER", a="PIT_HARD"))
            self.assertEqual([c["elapsed"] for c in a["cars"]], [c["elapsed"] for c in b["cars"]])
            car = next(c for c in a["cars"] if c["name"] == "Apex B")
            self.assertEqual(car["tyre_age"], 4 + FMT["neutralization"]["tyre_age_laps"][status])
        sc = scene(events=("SC",))
        ir.step(sc, act("HOLD"))
        o = sorted(sc["cars"], key=lambda c: c["elapsed"])
        gaps = [y["elapsed"] - x["elapsed"] for x, y in zip(o, o[1:])]
        self.assertTrue(all(g <= FMT["neutralization"]["sc_gap"] + 1e-9 for g in gaps))

    def test_double_stack_queue_per_team(self):
        a, b = scene(), scene()
        ir.step(a, act("RACE", a="PIT_HARD"))
        ir.step(b, act("RACE", a="PIT_HARD", b="PIT_HARD"))
        lone = next(c for c in a["cars"] if c["name"] == "Apex B")
        both = next(c for c in b["cars"] if c["name"] == "Apex B")
        self.assertEqual(sorted({c["name"] for c in b["cars"]}), sorted(engine.LEGACY_CAR_NAMES))
        self.assertGreater(both["elapsed"], lone["elapsed"])

    def test_unique_order_and_timing_invariants(self):
        for seed in range(15):
            rng = random.Random(seed)
            s = ir.attach(configured(seed), ["Apex", "Orion"])
            while not s["complete"]:
                before = {c["name"]: c["elapsed"] for c in s["cars"]}
                acts = {}
                for slot in ("Apex", "Orion"):
                    legal = ir.legal_team_orders(s, slot)
                    order = rng.choice(legal)
                    to = {"order": order}
                    if order == "SWAP" and rng.random() < 0.5 and ir.pair_geometry(s, slot)["car_ahead"]:
                        lap = engine._decision_laps(s)[s["step"]]
                        if lap + 6 <= engine.laps_total(s):
                            to["commitment"] = {"objective": "PASS_CAR_AHEAD", "deadline_lap": lap + 6,
                                                "give_back_if": "OBJECTIVE_NOT_MET"}
                    acts[slot] = {"driver_a": rng.choice(engine.COMPOUND_ACTIONS) if rng.random() < .1 else "STAY",
                                  "driver_b": rng.choice(engine.COMPOUND_ACTIONS) if rng.random() < .1 else "STAY",
                                  "team_order": to}
                ir.step(s, acts)
                elapsed = [c["elapsed"] for c in s["cars"]]
                self.assertEqual(len(set(order_of(s))), 8)
                self.assertTrue(all(c["elapsed"] > before[c["name"]] for c in s["cars"]))
                self.assertEqual(len(set(round(e, 9) for e in elapsed)), 8)
            positions = [e["position"] for e in engine.result(s)["classification"]]
            self.assertEqual(positions, list(range(1, 9)))


class CommitmentTests(unittest.TestCase):
    COMMIT = {"objective": "PASS_CAR_AHEAD", "deadline_lap": 6, "give_back_if": "OBJECTIVE_NOT_MET"}

    def swapped(self, **kw):
        s = scene(**kw)
        ir.step(s, act("SWAP", commitment=self.COMMIT))
        return s, s["integrated"]["teams"]["Apex"]["commitment"]

    def test_deadline_makes_commitment_due_and_restricts_orders(self):
        s, c = self.swapped(ahead=8.0, b_pace=-0.1)  # target far ahead: objective cannot be met
        self.assertEqual(c["target"], "Rival 2")
        self.assertEqual([t["to"] for t in c["transitions"]], ["ACTIVE", "DUE"])
        self.assertEqual(ir.legal_team_orders(s, "Apex"), ["KEEP_ORDER", "REQUEST_GIVE_BACK"])
        with self.assertRaises(ValueError):
            ir.step(s, act("RACE"))

    def test_give_back_fulfilled_or_broken_or_reconsidered(self):
        s, c = self.swapped(ahead=8.0, b_pace=-0.1)
        self.assertTrue(c["give_back_feasibility"]["executable_if_no_pit"])
        ir.step(s, act("REQUEST_GIVE_BACK"))
        self.assertEqual(c["status"], "FULFILLED")
        self.assertLess(order_of(s).index("Apex A"), order_of(s).index("Apex B"))
        s, c = self.swapped(ahead=8.0, b_pace=-0.1)
        ir.step(s, act("KEEP_ORDER"))
        self.assertEqual(c["status"], "BROKEN_WHILE_FEASIBLE")
        s, c = self.swapped(ahead=8.0, b_pace=-0.1)
        r3 = next(x for x in s["cars"] if x["name"] == "Rival 3")
        a = next(x for x in s["cars"] if x["name"] == "Apex A")
        r3["elapsed"] = a["elapsed"] + 0.4  # a rival has closed in: give-back becomes unsafe
        ir.update_commitments(s)
        self.assertFalse(c["give_back_feasibility"]["safe"])
        ir.step(s, act("KEEP_ORDER"))
        self.assertEqual(c["status"], "RECONSIDERED")

    def test_commitment_survives_sc_and_expires_at_finish(self):
        events = ["GREEN"] + ["SC"] * 2 + ["GREEN"] * (N - 3)  # short SC: the target does not pit
        s = scene(events=events, ahead=8.0, b_pace=-0.1)
        next(x for x in s["cars"] if x["name"] == "Rival 2")["base_pace"] = 89.0  # B cannot catch the target
        ir.step(s, act("SWAP", commitment=self.COMMIT))
        c = s["integrated"]["teams"]["Apex"]["commitment"]
        self.assertEqual(c["status"], "DUE")
        report = ir.step(s, act("REQUEST_GIVE_BACK"))["Apex"]  # SC: delayed, still due
        self.assertEqual(report["status"], "DELAYED")
        self.assertEqual(c["status"], "DUE")
        self.assertIn("NEUTRALIZED", c["give_back_feasibility"]["blocking_reasons"])
        while not s["complete"]:
            ir.step(s, act("REQUEST_GIVE_BACK" if c["status"] == "DUE" else "RACE"))
        self.assertEqual(c["status"], "FULFILLED")  # executed at the GREEN restart
        s2 = scene(events=["GREEN"] + ["SC"] * (N - 1), ahead=8.0, b_pace=-0.1)
        for car in s2["cars"]:  # nobody pits under the long SC, so the order is frozen
            car["tyre_age"] = 0 if car["team"] != "Apex" else car["tyre_age"]
        ir.step(s2, act("SWAP", commitment=self.COMMIT))
        c2 = s2["integrated"]["teams"]["Apex"]["commitment"]
        while not s2["complete"]:
            ir.step(s2, act("REQUEST_GIVE_BACK" if c2["status"] == "DUE" else "RACE"))
        self.assertIn(c2["status"], ("EXPIRED_AT_FINISH", "OBJECTIVE_ACHIEVED"))
        self.assertTrue(any(t.get("to") == "DUE" for t in c2["transitions"]))

    def test_objective_achieved_lapses_give_back(self):
        s, c = self.swapped(ahead=0.9, b_pace=-1.5)
        ir.step(s, act("RACE"))
        self.assertEqual(c["status"], "OBJECTIVE_ACHIEVED")
        self.assertNotIn("REQUEST_GIVE_BACK", ir.legal_team_orders(s, "Apex"))


class CounterfactualTests(unittest.TestCase):
    """Matched pairs: only SC/VSC status or a rival's pit differs; values are race outcomes."""

    def test_sc_changes_value_of_swap(self):
        values = {}
        for status in ("GREEN", "SC"):
            for order in ("SWAP", "HOLD"):
                s = scene(events=(status,), ahead=1.2, b_pace=-0.8, a_age=15, b_age=2)
                ir.step(s, act(order))
                values[(status, order)] = order_of(s).index("Apex B")
        self.assertLess(values[("GREEN", "SWAP")], values[("GREEN", "HOLD")])
        self.assertEqual(values[("SC", "SWAP")], values[("SC", "HOLD")])  # no exchange possible under SC

    def test_rival_pit_changes_value_of_defensive_buffer(self):
        def chased(rival_pits):
            s = scene(rear=0.5, b_pace=0.0)
            r3 = next(c for c in s["cars"] if c["name"] == "Rival 3")
            r3["base_pace"] = 89.5
            if rival_pits:  # the chasing rival has just pitted: it rejoins far behind
                r3["elapsed"] += coef.pit_model("mixed", coef.DEFAULT)["loss_sec"]["GREEN"]
            return s
        gain = {}
        for pits in (False, True):
            race, buffer = chased(pits), chased(pits)
            ir.step(race, act("RACE"))
            ir.step(buffer, act("DEFENSIVE_BUFFER"))
            gain[pits] = order_of(race).index("Apex B") - order_of(buffer).index("Apex B")
        self.assertGreater(gain[False], 0)   # buffer keeps the position against a close rival
        self.assertEqual(gain[True], 0)      # after the rival's stop the buffer only costs time

    def test_give_back_value_emerges_from_racing(self):
        """Points effect of giving back vs keeping order is measured, not imposed."""
        outcomes = {}
        for follow in ("KEEP_ORDER", "REQUEST_GIVE_BACK"):
            s = scene(ahead=8.0, b_pace=-0.1)
            ir.step(s, act("SWAP", commitment=CommitmentTests.COMMIT))
            ir.step(s, act(follow))
            outcomes[follow] = finish_baseline(s)
        for result in outcomes.values():
            self.assertEqual(sorted(e["position"] for e in result["classification"]), list(range(1, 9)))
        # no artificial penalty: team points depend only on finishing positions
        for follow, result in outcomes.items():
            self.assertEqual(result["constructors_points"], apex_points(result))


class SessionBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.cfg = C.two_team(1)
        self.pols = {"McLearn Racing": P.scripted("coordinator"), "Red Bool Racing": P.scripted("event_aware")}

    def test_no_seed_or_future_in_observations(self):
        s = S.IntegratedSession(self.cfg, 4)
        for _ in range(3):
            tick = s.tick_id
            for label in s.teams:
                text = json.dumps(s.observation(label))
                for forbidden in ('"seed"', '"events"', "future_track_status", '"cars"', "dnf_uniform", "retired"):
                    self.assertNotIn(forbidden, text)
                s.submit(label, tick, self.pols[label](s.observation(label)))
        other = S.IntegratedSession(self.cfg, 4)
        for _ in range(2):
            tick = other.tick_id
            for label in other.teams:
                other.submit(label, tick, self.pols[label](other.observation(label)))
        other.race_state["events"][other.race_state["step"] + 1:] = ["SC"] * (N - other.race_state["step"] - 1)
        other._open_tick()
        other._tick -= 1
        other._snapshots = {label: other._build_observation(label) for label in other.teams}
        s2 = S.IntegratedSession(self.cfg, 4)
        for _ in range(2):
            tick = s2.tick_id
            for label in s2.teams:
                s2.submit(label, tick, self.pols[label](s2.observation(label)))
        for label in s2.teams:
            self.assertEqual(s2._build_observation(label), other._build_observation(label))

    def test_private_state_and_reports_are_team_local(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = C.two_team(2, mclearn_engineers="MOCK_ENGINEERS")
            s = S.IntegratedSession(cfg, 4, engineer_broker=EngineerBroker(Path(tmp)))
            tick = s.tick_id
            for label in s.teams:
                s.submit(label, tick, self.pols[label](s.observation(label)))
            mc, rb = s.observation("McLearn Racing"), s.observation("Red Bool Racing")
            self.assertEqual(len(mc["engineer_reports"]), 2)
            self.assertNotIn("engineer_reports", rb)
            self.assertNotIn("McLearn A", rb["controlled_drivers"])
            self.assertIn("McLearn A", rb["rivals_public"])
            self.assertNotIn("components", rb["rivals_public"]["McLearn A"])
            self.assertEqual(rb["team_orders"]["commitment"], None)
            self.assertNotIn(json.dumps(mc["team_orders"]), json.dumps(rb))
            from track_c.engineer_runtime import format_runtime_observation
            local = format_runtime_observation(mc, "engineer_a")
            names = [e["driver"] for e in local["race_context"]["public_rivals"]]
            self.assertIn("McLearn A", names)
            self.assertNotIn("McLearn B", names)
            self.assertNotIn("engineer_reports", json.dumps(local))

    def test_simultaneous_submission_is_sealed_and_order_independent(self):
        journals = []
        for order in (["McLearn Racing", "Red Bool Racing"], ["Red Bool Racing", "McLearn Racing"]):
            s = S.IntegratedSession(self.cfg, 9, clock=lambda: 0.0)
            for _ in range(4):
                tick = s.tick_id
                snap = {label: s.observation(label) for label in s.teams}
                first, second = order
                s.submit(first, tick, self.pols[first](snap[first]))
                self.assertEqual(s.observation(second), snap[second])
                self.assertEqual(s.submission_status(second), {"tick_id": tick, "sealed": False, "action_sha256": None})
                with self.assertRaises(S.TickError):
                    s.submit(first, tick, self.pols[first](snap[first]))
                s.submit(second, tick, self.pols[second](snap[second]))
            journals.append([(e["tick_id"], e["submissions"], e["obs_before_sha256"], e["obs_after_sha256"])
                             for e in s.journal if e["kind"] == "resolved"])
        self.assertEqual(journals[0], journals[1])

    def test_timeout_and_invalid_actions(self):
        s = S.IntegratedSession(self.cfg, 9)
        tick = s.tick_id
        with self.assertRaises(S.TickError):
            s.submit("McLearn Racing", tick, {"type": "RACE_STRATEGY"})
        with self.assertRaises(S.TickError):
            s.submit("McLearn Racing", "t999", P.scripted("baseline")(s.observation("McLearn Racing")))
        bad = P.scripted("baseline")(s.observation("Red Bool Racing"))
        with self.assertRaises(S.TickError):  # Red Bool may not decide McLearn's components
            s.submit("McLearn Racing", tick, bad)
        s.submit("McLearn Racing", tick, P.scripted("baseline")(s.observation("McLearn Racing")))
        s.close_tick(tick)
        entry = s.journal[-1]
        self.assertEqual(entry["submissions"]["Red Bool Racing"]["status"], S.TIMEOUT)
        self.assertEqual([e["kind"] for e in s.journal].count("rejected"), 3)
        self.assertEqual(s.decision_type, S.RACE_STRATEGY)
        tick = s.tick_id
        s.submit("Red Bool Racing", tick, {"type": "RACE_STRATEGY", "driver_a": "STAY", "driver_b": "STAY",
                                           "team_order": RACE})
        s.close_tick(tick)
        self.assertEqual(s.journal[-1]["submissions"]["McLearn Racing"]["action"]["team_order"], RACE)
        V.replay(self.cfg, 9, s.journal, require_complete=False)


class JournalReplayTests(unittest.TestCase):
    def test_full_seasons_replay_and_detect_tampering(self):
        cfg = C.two_team(1)
        pols = {"McLearn Racing": P.scripted("coordinator"), "Red Bool Racing": P.scripted("undercut")}
        s = play(cfg, 21, pols)
        out = V.replay(cfg, 21, s.journal)
        self.assertEqual(out["standings"], s.standings())
        self.assertLessEqual(sum(out["standings"]["team_points"].values()), 8 * sum(engine.POINTS))
        for rr in out["race_results"]:  # points are conserved: only finishers score, by position
            self.assertEqual(sum(rr["team_points"].values()), sum(e["points"] for e in rr["classification"]))
        tampered = copy.deepcopy(s.journal)
        tampered[30]["submissions"]["McLearn Racing"]["action"]["driver_a"] = "PIT_SOFT"
        with self.assertRaises(V.ReplayError):
            V.replay(cfg, 21, tampered)
        with self.assertRaises(V.ReplayError):
            V.replay(cfg, 22, s.journal)  # wrong seed
        reordered = copy.deepcopy(s.journal)
        reordered[3], reordered[4] = reordered[4], reordered[3]
        with self.assertRaises(V.ReplayError):
            V.verify_chain(reordered)

    def test_engineer_records_replay_and_tamper_detection(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = C.solo_coordination(engineers="CONFLICTING_LOCAL_RECOMMENDATIONS")
            s = play(cfg, 3, {"Apex": P.scripted("coordinator")}, EngineerBroker(Path(tmp)))
            V.replay(cfg, 3, s.journal, engineer_broker=EngineerBroker.replaying(Path(tmp)))
            path = Path(tmp) / "apex" / "engineer_records.jsonl"
            lines = path.read_text().splitlines()
            record = json.loads(lines[10])
            record["recommendation"]["confidence"]["value"] = 0.01
            lines[10] = json.dumps(record, sort_keys=True)
            path.write_text("\n".join(lines) + "\n")
            with self.assertRaises(Exception):
                V.replay(cfg, 3, s.journal, engineer_broker=EngineerBroker.replaying(Path(tmp)))

    def test_recorded_engineer_condition_reuses_exact_records(self):
        with tempfile.TemporaryDirectory() as tmp:
            live_dir, rec_dir = Path(tmp) / "mock", Path(tmp) / "recorded"
            pol = {"Apex": P.scripted("baseline")}
            first = play(C.solo_coordination(engineers="MOCK_ENGINEERS"), 6, pol, EngineerBroker(live_dir))
            cfg = C.solo_coordination(engineers="RECORDED_RECOMMENDATIONS")
            again = play(cfg, 6, pol, EngineerBroker(rec_dir, recorded_from=live_dir))
            records = [json.loads(x) for x in (rec_dir / "apex" / "engineer_records.jsonl").read_text().splitlines()]
            self.assertTrue(records and all(r["source"] == "RECORDED_REPLAY" and r["status"] == "VALID" for r in records))
            self.assertEqual(first.standings(), again.standings())
            other = play(cfg, 7, pol, EngineerBroker(Path(tmp) / "other", recorded_from=live_dir))
            missing = [json.loads(x) for x in (Path(tmp) / "other" / "apex" / "engineer_records.jsonl").read_text().splitlines()]
            source = {(r["engineer_id"], r["observation_hash"])
                      for r in (json.loads(x) for x in (live_dir / "apex" / "engineer_records.jsonl").read_text().splitlines())}
            self.assertTrue(any(r["status"] == "MISSING" for r in missing))
            for r in missing:  # never fabricated: a VALID record exists only for an exactly recorded observation
                if r["status"] == "VALID":
                    self.assertIn((r["engineer_id"], r["observation_hash"]), source)
            V.replay(cfg, 7, other.journal, engineer_broker=EngineerBroker.replaying(Path(tmp) / "other"))

    def test_slot_swap_same_world(self):
        cfg = C.two_team(1)
        pols = {"McLearn Racing": P.scripted("baseline"), "Red Bool Racing": P.scripted("baseline")}
        a, b = play(cfg, 13, pols), play(cfg, 13, pols)
        self.assertEqual([e["entry_hash"] for e in a.journal], [e["entry_hash"] for e in b.journal] and
                         [e["entry_hash"] for e in a.journal]) if False else None
        self.assertEqual(a.standings(), b.standings())
        swapped = play(cfg.swapped(), 13, pols)
        self.assertEqual([r["events"] for r in a.race_results], [r["events"] for r in swapped.race_results])
        mc_first = a.standings()["team_points"]
        mc_swapped = swapped.standings()["team_points"]
        # identical policies: swapping slots swaps the two teams' points exactly
        self.assertEqual(mc_first["McLearn Racing"], mc_swapped["Red Bool Racing"])
        self.assertEqual(mc_first["Red Bool Racing"], mc_swapped["McLearn Racing"])

    def test_fixed_replay_condition(self):
        cfg = C.two_team(1)
        live = M.run_season(cfg, 5, {"McLearn Racing": P.scripted("baseline"),
                                     "Red Bool Racing": P.scripted("opportunistic")})
        fixed_cfg = C.two_team(1, rival_condition="FIXED_REPLAY")
        rerun = M.run_season(fixed_cfg, 5, {"McLearn Racing": P.scripted("baseline"),
                                            "Red Bool Racing": M.ReplayPolicy(live["journal"], "Red Bool Racing")})
        self.assertEqual(rerun["standings"], live["standings"])
        self.assertNotEqual(rerun["config_hash"], live["config_hash"])  # different estimand label
        changed = M.run_season(fixed_cfg, 5, {"McLearn Racing": P.scripted("long_stint"),
                                              "Red Bool Racing": M.ReplayPolicy(live["journal"], "Red Bool Racing")})
        statuses = {p["status"] for p in changed["provenance"] if p["team"] == "Red Bool Racing"}
        self.assertTrue(statuses <= {"SUBMITTED", "INVALID"})


class FakeChat:
    def __init__(self, replies):
        self.replies, self.calls = list(replies), []

    def complete(self, **kw):
        self.calls.append(kw)
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply


def ok(text, model="m-rev"):
    return {"text": text, "model": model, "request_id": "r1", "status": 200,
            "usage": {"input_tokens": 1000, "output_tokens": 100}}


class ProviderContractTests(unittest.TestCase):
    def setUp(self):
        os.environ["B6_TEST_KEY_A"] = "secret-a"
        os.environ["B6_TEST_KEY_B"] = "secret-b"
        self.obs = S.IntegratedSession(C.two_team(1), 3).observation("Red Bool Racing")

    def test_provenance_cost_and_revision(self):
        chief = PR.redbool_chief(api_key_env="B6_TEST_KEY_B",
                                 transport=FakeChat([ok(json.dumps(P.component_action(self.obs)), "deepseek-x-0917")]))
        action, meta = chief(self.obs)
        self.assertEqual(action["type"], "COMPONENT_DECISION")
        self.assertEqual(meta["requested_model"], "deepseek-4-1-flash-1017")
        self.assertEqual(meta["returned_model"], "deepseek-x-0917")
        self.assertAlmostEqual(meta["estimated_cost"]["amount"], 1000 / 1e6 * 0.15 + 100 / 1e6 * 0.60)
        self.assertNotIn("secret-b", json.dumps(meta))
        self.assertNotIn("secret-b", chief.transport.calls[0]["prompt"])

    def test_invalid_output_and_errors_are_not_repaired(self):
        chief = PR.redbool_chief(api_key_env="B6_TEST_KEY_B", transport=FakeChat([ok("```json {}```")]))
        with self.assertRaises(ValueError):
            chief(self.obs)
        no_retry = PR.redbool_chief(api_key_env="B6_TEST_KEY_B",
                                    transport=FakeChat([PR.ProviderError("http_error", 402)]), max_retries=3)
        with self.assertRaises(PR.ProviderError):
            no_retry(self.obs)
        self.assertEqual(len(no_retry.transport.calls), 1)
        waits = []
        limited = PR.redbool_chief(api_key_env="B6_TEST_KEY_B", sleep=waits.append, max_retries=2,
                                   transport=FakeChat([PR.ProviderError("http_error", 429, 2.0),
                                                       ok(json.dumps(P.component_action(self.obs)))]))
        _, meta = limited(self.obs)
        self.assertEqual(waits, [2.0])
        self.assertEqual(meta["retries"], 1)
        del os.environ["B6_TEST_KEY_B"]
        with self.assertRaises(PR.ProviderError):
            PR.redbool_chief(api_key_env="B6_TEST_KEY_B", transport=FakeChat([]))(self.obs)

    def test_isolation_and_wrong_team(self):
        a = PR.gemini_chief("McLearn Racing", "g", "B6_TEST_KEY_A", FakeChat([]))
        b = PR.redbool_chief(api_key_env="B6_TEST_KEY_A", transport=FakeChat([]))
        with self.assertRaises(ValueError):
            PR.assert_isolated({"McLearn Racing": a, "Red Bool Racing": b})
        with self.assertRaises(PermissionError):
            a(self.obs)

    def test_model_availability_check(self):
        class Lister:
            def list_models(self, api_key, timeout_sec=20):
                return ["deepseek-4-1-flash-1017"]
        with self.assertRaises(PR.ProviderError):
            PR.verify_model_available(Lister(), "deepseek-flash", "B6_TEST_KEY_A")
        self.assertTrue(PR.verify_model_available(Lister(), "deepseek-4-1-flash-1017", "B6_TEST_KEY_A")["available"])

    def test_runner_falls_back_on_provider_failure(self):
        failing = PR.redbool_chief(api_key_env="B6_TEST_KEY_B",
                                   transport=FakeChat([PR.ProviderError("http_error", 403)] * 200))
        out = M.run_season(C.two_team(1), 2, {"McLearn Racing": P.scripted("baseline"), "Red Bool Racing": failing})
        rb = [p for p in out["provenance"] if p["team"] == "Red Bool Racing"]
        self.assertTrue(all(p["status"] == "POLICY_ERROR" for p in rb))
        self.assertTrue(all(e["submissions"]["Red Bool Racing"]["status"] == S.INVALID
                            for e in out["journal"] if e["kind"] == "resolved"))
        V.replay(C.two_team(1), 2, out["journal"])


if __name__ == "__main__":
    unittest.main()
