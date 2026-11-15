"""Pure Practice → Qualifying → parc-fermé C5 functions.

The public state contains priors and measurements, never a seed or latent draw.
Private parc-fermé envelopes are required only when trusted race setup is computed.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
import hashlib
import json
import math
from typing import Any

from .model import (
    METRICS,
    PROGRAMS,
    RUN_PLANS,
    integers,
    load_model,
    observation_sd,
    prior,
    reject_secret_content,
    rng_integer,
    validate_setup,
)


def _rounded(value: float, digits: int = 12) -> float:
    result = round(float(value), digits)
    return 0.0 if result == 0 else result


def _canonical_key(value: tuple[Any, ...]) -> bytes:
    return json.dumps(value, sort_keys=False, separators=(",", ":"), allow_nan=False).encode("utf-8")


def keyed_normal(rng_key: int, *parts: Any) -> float:
    """One standard normal draw, independent of call order and unrelated actions."""
    rng_integer(rng_key)
    digest = hashlib.sha256(_canonical_key((rng_key, *parts))).digest()
    u1 = (int.from_bytes(digest[:8], "big") + 1) / (2**64 + 1)
    u2 = int.from_bytes(digest[8:16], "big") / 2**64
    return math.sqrt(-2.0 * math.log(u1)) * math.cos(2.0 * math.pi * u2)


def _true_effect(rng_key: int, weekend_id: str, team: str, setup_id: str, metric: str,
                 model: dict[str, Any]) -> float:
    mean, sd = prior(model, setup_id, metric)
    if sd == 0:
        return mean
    return mean + sd * keyed_normal(rng_key, "c5-truth-v1", weekend_id, team, setup_id, metric)


def _new_estimates(model: dict[str, Any], history: list[dict[str, Any]]) -> tuple[dict, dict]:
    known, tyre = {}, {}
    for setup_id in model["setups"]:
        known[setup_id] = {}
        for metric in METRICS:
            mean, sd = prior(model, setup_id, metric)
            precision = math.inf if sd == 0 else 1.0 / (sd * sd)
            weighted = 0.0 if sd == 0 else mean * precision
            laps = 0
            for tick in history:
                for row in tick["measurements"]:
                    if row["setup_id"] != setup_id or row["metric"] != metric:
                        continue
                    count = row["laps"]
                    noise = row["observation_sd_per_lap"]
                    weight = count / (noise * noise)
                    weighted += weight * row["sample_mean"]
                    precision += weight
                    laps += count
            if math.isinf(precision):
                posterior, ci = mean, 0.0
            else:
                posterior = weighted / precision
                ci = model["ci95_z"] * math.sqrt(1.0 / precision)
            estimate = {"mean": _rounded(posterior), "ci95": _rounded(ci), "laps_observed": laps}
            if metric == "deg_multiplier_factor":
                tyre[setup_id] = estimate
            else:
                known[setup_id][metric] = estimate
    return known, tyre


def _validate_field(state: dict[str, Any]) -> None:
    if set(state) != {"schema_version", "weekend_id", "team", "car_ids", "field", "model", "phase", "practice"}:
        raise ValueError("invalid public C5 state fields")
    if state["schema_version"] != 1 or not isinstance(state["weekend_id"], str) or not state["weekend_id"]:
        raise ValueError("public C5 weekend identity is missing")
    if not isinstance(state["team"], str) or not state["team"]:
        raise ValueError("public C5 team identity is missing")
    if set(state["car_ids"]) != {"driver_a", "driver_b"}:
        raise ValueError("exactly two controlled cars are required")
    for seat, car in state["car_ids"].items():
        if not isinstance(car, str) or car not in state["field"]:
            raise ValueError("controlled car is absent from field")
        entry = state["field"][car]
        if entry.get("team") != state["team"] or entry.get("driver_key") != seat:
            raise ValueError("controlled car ownership mismatch")
    seat_owners = set()
    for car, entry in state["field"].items():
        if not isinstance(car, str) or set(entry) != {"team", "driver_key", "base_pace_sec"}:
            raise ValueError(f"invalid field entry for {car}")
        if entry["driver_key"] not in ("driver_a", "driver_b"):
            raise ValueError("invalid field seat")
        ownership = (entry["team"], entry["driver_key"])
        if ownership in seat_owners:
            raise ValueError(f"duplicate team/seat ownership: {ownership}")
        seat_owners.add(ownership)
        value = entry["base_pace_sec"]
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
            raise ValueError("base pace must be positive and finite")
    controlled_cars = {car for car, entry in state["field"].items() if entry["team"] == state["team"]}
    if controlled_cars != set(state["car_ids"].values()):
        raise ValueError("controlled team must have exactly the two declared cars")


def _expected_state(state: dict[str, Any], history: list[dict[str, Any]]) -> dict[str, Any]:
    model = state["model"]
    remaining = {seat: model["lap_budget_per_driver"] for seat in state["car_ids"]}
    next_lap = {seat: 0 for seat in state["car_ids"]}
    for expected_session, tick in enumerate(history, 1):
        if set(tick) != {"session_index", "actions", "measurements"} or tick["session_index"] != expected_session:
            raise ValueError("practice history/session order is invalid")
        by_driver = {}
        for action in tick["actions"]:
            if set(action) != {"driver", "program", "setup_id", "laps", "lap_index_start"}:
                raise ValueError("invalid practice history action")
            seat = action["driver"]
            if seat not in remaining or seat in by_driver:
                raise ValueError("practice driver is invalid or repeated")
            program = action["program"]
            observation_sd(state["model"], program)
            validate_setup(state["model"], action["setup_id"])
            laps = integers(action["laps"])
            if action["lap_index_start"] != next_lap[seat]:
                raise ValueError("absolute practice lap index is not contiguous")
            remaining[seat] -= laps
            if remaining[seat] < 0:
                raise ValueError("practice lap budget is negative")
            next_lap[seat] += laps
            by_driver[seat] = action
        if set(by_driver) != set(remaining):
            raise ValueError("every controlled driver needs an action per session")
        expected_measurements = sum(action["laps"] > 0 for action in by_driver.values())
        if len(tick["measurements"]) != expected_measurements:
            raise ValueError("practice history measurement count differs from actions")
        measured_drivers = set()
        for row in tick["measurements"]:
            if set(row) != {"driver", "program", "setup_id", "metric", "laps", "lap_index_start",
                            "sample_mean", "observation_sd_per_lap", "sample_standard_error"}:
                raise ValueError("invalid practice measurement fields")
            seat = row["driver"]
            if seat in measured_drivers:
                raise ValueError("exactly one measurement per positive-lap driver is required")
            measured_drivers.add(seat)
            action = by_driver.get(seat)
            if action is None or row["lap_index_start"] != action["lap_index_start"]:
                raise ValueError("measurement action linkage is invalid")
            metric = model["noise_model"]["programs"][action["program"]]["metric"]
            if row["program"] != action["program"] or row["setup_id"] != action["setup_id"] or row["metric"] != metric:
                raise ValueError("measurement program/setup/metric mismatch")
            if integers(row["laps"], minimum=1) != action["laps"]:
                raise ValueError("measurement lap count mismatch")
            sd = observation_sd(model, row["program"])
            if row["observation_sd_per_lap"] != sd:
                raise ValueError("measurement noise model mismatch")
            if row["sample_standard_error"] != _rounded(sd / math.sqrt(row["laps"])):
                raise ValueError("measurement standard error mismatch")
            if isinstance(row["sample_mean"], bool) or not isinstance(row["sample_mean"], (int, float)) or not math.isfinite(row["sample_mean"]):
                raise ValueError("measurement mean must be finite")
        expected_drivers = {seat for seat, action in by_driver.items() if action["laps"] > 0}
        if measured_drivers != expected_drivers:
            raise ValueError("measurements must cover every positive-lap driver exactly once")
    known, tyre = _new_estimates(state["model"], history)
    noise_model = copy.deepcopy(state["model"]["noise_model"])
    noise_model["posterior_estimator"] = {
        "model": "conjugate Gaussian precision update",
        "precision": "1/prior_sd^2 plus sum(observed_laps / observation_sd_per_lap^2)",
        "mean": "precision-weighted prior and batch sample means",
        "ci95_half_width": "ci95_z / sqrt(posterior_precision)",
        "ci95_z": state["model"]["ci95_z"],
    }
    session_index = min(len(history) + 1, state["model"]["sessions_total"])
    practice = {
        "session_index": session_index,
        "sessions_total": state["model"]["sessions_total"],
        "laps_budget_remaining": remaining,
        "next_lap_index": next_lap,
        "known_setup_estimates": known,
        "tyre_wear_estimates": tyre,
        "noise_model": noise_model,
        "history": copy.deepcopy(history),
    }
    return practice


def _validate_public_state(state: dict[str, Any]) -> None:
    reject_secret_content(state)
    _validate_field(state)
    model = state["model"]
    if not isinstance(model, dict) or model.get("archetype") not in {"mixed", "street", "high_speed", "high_degradation", "wet_prone"}:
        raise ValueError("invalid C5 model")
    if state["phase"] not in ("PRACTICE", "QUALIFYING"):
        raise ValueError("C5 phase must be PRACTICE or QUALIFYING")
    expected = _expected_state(state, state["practice"]["history"])
    if state["practice"] != expected:
        raise ValueError("public practice counters or estimates are inconsistent with history")
    if state["phase"] == "PRACTICE" and len(state["practice"]["history"]) >= model["sessions_total"]:
        raise ValueError("practice sessions are exhausted")
    if state["phase"] == "QUALIFYING" and len(state["practice"]["history"]) != model["sessions_total"]:
        raise ValueError("qualifying requires both practice sessions")
    reject_secret_content(state)


def initial_public_state(model: dict[str, Any], *, weekend_id: str, team: str,
                         car_ids: dict[str, str], field: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Create a fresh public PRACTICE state with no hidden draw or RNG state."""
    state = {
        "schema_version": 1,
        "weekend_id": weekend_id,
        "team": team,
        "car_ids": copy.deepcopy(car_ids),
        "field": copy.deepcopy(field),
        "model": copy.deepcopy(model),
        "phase": "PRACTICE",
        "practice": {},
    }
    _validate_field(state)
    practice = _expected_state(state, [])
    state["practice"] = practice
    _validate_public_state(state)
    return state


def _clean_driver_action(model: dict[str, Any], value: Any) -> tuple[str, str, int]:
    if not isinstance(value, dict) or set(value) != {"program", "setup_id", "laps"}:
        raise ValueError("practice action fields must be exactly program/setup_id/laps")
    observation_sd(model, value["program"])
    return value["program"], validate_setup(model, value["setup_id"]), integers(value["laps"])


def simulate_practice(public_state: dict[str, Any], action: dict[str, Any], rng_key: int) -> dict[str, Any]:
    """Return one atomic `{measurements, state}` result; no RNG or truth is exposed."""
    rng_integer(rng_key)
    _validate_public_state(public_state)
    if public_state["phase"] != "PRACTICE":
        raise ValueError("simulate_practice requires PRACTICE phase")
    if not isinstance(action, dict) or set(action) != {"type", "driver_a", "driver_b"} or action["type"] != "PRACTICE":
        raise ValueError("invalid PRACTICE action envelope")
    remaining = public_state["practice"]["laps_budget_remaining"]
    next_lap = public_state["practice"]["next_lap_index"]
    model = public_state["model"]
    clean = []
    measurements = []
    for seat in ("driver_a", "driver_b"):
        program, setup_id, laps = _clean_driver_action(model, action[seat])
        if laps > remaining[seat]:
            raise ValueError("practice action exceeds weekend lap budget")
        start = next_lap[seat]
        clean.append({"driver": seat, "program": program, "setup_id": setup_id,
                      "laps": laps, "lap_index_start": start})
        if laps == 0:
            continue
        metric = model["noise_model"]["programs"][program]["metric"]
        sd = observation_sd(model, program)
        truth = _true_effect(rng_key, public_state["weekend_id"], public_state["team"], setup_id, metric, model)
        values = [
            truth + sd * keyed_normal(
                rng_key, "c5-practice-noise-v1", public_state["weekend_id"], public_state["team"],
                seat, public_state["practice"]["session_index"], setup_id, metric, start + lap,
            )
            for lap in range(laps)
        ]
        measurements.append({
            "driver": seat, "program": program, "setup_id": setup_id, "metric": metric,
            "laps": laps, "lap_index_start": start, "sample_mean": _rounded(sum(values) / laps),
            "observation_sd_per_lap": sd, "sample_standard_error": _rounded(sd / math.sqrt(laps)),
        })
    session_index = public_state["practice"]["session_index"]
    history = copy.deepcopy(public_state["practice"]["history"])
    history.append({"session_index": session_index, "actions": clean, "measurements": measurements})
    next_state = copy.deepcopy(public_state)
    next_state["practice"] = _expected_state(next_state, history)
    next_state["phase"] = "PRACTICE" if len(history) < model["sessions_total"] else "QUALIFYING"
    _validate_public_state(next_state)
    return {"type": "PRACTICE_RESULT", "measurements": measurements, "state": next_state}


def _clean_qualifying_action(model: dict[str, Any], value: Any) -> dict[str, dict[str, str]]:
    if not isinstance(value, dict) or set(value) != {"type", "driver_a", "driver_b"} or value["type"] != "QUALIFYING":
        raise ValueError("invalid QUALIFYING action envelope")
    clean = {}
    for seat in ("driver_a", "driver_b"):
        item = value[seat]
        if not isinstance(item, dict) or set(item) != {"setup_id", "run_plan"}:
            raise ValueError("qualifying fields must be exactly setup_id/run_plan")
        if item["run_plan"] not in RUN_PLANS:
            raise ValueError("unknown qualifying run plan")
        clean[seat] = {"setup_id": validate_setup(model, item["setup_id"]), "run_plan": item["run_plan"]}
    return clean


def qualifying(public_state: dict[str, Any], actions: dict[str, Any], rng_key: int) -> dict[str, Any]:
    """Return only the provisional grid and times; penalties belong to the engine owner."""
    rng_integer(rng_key)
    _validate_public_state(public_state)
    if public_state["phase"] != "QUALIFYING":
        raise ValueError("qualifying requires both practice sessions")
    model = public_state["model"]
    if isinstance(actions, dict) and "type" in actions:
        action_map = {public_state["team"]: actions}
    elif isinstance(actions, dict) and all(isinstance(key, str) for key in actions):
        action_map = actions
    else:
        raise ValueError("qualifying actions must be a team action or team-to-action map")
    clean = {team: _clean_qualifying_action(model, action) for team, action in action_map.items()}
    unknown = set(clean) - {entry["team"] for entry in public_state["field"].values()}
    if unknown:
        raise ValueError(f"qualifying action for unknown team(s): {sorted(unknown)}")
    times = {}
    for car, entry in public_state["field"].items():
        team, seat = entry["team"], entry["driver_key"]
        choice = clean.get(team, {}).get(seat, {
            "setup_id": model["default_setup_id"], "run_plan": model["rivals_run_plan"]})
        setup_id = choice["setup_id"]
        true = _true_effect(rng_key, public_state["weekend_id"], team, setup_id, "qualifying_pace_offset_sec", model)
        sd = model["noise_model"]["qualifying_sd_per_run"]
        runs = 1 if choice["run_plan"] == "ONE_RUN" else 2
        attempts = []
        for run_index in range(runs):
            noise = sd * keyed_normal(
                rng_key, "c5-qualifying-noise-v1", public_state["weekend_id"], team, car,
                setup_id, run_index,
            )
            attempts.append(entry["base_pace_sec"] + true + noise)
        times[car] = _rounded(min(attempts), 6)
    order = sorted(times, key=lambda car: (times[car], car))
    result = {"order": order, "times": times}
    reject_secret_content(result)
    return result


@dataclass(frozen=True)
class ParcFermeChoice:
    """Trusted frozen private selection; never serialize into public observations."""

    rng_key: int = field(repr=False)
    weekend_id: str
    archetype: str
    team: str
    setups: tuple[tuple[str, str], ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "setups", tuple(sorted(self.setups)))


def make_parc_ferme_choice(choices: dict[str, str], *, rng_key: int, weekend_id: str,
                           archetype: str, team: str) -> ParcFermeChoice:
    """Seal car→setup choices; raw mutable public actions cannot become race config."""
    if not isinstance(choices, dict) or not choices:
        raise ValueError("parc-fermé choices must be a nonempty car→setup map")
    model = load_model(archetype)
    clean = tuple((car, validate_setup(model, setup)) for car, setup in choices.items())
    return ParcFermeChoice(rng_key, weekend_id, archetype, team, clean)


def race_modifiers(choice: ParcFermeChoice | None) -> dict[str, dict[str, float]]:
    """Apply the frozen private setup truth; None preserves legacy/no-C5 config."""
    if choice is None:
        return {}
    if not isinstance(choice, ParcFermeChoice):
        raise ValueError("race_modifiers requires a frozen private ParcFermeChoice")
    rng_integer(choice.rng_key)
    model = load_model(choice.archetype)
    output = {}
    for car, setup_id in choice.setups:
        if not isinstance(car, str) or not car:
            raise ValueError("parc-fermé car identifier is invalid")
        validate_setup(model, setup_id)
        pace = _true_effect(choice.rng_key, choice.weekend_id, choice.team, setup_id,
                            "long_run_pace_offset_sec_per_lap", model)
        deg = _true_effect(choice.rng_key, choice.weekend_id, choice.team, setup_id,
                           "deg_multiplier_factor", model)
        if deg <= 0:
            raise ValueError("degradation multiplier must be positive")
        output[car] = {
            "pace_offset_sec_per_lap": _rounded(pace),
            "deg_multiplier_factor": _rounded(deg),
        }
    return output


def public_observation(public_state: dict[str, Any]) -> dict[str, Any]:
    """Project the public phase observation after validating all accounting."""
    _validate_public_state(public_state)
    practice = public_state["practice"]
    if public_state["phase"] == "PRACTICE":
        output = {
            "schema_version": 1,
            "type": "PRACTICE",
            "team": public_state["team"],
            "weekend_id": public_state["weekend_id"],
            "practice": {
                "session_index": practice["session_index"],
                "sessions_total": practice["sessions_total"],
                "laps_budget_remaining": copy.deepcopy(practice["laps_budget_remaining"]),
                "known_setup_estimates": copy.deepcopy(practice["known_setup_estimates"]),
                "tyre_wear_estimates": copy.deepcopy(practice["tyre_wear_estimates"]),
                "noise_model": copy.deepcopy(practice["noise_model"]),
            },
        }
    else:
        setup_options = copy.deepcopy(practice["known_setup_estimates"])
        output = {
            "schema_version": 1,
            "type": "QUALIFYING",
            "team": public_state["team"],
            "weekend_id": public_state["weekend_id"],
            "qualifying": {
                "setup_options": setup_options,
                "tyre_wear_estimates": copy.deepcopy(practice["tyre_wear_estimates"]),
                "run_plans": list(RUN_PLANS),
                "noise_model": copy.deepcopy(practice["noise_model"]),
                "parc_ferme": "qualifying setup is frozen for the race",
                "grid_status": "provisional only; penalties are applied later by the engine owner",
            },
        }
    result = {
        **output,
        "base_pace_sec": {car: entry["base_pace_sec"] for car, entry in public_state["field"].items()},
        "data_status": "synthetic_only",
    }
    reject_secret_content(result)
    return result
