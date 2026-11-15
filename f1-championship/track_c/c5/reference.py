"""Small public-input C5 decision reference for later evaluation only.

This is a deterministic heuristic, not an optimal planner, reward policy, or part of
shared simulation. It reads priors, public observations, and public field pace only.
"""

from __future__ import annotations

import copy
import math
from typing import Any

from .core import public_observation
from .model import observation_sd


def _metric_precision(state: dict[str, Any], setup_id: str, metric: str) -> float:
    prior_sd = state["model"]["setups"][setup_id]["priors"][metric]["sd"]
    if prior_sd == 0:
        return math.inf
    precision = 1.0 / (prior_sd * prior_sd)
    for tick in state["practice"]["history"]:
        for row in tick["measurements"]:
            if row["setup_id"] == setup_id and row["metric"] == metric:
                precision += row["laps"] / (row["observation_sd_per_lap"] ** 2)
    return precision


def _estimate(state: dict[str, Any], setup_id: str, metric: str) -> float:
    if metric == "deg_multiplier_factor":
        return state["practice"]["tyre_wear_estimates"][setup_id]["mean"]
    return state["practice"]["known_setup_estimates"][setup_id][metric]["mean"]


def evaluate_setup(public_state: dict[str, Any], car: str, setup_id: str,
                   grid_loss_places: int = 0) -> dict[str, Any]:
    """Estimate provisional grid and heuristic race points for one controlled car."""
    public_observation(public_state)
    if isinstance(grid_loss_places, bool) or not isinstance(grid_loss_places, int) or grid_loss_places < 0:
        raise ValueError("grid loss must be a non-negative integer")
    if setup_id not in public_state["model"]["setups"] or car not in public_state["field"]:
        raise ValueError("unknown setup or car")
    model = public_state["model"]
    quali_times = {}
    race_times = {}
    for contender, entry in public_state["field"].items():
        selected = setup_id if contender == car else model["default_setup_id"]
        quali_mean = _estimate(public_state, selected, "qualifying_pace_offset_sec")
        race_mean = _estimate(public_state, selected, "long_run_pace_offset_sec_per_lap")
        deg_mean = _estimate(public_state, selected, "deg_multiplier_factor")
        quali_times[contender] = entry["base_pace_sec"] + quali_mean
        laps = model["reference"]["race_laps"]["value"]
        race_times[contender] = (
            entry["base_pace_sec"]
            + laps * race_mean
            + laps * model["base_deg_time_loss_sec_per_lap"] * (deg_mean - 1.0)
        )
    grid = sorted(quali_times, key=lambda contender: (quali_times[contender], contender))
    race = sorted(race_times, key=lambda contender: (race_times[contender], contender))
    points = model["reference"]["points_by_position"]["value"]
    position = race.index(car) + 1
    race_points = points[position - 1] if position <= len(points) else 0
    grid_loss = grid_loss_places * model["reference"]["grid_loss_points_per_place"]["value"]
    return {
        "car": car,
        "setup_id": setup_id,
        "provisional_grid_position": grid.index(car) + 1,
        "estimated_race_position": position,
        "estimated_race_points": race_points,
        "grid_loss_points": grid_loss,
        "net_estimated_points": race_points - grid_loss,
        "estimated_qualifying_time": quali_times[car],
        "estimated_race_time": race_times[car],
        "estimation_basis": "posterior means over public practice evidence; rivals use neutral defaults",
    }


def qualifying_reference(public_state: dict[str, Any], *, grid_loss_places: int = 0) -> dict[str, Any]:
    """Choose highest heuristic net points, with a deterministic setup-ID tie-break."""
    choices = {}
    for seat, car in sorted(public_state["car_ids"].items()):
        evaluations = [evaluate_setup(public_state, car, setup_id, grid_loss_places)
                       for setup_id in public_state["model"]["setups"]]
        best = min(evaluations, key=lambda row: (-row["net_estimated_points"], row["setup_id"]))
        ci = public_state["practice"]["known_setup_estimates"][best["setup_id"]][
            "qualifying_pace_offset_sec"]["ci95"]
        choices[seat] = {
            "setup_id": best["setup_id"],
            "run_plan": "TWO_RUN" if ci > 0 else "ONE_RUN",
            "evaluation": best,
        }
    return {
        "type": "QUALIFYING",
        "driver_a": {key: value for key, value in choices["driver_a"].items() if key != "evaluation"},
        "driver_b": {key: value for key, value in choices["driver_b"].items() if key != "evaluation"},
    }


def _information_value(state: dict[str, Any], setup_id: str, program: str,
                       allocated_laps: int) -> float:
    metric = state["model"]["noise_model"]["programs"][program]["metric"]
    before = _metric_precision(state, setup_id, metric)
    if math.isinf(before):
        return 0.0
    sd = observation_sd(state["model"], program)
    after = before + allocated_laps / (sd * sd)
    variance_reduction = (1.0 / before) - (1.0 / after)
    weights = state["model"]["reference"]["information_weights"]
    weight = weights[metric]["value"]
    if weight is None:
        weight = state["model"]["reference"]["race_laps"]["value"] * state["model"]["base_deg_time_loss_sec_per_lap"]
    return weight * variance_reduction


def _practice_allocation(public_state: dict[str, Any], seat: str) -> tuple[str, str, int]:
    remaining = public_state["practice"]["laps_budget_remaining"][seat]
    if remaining <= 0:
        return "SETUP_TEST", public_state["model"]["default_setup_id"], 0
    batch = min(remaining, public_state["model"]["reference"]["practice_batch_laps"]["value"])
    allocation = {program: {setup_id: 0 for setup_id in public_state["model"]["setups"]}
                  for program in public_state["model"]["noise_model"]["programs"]}
    for _ in range(batch):
        choices = []
        for program, by_setup in allocation.items():
            for setup_id, allocated in by_setup.items():
                value = _information_value(public_state, setup_id, program, allocated + 1)
                recent = _information_value(public_state, setup_id, program, allocated) if allocated else 0.0
                choices.append((value - recent, program, setup_id))
        gain, program, setup_id = min(choices, key=lambda row: (-row[0], row[1], row[2]))
        if gain <= 0:
            break
        allocation[program][setup_id] += 1
    ranked = sorted(
        (count, program, setup_id)
        for program, by_setup in allocation.items() for setup_id, count in by_setup.items() if count
    )
    if not ranked:
        return "SETUP_TEST", public_state["model"]["default_setup_id"], 0
    count, program, setup_id = ranked[-1]
    return program, setup_id, count


def practice_reference(public_state: dict[str, Any]) -> dict[str, Any]:
    """Greedily buy marginal public variance reduction within a bounded batch."""
    public_observation(public_state)
    if public_state["phase"] != "PRACTICE":
        raise ValueError("practice_reference requires PRACTICE phase")
    output = {"type": "PRACTICE"}
    for seat in public_state["car_ids"]:
        program, setup_id, laps = _practice_allocation(public_state, seat)
        output[seat] = {"program": program, "setup_id": setup_id, "laps": laps}
    return copy.deepcopy(output)


def reference_decision(public_state: dict[str, Any]) -> dict[str, Any]:
    """Return the phase-appropriate public-input reference action for later evaluation."""
    if public_state["phase"] == "PRACTICE":
        return practice_reference(public_state)
    return qualifying_reference(public_state)
