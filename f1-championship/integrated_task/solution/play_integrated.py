#!/usr/bin/env python3
"""Oracle for the integrated task: the published coordinator policy played through f1ctl."""
import json
import subprocess
import sys

sys.path.insert(0, __file__.rsplit("/", 1)[0])
from policies import scripted  # noqa: E402  (copy of f1pitwall/integrated/policies.py)


def call(*args):
    out = subprocess.run(["f1ctl", *args], capture_output=True, text=True)
    return json.loads(out.stdout)


def weekend_action(obs):
    """2.2.0 C5 smoke policy (not a reference): spend practice on qualifying simulations of the two non-default
    setups, then qualify both cars on the setup with the lower estimated tyre degradation, best of two runs."""
    view = obs["weekend"]
    if obs["decision_type"] == "PRACTICE":
        setups = sorted(view["practice"]["known_setup_estimates"])
    else:
        setups = sorted(view["qualifying"]["setup_options"])
    others = [s for s in setups if s != "balanced"] or setups
    if obs["decision_type"] == "PRACTICE":
        budget = view["practice"]["laps_budget_remaining"]
        laps = {k: budget[k] // 2 if view["practice"]["session_index"] == 1 else budget[k] for k in budget}
        return {"type": "PRACTICE",
                "driver_a": {"program": "QUALI_SIM", "setup_id": others[0], "laps": laps["driver_a"]},
                "driver_b": {"program": "LONG_RUN", "setup_id": others[-1], "laps": laps["driver_b"]}}
    wear = view["qualifying"]["tyre_wear_estimates"]
    best = min(wear, key=lambda s: (wear[s]["mean"], s)) if wear else "balanced"
    return {"type": "QUALIFYING", "driver_a": {"setup_id": best, "run_plan": "TWO_RUN"},
            "driver_b": {"setup_id": best, "run_plan": "TWO_RUN"}}


def main():
    call("rules")
    obs = call("observe")["observation"]
    policy = scripted("coordinator")
    decisions = 0
    while obs["decision_type"] != "CHAMPIONSHIP_COMPLETE":
        action = weekend_action(obs) if obs["decision_type"] in ("PRACTICE", "QUALIFYING") else policy(obs)
        if obs.get("engineer_reports"):
            action["consumed_reports"] = [r["record_hash"] for r in obs["engineer_reports"] if r["status"] == "VALID"]
        reply = call("act", obs["decision_id"], json.dumps(action))
        if not reply.get("ok"):
            print(json.dumps(reply), file=sys.stderr)
            return 1
        obs = reply["observation"]
        decisions += 1
    print(json.dumps({"decisions": decisions, "team_standings": obs["championship"]["team_standings"]}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
