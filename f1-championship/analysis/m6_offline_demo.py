#!/usr/bin/env python3
"""API-free M6 demonstration; this is not an agent evaluation."""

from __future__ import annotations

import json
import sys
from pathlib import Path

TASK = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(TASK / "src"), str(TASK)]

from track_c.driver_objectives import (  # noqa: E402
    compliance_probability, load_m6_config, public_compliance_observation,
    resolve_order_compliance, wdc_standings,
)


def main():
    config = load_m6_config()
    demo = config["demo"]
    standings = wdc_standings(demo["driver_points"], demo["teams"], demo["races_remaining"])
    leader = next(row for row in standings["drivers"] if row["driver"] == demo["affected_driver"])
    probability = compliance_probability(leader["gap_to_teammate"], demo["races_remaining"],
                                         demo["order"], config)
    output = {"kind": "SYNTHETIC_FUNCTIONAL_DEMO_NOT_AGENT_EVIDENCE",
              "public_observation": public_compliance_observation(standings, config, True),
              "conflicting_order": resolve_order_compliance(
                  demo["order"], demo["affected_driver"], probability,
                  enabled=True, seeded_draw=demo["seeded_draw"]),
              "m6_disabled_control": resolve_order_compliance(
                  demo["order"], demo["affected_driver"], probability, enabled=False)}
    print(json.dumps(output, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
