#!/usr/bin/env python3
"""P0 oracle policy: plays the championship through f1ctl using only observations.

Deliberately simple; it exists to exercise the sealed sidecar end to end. The
P2 reference planner replaces it.
"""

import json
import subprocess
import sys

F1CTL = "f1ctl"


def call(*args):
    proc = subprocess.run([F1CTL, *args], capture_output=True, text=True)
    response = json.loads(proc.stdout)
    if not response.get("ok"):
        raise SystemExit(f"f1ctl {args[0]} failed: {response}")
    return response


def component_action(obs):
    decisions = []
    for driver, state in obs["controlled_drivers"].items():
        for component, info in state["components"].items():
            action = "USE" if "USE" in info["legal_actions"] else "REPLACE"
            decisions.append({"driver": driver, "component": component, "action": action})
    return {"type": "COMPONENT_DECISION", "decisions": decisions}


def race_action(obs):
    """Public baseline: pit cheaply under SC/VSC, before a tyre passes its published life, or when
    a SOFT is worn at the first decision; choose the compound from the laps remaining; make sure the
    two-compound rule is met by the last stop; avoid double stacks unless the rule needs both."""
    race = obs["race_progress"]
    status = race["track_status"]
    legal = race.get("legal_actions", ["PIT", "STAY"])
    threshold = {"SC": 6, "VSC": 8}.get(status, 99)
    last = race["decision_index"] == race["decision_count"]
    life = race.get("tyre_life_laps")
    segment = race.get("segment_laps", 4)
    remaining = race.get("laps_remaining", 99)
    wants, must = {}, {}
    for key, car in race["drivers"].items():
        worn_soft = car["compound"] == "SOFT" and car["tyre_age"] >= 8 and race["decision_index"] == 1
        # Long races: stop once the tyre has reached its published life, unless the race is nearly
        # over (with fewer than 3 segments left the cliff costs less than a green pit stop).
        end_of_life = (life is not None and car["tyre_age"] >= life[car["compound"]]
                       and remaining >= 3 * segment)
        must[key] = last and "compounds_used" in car and len(car["compounds_used"]) < 2
        wants[key] = (car["tyre_age"] >= threshold and remaining > segment) or worn_soft or end_of_life or must[key]
    if wants["driver_a"] and wants["driver_b"] and not (must["driver_a"] and must["driver_b"]):
        keep = [k for k in wants if must[k]] or [max(("driver_a", "driver_b"),
                                                     key=lambda k: race["drivers"][k]["tyre_age"])]
        wants = {k: k == keep[0] for k in wants}
    return {"type": "RACE_STRATEGY",
            "driver_a": _pit_choice(race, "driver_a", legal) if wants["driver_a"] else "STAY",
            "driver_b": _pit_choice(race, "driver_b", legal) if wants["driver_b"] else "STAY"}


def _pit_choice(race, key, legal):
    if "PIT" in legal:
        return "PIT"
    if legal == ["STAY", "PIT_MEDIUM"]:
        return "PIT_MEDIUM"
    remaining = race["laps_remaining"]
    compound = "SOFT" if remaining <= 6 else "MEDIUM" if remaining <= 14 else "HARD"
    used = set(race["drivers"][key].get("compounds_used", []))
    if used == {compound}:
        compound = {"SOFT": "MEDIUM", "HARD": "MEDIUM",
                    "MEDIUM": "SOFT" if remaining <= 10 else "HARD"}[compound]
    return "PIT_" + compound


def main():
    call("rules")
    obs = call("observe")["observation"]
    decisions = 0
    while obs["decision_type"] != "CHAMPIONSHIP_COMPLETE":
        action = component_action(obs) if obs["decision_type"] == "COMPONENT_DECISION" else race_action(obs)
        obs = call("act", obs["decision_id"], json.dumps(action))["observation"]
        decisions += 1
    standings = obs["championship"]["team_standings"]
    print(json.dumps({"decisions": decisions, "team_standings": standings}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
