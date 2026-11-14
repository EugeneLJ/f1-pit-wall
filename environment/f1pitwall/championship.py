"""Serializable state schema for the future eight-race championship.

This module intentionally contains no race, wear, penalty, or scoring logic.
It only defines persistent state and validates its shape at configuration
boundaries.
"""

from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 1
CALENDAR_FIXTURE = Path(__file__).with_name("fixtures") / "championship_calendar.json"
TRACK_ARCHETYPES = {"street", "high_speed", "high_degradation", "wet_prone", "mixed"}

TEAM_DRIVERS = {
    "Apex": ("Apex A", "Apex B"),
    "Orion": ("Orion A", "Orion B"),
    "Nova": ("Nova A", "Nova B"),
    "Vertex": ("Vertex A", "Vertex B"),
}


@dataclass(frozen=True)
class RaceEntry:
    name: str
    archetype: str
    power_unit_stress: float
    overtaking_difficulty: float
    tyre_degradation: float
    synthetic_placeholder: bool

    def validate(self) -> None:
        if not isinstance(self.name, str) or not self.name.strip():
            raise ValueError("race name must be a non-empty string")
        if not isinstance(self.archetype, str) or not self.archetype.strip():
            raise ValueError("race archetype must be a non-empty string")
        if self.archetype not in TRACK_ARCHETYPES:
            raise ValueError(f"unsupported race archetype: {self.archetype}")
        for name, value in (("power_unit_stress", self.power_unit_stress),
                            ("overtaking_difficulty", self.overtaking_difficulty),
                            ("tyre_degradation", self.tyre_degradation)):
            _validate_unit_interval(name, value)
        if self.synthetic_placeholder is not True:
            raise ValueError("calendar values must be marked as synthetic placeholders")


@dataclass
class PowerUnitComponent:
    wear: float = 0.0
    replacements: int = 0

    def validate(self) -> None:
        if isinstance(self.wear, bool) or not isinstance(self.wear, (int, float)):
            raise ValueError("component wear must be numeric")
        if not math.isfinite(self.wear) or not 0.0 <= self.wear <= 1.0:
            raise ValueError("component wear must be finite and within [0, 1]")
        _validate_nonnegative_int("component replacements", self.replacements)


@dataclass
class ChampionshipState:
    race_index: int
    calendar: list[RaceEntry]
    driver_points: dict[str, int]
    team_points: dict[str, int]
    power_units: dict[str, dict[str, PowerUnitComponent]]
    grid_penalties: dict[str, int]
    resource_inventory: dict[str, dict[str, int]]
    schema_version: int = SCHEMA_VERSION

    def validate(self) -> None:
        if self.schema_version != SCHEMA_VERSION:
            raise ValueError(f"unsupported championship schema version: {self.schema_version}")
        _validate_nonnegative_int("race_index", self.race_index)
        if not self.calendar:
            raise ValueError("calendar must contain at least one race")
        if self.race_index > len(self.calendar):
            raise ValueError("race_index cannot exceed calendar length")
        for race in self.calendar:
            race.validate()
        names = [race.name for race in self.calendar]
        if len(names) != len(set(names)):
            raise ValueError("calendar race names must be unique")

        expected_teams = set(TEAM_DRIVERS)
        expected_drivers = {driver for drivers in TEAM_DRIVERS.values() for driver in drivers}
        _validate_keys("team_points", self.team_points, expected_teams)
        _validate_keys("resource_inventory", self.resource_inventory, expected_teams)
        _validate_keys("driver_points", self.driver_points, expected_drivers)
        _validate_keys("power_units", self.power_units, expected_drivers)
        _validate_keys("grid_penalties", self.grid_penalties, expected_drivers)

        for label, values in (("driver points", self.driver_points),
                              ("team points", self.team_points),
                              ("grid penalty", self.grid_penalties)):
            for value in values.values():
                _validate_nonnegative_int(label, value)
        for components in self.power_units.values():
            if not components:
                raise ValueError("each driver must have at least one power-unit component")
            for name, component in components.items():
                if not isinstance(name, str) or not name:
                    raise ValueError("power-unit component names must be non-empty strings")
                component.validate()
        for inventory in self.resource_inventory.values():
            for name, quantity in inventory.items():
                if not isinstance(name, str) or not name:
                    raise ValueError("resource names must be non-empty strings")
                _validate_nonnegative_int("resource quantity", quantity)

    def to_dict(self) -> dict[str, Any]:
        self.validate()
        return asdict(self)

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), sort_keys=True, separators=(",", ":"))

    @classmethod
    def from_dict(cls, value: Any) -> "ChampionshipState":
        if not isinstance(value, dict):
            raise ValueError("championship state must be an object")
        required = {"schema_version", "race_index", "calendar", "driver_points", "team_points",
                    "power_units", "grid_penalties", "resource_inventory"}
        if set(value) != required:
            raise ValueError("championship state contains missing or unknown fields")
        try:
            state = cls(
                schema_version=value["schema_version"],
                race_index=value["race_index"],
                calendar=[RaceEntry(**race) for race in value["calendar"]],
                driver_points=dict(value["driver_points"]),
                team_points=dict(value["team_points"]),
                power_units={driver: {name: PowerUnitComponent(**component)
                                      for name, component in components.items()}
                             for driver, components in value["power_units"].items()},
                grid_penalties=dict(value["grid_penalties"]),
                resource_inventory={team: dict(resources)
                                    for team, resources in value["resource_inventory"].items()},
            )
        except (TypeError, AttributeError) as exc:
            raise ValueError("invalid championship state structure") from exc
        state.validate()
        return state

    @classmethod
    def from_json(cls, value: str) -> "ChampionshipState":
        try:
            decoded = json.loads(value)
        except (TypeError, json.JSONDecodeError) as exc:
            raise ValueError("invalid championship state JSON") from exc
        return cls.from_dict(decoded)


def load_calendar_fixture(path: Path = CALENDAR_FIXTURE) -> list[RaceEntry]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"invalid calendar fixture: {path}") from exc
    required = {"schema_version", "data_status", "scale", "races"}
    if not isinstance(value, dict) or set(value) != required:
        raise ValueError("calendar fixture contains missing or unknown fields")
    if value["schema_version"] != 1:
        raise ValueError("unsupported calendar fixture schema version")
    if value["data_status"] != "synthetic_placeholder":
        raise ValueError("calendar fixture must identify synthetic placeholder data")
    if value["scale"] != "normalized_0_to_1":
        raise ValueError("calendar fixture must use the normalized 0-to-1 scale")
    try:
        races = [RaceEntry(**race) for race in value["races"]]
    except (TypeError, AttributeError) as exc:
        raise ValueError("invalid calendar race structure") from exc
    if len(races) != 8:
        raise ValueError("default championship calendar must contain exactly eight races")
    for race in races:
        race.validate()
    if len({race.name for race in races}) != len(races):
        raise ValueError("calendar race names must be unique")
    return races


def default_calendar() -> list[RaceEntry]:
    return load_calendar_fixture()


def new_championship_state() -> ChampionshipState:
    drivers = [driver for team_drivers in TEAM_DRIVERS.values() for driver in team_drivers]
    state = ChampionshipState(
        race_index=0,
        calendar=default_calendar(),
        driver_points={driver: 0 for driver in drivers},
        team_points={team: 0 for team in TEAM_DRIVERS},
        power_units={driver: {
            "ICE": PowerUnitComponent(),
            "turbo": PowerUnitComponent(),
            "energy_store": PowerUnitComponent(),
        } for driver in drivers},
        grid_penalties={driver: 0 for driver in drivers},
        resource_inventory={team: {"component_spares": 2, "development_units": 100}
                            for team in TEAM_DRIVERS},
    )
    state.validate()
    return state


def _validate_keys(label: str, value: Any, expected: set[str]) -> None:
    if not isinstance(value, dict) or set(value) != expected:
        raise ValueError(f"{label} keys must match the configured championship participants")


def _validate_nonnegative_int(label: str, value: Any) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{label} must be a non-negative integer")


def _validate_unit_interval(label: str, value: Any) -> None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{label} must be numeric")
    if not math.isfinite(value) or not 0.0 <= value <= 1.0:
        raise ValueError(f"{label} must be finite and within [0, 1]")
