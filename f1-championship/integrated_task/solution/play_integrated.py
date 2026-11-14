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


def main():
    call("rules")
    obs = call("observe")["observation"]
    policy = scripted("coordinator")
    decisions = 0
    while obs["decision_type"] != "CHAMPIONSHIP_COMPLETE":
        action = policy(obs)
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
