"""Representative mid-season scenarios and counterfactual/control pairs (synthetic).

A scenario is an 8-race calendar plus the state at race index 5. History
(races 0-4) is produced by public rules: rivals use the public threshold rule,
Apex uses one of two plausible early-season habits. The remaining three races
form the reduced season that the exact solver optimizes.

Scores are reported over every generated scenario. Pairs are diagnostics and
are never used to select scenarios.
"""

from __future__ import annotations

import copy
import random
from typing import Any, Dict, List, Mapping

from track_a_solver import Solver, after_race, prepare  # noqa: F401

from f1pitwall import coefficients as coef
from f1pitwall.championship import RaceEntry, new_championship_state
from f1pitwall.championship_transition import initial_inventory

GENERATOR_SEED = 2026_11_14
HISTORY_RACES = 5

# Synthetic placeholder parameter ranges per archetype: (stress, overtaking, tyre_degradation).
ARCHETYPE_RANGES = {
    "street": ((0.35, 0.50), (0.80, 0.95), (0.30, 0.45)),
    "high_speed": ((0.80, 0.95), (0.20, 0.35), (0.40, 0.55)),
    "high_degradation": ((0.55, 0.70), (0.35, 0.50), (0.85, 1.00)),
    "wet_prone": ((0.45, 0.60), (0.50, 0.65), (0.55, 0.70)),
    "mixed": ((0.50, 0.70), (0.40, 0.60), (0.45, 0.70)),
}
EARLY_HABITS = ("rival_rule", "always_use")


def _track(name: str, archetype: str, rng: random.Random) -> RaceEntry:
    s, o, d = ARCHETYPE_RANGES[archetype]
    return RaceEntry(name=name, archetype=archetype,
                     power_unit_stress=round(rng.uniform(*s), 3),
                     overtaking_difficulty=round(rng.uniform(*o), 3),
                     tyre_degradation=round(rng.uniform(*d), 3),
                     synthetic_placeholder=True)


def midpoint_track(name: str, archetype: str) -> RaceEntry:
    s, o, d = ARCHETYPE_RANGES[archetype]
    return RaceEntry(name=name, archetype=archetype, power_unit_stress=round(sum(s) / 2, 3),
                     overtaking_difficulty=round(sum(o) / 2, 3), tyre_degradation=round(sum(d) / 2, 3),
                     synthetic_placeholder=True)


def generate_specs(count: int, seed: int = GENERATOR_SEED) -> List[Dict[str, Any]]:
    rng = random.Random(seed)
    specs = []
    for index in range(count):
        archetypes = [rng.choice(sorted(ARCHETYPE_RANGES)) for _ in range(8)]
        calendar = [_track(f"G{index:02d}-R{r + 1}", a, rng) for r, a in enumerate(archetypes)]
        specs.append({"id": f"S{index:02d}", "calendar": calendar, "early_habit": rng.choice(EARLY_HABITS)})
    return specs


def build_state(spec: Mapping[str, Any], coeffs: Mapping[str, Any] = coef.DEFAULT):
    """Season start -> state before race index HISTORY_RACES, using only public rules."""
    solver = Solver(coeffs)
    state = new_championship_state(calendar=spec["calendar"], resource_inventory=initial_inventory(coeffs))
    for _ in range(HISTORY_RACES):
        state = after_race(prepare(state, solver.choose(state, spec["early_habit"]), coeffs), coeffs)
    return state


def with_late_calendar(spec: Mapping[str, Any], late: List[RaceEntry], label: str) -> Dict[str, Any]:
    out = copy.deepcopy(dict(spec))
    out["calendar"] = list(spec["calendar"][:6]) + list(late)
    out["id"] = f"{spec['id']}-{label}"
    return out


def pair_variants(spec: Mapping[str, Any]) -> Dict[str, Dict[str, Any]]:
    """Same history and same next race (index 5); only races 7-8 differ.

    decision pair: a late high-speed double-header vs a late street double-header.
      Natural because real calendars cluster similar venues; power-unit stress and
      overtaking difficulty move in opposite directions between the two.
    control pair: the original late races with every parameter jittered by at
      most +/-0.03 (same archetypes): a statistically indistinguishable calendar
      that should rarely change the optimal decision.
    """
    rng = random.Random(f"control:{spec['id']}")

    def jitter(race: RaceEntry) -> RaceEntry:
        clip = lambda v: round(min(1.0, max(0.0, v + rng.uniform(-0.03, 0.03))), 3)  # noqa: E731
        return RaceEntry(name=race.name + "j", archetype=race.archetype,
                         power_unit_stress=clip(race.power_unit_stress),
                         overtaking_difficulty=clip(race.overtaking_difficulty),
                         tyre_degradation=clip(race.tyre_degradation), synthetic_placeholder=True)

    late = spec["calendar"][6:]
    return {
        "late_high_speed": with_late_calendar(
            spec, [midpoint_track(f"{spec['id']}-HS{i}", "high_speed") for i in (1, 2)], "HS"),
        "late_street": with_late_calendar(
            spec, [midpoint_track(f"{spec['id']}-ST{i}", "street") for i in (1, 2)], "ST"),
        "control_a": with_late_calendar(spec, list(late), "CA"),
        "control_b": with_late_calendar(spec, [jitter(r) for r in late], "CB"),
    }
