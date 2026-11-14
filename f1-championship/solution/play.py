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
    race = obs["race_progress"]
    status = race["track_status"]
    threshold = {"SC": 6, "VSC": 8}.get(status, 99)
    wants = {}
    for key, car in race["drivers"].items():
        worn_soft = car["compound"] == "SOFT" and car["tyre_age"] >= 8 and race["decision_index"] == 1
        wants[key] = car["tyre_age"] >= threshold or worn_soft
    if wants["driver_a"] and wants["driver_b"]:
        older = max(("driver_a", "driver_b"), key=lambda k: race["drivers"][k]["tyre_age"])
        wants = {k: k == older for k in wants}
    return {"type": "RACE_STRATEGY",
            "driver_a": "PIT" if wants["driver_a"] else "STAY",
            "driver_b": "PIT" if wants["driver_b"] else "STAY"}


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
