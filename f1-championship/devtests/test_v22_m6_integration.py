from __future__ import annotations

import copy
from dataclasses import replace
import unittest

from devtests.test_b6_integration import act, scene
from f1pitwall.integrated import config as C
from f1pitwall.integrated import session as S
from f1pitwall.integrated import verify as V
from f1pitwall.journal import seal_entry
from devtests.v22_helpers import assert_no_secrets as secret_guard


def assert_no_secrets(event):
    class Wrapper:
        def assertNotIn(self, *args, **kwargs):
            pass
    secret_guard(Wrapper(), event)


def fixture(enabled=True):
    cfg = replace(C.with_version(C.two_team(1), "2.2.0"), m6_compliance=enabled)
    driver = S.IntegratedSession(cfg, 1, clock=lambda: 0.0)
    for label in driver.teams:
        obs = driver.observation(label)
        decisions = [{"driver": driver_name, "component": name, "action": "USE"}
                     for driver_name, info in obs["controlled_drivers"].items()
                     for name in info["components"]]
        driver.submit(label, driver.tick_id, {"type": "COMPONENT_DECISION", "decisions": decisions})
    driver.state.race_index = 7
    driver.race_state = scene(b_pace=0.1)
    driver.race_state["integrated"]["controlled"].append("Orion")
    driver.race_state["integrated"]["teams"]["Orion"] = {
        "commitment": None, "closed_commitments": [], "order_log": []}
    driver.race_state["integrated"]["teams"]["Apex"]["commitment"] = {
        "objective": "PASS_CAR_AHEAD", "target": "Rival 2", "deadline_lap": 36,
        "give_back_if": "OBJECTIVE_NOT_MET", "promoted": "driver_a", "yielded": "driver_b",
        "status": "DUE", "created_decision": 1, "give_back_attempts": 0, "transitions": []}
    for name, points in (("Apex A", 50), ("Apex B", 18)):
        driver.state.driver_points[name] = points
    driver._open_tick()
    return driver


def request(driver):
    for label in driver.teams:
        order = "REQUEST_GIVE_BACK" if label == "McLearn Racing" else "RACE"
        driver.submit(label, driver.tick_id, {"type": "RACE_STRATEGY", **act(order)["Apex"]})


def drive(config, seed):
    driver = S.IntegratedSession(config, seed, clock=lambda: 0.0)
    while driver.decision_type != S.CHAMPIONSHIP_COMPLETE:
        for label in sorted(driver.teams):
            obs = driver.observation(label)
            if obs["decision_type"] == "COMPONENT_DECISION":
                decisions = [{"driver": d, "component": name,
                              "action": "USE" if "USE" in info["components"][name]["legal_actions"] else "REPLACE"}
                             for d, info in obs["controlled_drivers"].items() for name in info["components"]]
                action = {"type": "COMPONENT_DECISION", "decisions": decisions}
            else:
                action = {"type": "RACE_STRATEGY", **act("RACE")["Apex"]}
            driver.submit(label, driver.tick_id, action)
    return driver


class M6IntegrationTests(unittest.TestCase):
    def test_m6_decline_then_retry_preserves_request_and_commitment(self):
        driver = fixture()
        request(driver)
        commitment = driver.race_state["integrated"]["teams"]["Apex"]["commitment"]
        assert len(driver._last_order_events) == 1
        event = driver._last_order_events[0]
        assert event["team"] == "McLearn Racing"
        assert event["event"] == {
            "type": "ORDER_DECLINED", "driver": "McLearn A", "order": "REQUEST_GIVE_BACK",
            "effective_order": "RACE", "public_reason": "WDC_COMPLIANCE_PROFILE",
            "compliance_probability": 0.273125}
        assert_no_secrets(event)
        assert commitment["status"] == "DUE"
        assert commitment["give_back_attempts"] == 0
        assert driver.race_state["integrated"]["teams"]["Apex"]["order_log"][-1]["order"] == "REQUEST_GIVE_BACK"
        assert driver.race_state["actions"][-1]["Apex"]["team_order"]["order"] == "REQUEST_GIVE_BACK"
        request(driver)
        assert commitment["status"] == "FULFILLED"
        assert commitment["give_back_attempts"] == 1
        assert driver._last_order_events == []


    def test_m6_public_observation_uses_public_roles_without_secrets(self):
        driver = fixture()
        block = driver.observation("McLearn Racing")["championship"]["m6_driver_objectives"]
        assert block["m6_enabled"] is True
        assert block["races_remaining"] == 1
        promoted = next(row for row in block["driver_standings"] if row["driver"] == "McLearn A")
        assert promoted["gap_to_teammate"] == 32
        assert promoted["teammate"] == "McLearn B"
        assert promoted["team"] == "McLearn Racing"
        assert promoted["order_compliance_probability"]["REQUEST_GIVE_BACK"] == 0.273125
        assert_no_secrets(block)


    def test_m6_disabled_full_season_is_byte_identical_and_no_draw_blocks(self):
        first = drive(C.two_team(1), 1)
        second = drive(replace(C.two_team(1), m6_compliance=False), 1)
        assert first.journal == second.journal
        assert first.race_results == second.race_results
        assert first.standings() == second.standings()
        cfg = replace(C.with_version(C.two_team(1), "2.2.0"), m6_compliance=False)
        disabled = drive(cfg, 1)
        assert all("order_events" not in entry for entry in disabled.journal)
        assert "m6_driver_objectives" not in disabled.observation("McLearn Racing")["championship"]


    def test_full_season_replay_and_resealed_order_event_tampering(self):
        for seed in (1, 2):
            cfg = replace(C.with_version(C.two_team(1), "2.2.0"), m6_compliance=True)
            driver = drive(cfg, seed)
            result = V.replay(cfg, seed, list(driver.journal), require_complete=True)
            assert result["complete"] is True
            assert result["standings"] == driver.standings()
            tampered = copy.deepcopy(driver.journal)
            for entry in tampered:
                if "order_events" in entry:
                    entry["order_events"].append({"team": "forged", "event": {"type": "ORDER_DECLINED"}})
                    break
            else:
                continue
            previous = "0" * 64
            for entry in tampered:
                entry["prev_hash"] = previous
                entry["entry_hash"] = seal_entry(entry, previous)["entry_hash"]
                previous = entry["entry_hash"]
            try:
                V.replay(cfg, seed, tampered, require_complete=False)
            except V.ReplayError as exc:
                assert "order events" in str(exc)
            else:
                raise AssertionError("forged order event was accepted")
