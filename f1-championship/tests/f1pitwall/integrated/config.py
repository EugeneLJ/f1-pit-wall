"""Versioned championship modes and reproducible configuration (benchmark 2.0.0).

SOLO_LEGACY is the unchanged 1.1.0 benchmark (ChampionshipSession, journal v1, reward p0).
SOLO_COORDINATION and TWO_TEAM_COMPETITION are integrated modes with their own version,
contract (contract_version 2), journal (journal_version 2) and configuration hash.
"""

from __future__ import annotations

import copy
import hashlib
import json
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from ..version import BENCHMARK_VERSION as LEGACY_VERSION

INTEGRATED_VERSION = "2.0.0"
SOLO_LEGACY = "SOLO_LEGACY"
SOLO_COORDINATION = "SOLO_COORDINATION"
TWO_TEAM_COMPETITION = "TWO_TEAM_COMPETITION"
MODES = (SOLO_LEGACY, SOLO_COORDINATION, TWO_TEAM_COMPETITION)
SLOTS = ("Apex", "Orion", "Nova", "Vertex")
ENGINEER_CONDITIONS = ("CHIEF_ONLY", "GEMINI_LITE_ENGINEERS", "RECORDED_RECOMMENDATIONS",
                       "CONFLICTING_LOCAL_RECOMMENDATIONS", "NOMINAL_CONFIDENCE_CONTROL",
                       "HIGH_SELF_REPORTED_CONFIDENCE_CONTROL", "MOCK_ENGINEERS")
RIVAL_CONDITIONS = ("ADAPTIVE", "FIXED_REPLAY")

VERSION_NOTES = {
    "2.0.0": ("Integrated modes (B6): Track C team orders (RACE/HOLD/SWAP/DEFENSIVE_BUFFER, "
              "KEEP_ORDER/REQUEST_GIVE_BACK) and conditional commitments executed by the Track B "
              "race engine; Engineer reports as observation content; multi-team simultaneous ticks; "
              "journal v2. Tyre, pit, SC/VSC, overtaking, Track A and points models are the 1.1.0 "
              "models unchanged; with team order RACE the race step equals 1.1.0 bit for bit."),
}


@dataclass(frozen=True)
class TeamSpec:
    label: str                 # constructor name in observations and standings
    short: str                 # driver-name prefix: '<short> A', '<short> B'
    slot: str                  # car slot in the engine (performance profile, grid)
    chief: Dict[str, Any] = field(default_factory=dict)       # provenance: provider/model/policy
    engineers: str = "CHIEF_ONLY"

    def validate(self) -> None:
        if self.slot not in SLOTS:
            raise ValueError(f"unknown slot {self.slot}")
        if self.engineers not in ENGINEER_CONDITIONS:
            raise ValueError(f"unknown engineer condition {self.engineers}")
        if not self.label or not self.short:
            raise ValueError("team label and short name are required")


@dataclass(frozen=True)
class IntegratedConfig:
    mode: str
    teams: List[TeamSpec]
    rival_condition: str = "ADAPTIVE"           # second team live, or replay of a fixed trace
    rival_policy_variant: Optional[str] = None  # uncontrolled teams' pit rule (None = published)
    decision_timeout_sec: float = 120.0
    benchmark_version: str = INTEGRATED_VERSION

    def validate(self) -> None:
        if self.mode not in MODES:
            raise ValueError("unknown mode")
        if self.mode == SOLO_LEGACY:
            raise ValueError("SOLO_LEGACY uses the 1.1.0 ChampionshipSession, not IntegratedConfig")
        expected = 1 if self.mode == SOLO_COORDINATION else 2
        if len(self.teams) != expected:
            raise ValueError(f"{self.mode} needs {expected} controlled team(s)")
        for team in self.teams:
            team.validate()
        if len({t.slot for t in self.teams}) != len(self.teams):
            raise ValueError("controlled teams need distinct slots")
        if len({t.label for t in self.teams}) != len(self.teams) or \
                len({t.short for t in self.teams}) != len(self.teams):
            raise ValueError("team labels and short names must be distinct")
        uncontrolled = set(SLOTS) - {t.slot for t in self.teams}
        if {t.label for t in self.teams} & uncontrolled or {t.short for t in self.teams} & uncontrolled:
            raise ValueError("team names must not collide with uncontrolled team names")
        if self.rival_condition not in RIVAL_CONDITIONS:
            raise ValueError("unknown rival condition")
        if self.benchmark_version != INTEGRATED_VERSION:
            raise ValueError("integrated modes are benchmark 2.0.0")

    def as_dict(self) -> Dict[str, Any]:
        return {"mode": self.mode, "benchmark_version": self.benchmark_version,
                "teams": [{"label": t.label, "short": t.short, "slot": t.slot,
                           "chief": copy.deepcopy(t.chief), "engineers": t.engineers} for t in self.teams],
                "rival_condition": self.rival_condition, "rival_policy_variant": self.rival_policy_variant,
                "decision_timeout_sec": self.decision_timeout_sec}

    def config_hash(self) -> str:
        text = json.dumps(self.as_dict(), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(text.encode("utf-8")).hexdigest()

    def swapped(self) -> "IntegratedConfig":
        """Same configuration with the two controlled teams' car slots exchanged."""
        if len(self.teams) != 2:
            raise ValueError("slot swap needs two controlled teams")
        a, b = self.teams
        return IntegratedConfig(self.mode, [TeamSpec(a.label, a.short, b.slot, a.chief, a.engineers),
                                            TeamSpec(b.label, b.short, a.slot, b.chief, b.engineers)],
                                self.rival_condition, self.rival_policy_variant,
                                self.decision_timeout_sec, self.benchmark_version)

    @staticmethod
    def from_dict(value: Dict[str, Any]) -> "IntegratedConfig":
        teams = [TeamSpec(t["label"], t["short"], t["slot"], dict(t.get("chief", {})),
                          t.get("engineers", "CHIEF_ONLY")) for t in value["teams"]]
        cfg = IntegratedConfig(value["mode"], teams, value.get("rival_condition", "ADAPTIVE"),
                               value.get("rival_policy_variant"), float(value.get("decision_timeout_sec", 120.0)),
                               value.get("benchmark_version", INTEGRATED_VERSION))
        cfg.validate()
        return cfg


def solo_coordination(engineers: str = "CHIEF_ONLY", chief: Optional[Dict[str, Any]] = None) -> IntegratedConfig:
    cfg = IntegratedConfig(SOLO_COORDINATION, [TeamSpec("Apex", "Apex", "Apex", chief or {}, engineers)])
    cfg.validate()
    return cfg


def two_team(layer: int = 1, mclearn_chief: Optional[Dict[str, Any]] = None,
             redbool_chief: Optional[Dict[str, Any]] = None, mclearn_slot: str = "Apex",
             redbool_slot: str = "Orion", rival_condition: str = "ADAPTIVE",
             mclearn_engineers: Optional[str] = None) -> IntegratedConfig:
    """Layer 1: both Chiefs without Engineers. Layer 2: McLearn Chief + Engineer A/B."""
    if layer not in (1, 2):
        raise ValueError("layer must be 1 or 2")
    engineers = mclearn_engineers or ("GEMINI_LITE_ENGINEERS" if layer == 2 else "CHIEF_ONLY")
    if layer == 1 and engineers != "CHIEF_ONLY":
        raise ValueError("layer 1 has no Engineers")
    cfg = IntegratedConfig(TWO_TEAM_COMPETITION, [
        TeamSpec("McLearn Racing", "McLearn", mclearn_slot,
                 mclearn_chief or {"provider": "google_genai", "model": "gemini"}, engineers),
        TeamSpec("Red Bool Racing", "Red Bool", redbool_slot,
                 redbool_chief or {"provider": "verda_openai_compatible", "model": "deepseek-4-1-flash-1017"}, "CHIEF_ONLY"),
    ], rival_condition)
    cfg.validate()
    return cfg


__all__ = ["INTEGRATED_VERSION", "LEGACY_VERSION", "MODES", "SOLO_LEGACY", "SOLO_COORDINATION",
           "TWO_TEAM_COMPETITION", "TeamSpec", "IntegratedConfig", "solo_coordination", "two_team"]
