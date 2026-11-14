"""Trusted match runner for integrated modes: policies/providers per team, timeouts,
fixed-rival replay, same-seed slot-swapped pairs, and per-decision provenance.

The runner is the trusted host: it gives each Chief only `session.observation(own label)`,
collects one sealed action per team per tick, and closes the tick with the published fallback
when a Chief fails, times out or submits an invalid action. Fixed-rival replay and adaptive
competition are different estimands and are labelled separately in every result.
"""

from __future__ import annotations

import copy
import time
from typing import Any, Callable, Dict, List, Optional

from .config import IntegratedConfig
from .session import CHAMPIONSHIP_COMPLETE, INVALID, TIMEOUT, IntegratedSession, TickError

Policy = Callable[[Dict[str, Any]], Any]


class ReplayPolicy:
    """Fixed-rival condition: replays one team's recorded actions tick by tick. An action that
    is no longer legal is NOT altered: it is reported and the published fallback applies."""

    def __init__(self, journal: List[Dict[str, Any]], label: str) -> None:
        self.actions = {e["tick_id"]: copy.deepcopy(e["submissions"][label]["action"])
                        for e in journal if e["kind"] == "resolved" and label in e["submissions"]}
        self.label = label

    def __call__(self, observation: Dict[str, Any]):
        tick = observation["tick_id"]
        if tick not in self.actions:
            raise KeyError(f"no recorded action for {tick}")
        action = copy.deepcopy(self.actions[tick])
        return action, {"source": "FIXED_REPLAY"}


def run_season(config: IntegratedConfig, base_seed: int, policies: Dict[str, Policy],
               engineer_broker: Any = None, coeffs: Optional[dict] = None,
               timeout_sec: Optional[float] = None) -> Dict[str, Any]:
    """Play one full championship. A policy returns an action, or (action, metadata)."""
    if set(policies) != {t.label for t in config.teams}:
        raise ValueError("one policy per controlled team is required")
    session = IntegratedSession(config, base_seed, coeffs=coeffs, engineer_broker=engineer_broker)
    limit = timeout_sec if timeout_sec is not None else config.decision_timeout_sec
    provenance: List[Dict[str, Any]] = []
    while session.decision_type != CHAMPIONSHIP_COMPLETE:
        tick, failures = session.tick_id, {}
        for label in sorted(policies):  # order of calls cannot leak: each sees only its snapshot
            obs = session.observation(label)
            started = time.monotonic()
            meta: Dict[str, Any] = {}
            try:
                result = policies[label](obs)
                action, meta = result if isinstance(result, tuple) else (result, {})
                elapsed = time.monotonic() - started
                if elapsed > limit:
                    failures[label] = TIMEOUT
                    status = "TIMEOUT"
                else:
                    session.submit(label, tick, action, submitted_via=meta.get("submitted_via", "runner"))
                    status = "SUBMITTED"
            except TickError as exc:
                failures[label], status, meta = INVALID, "INVALID", {**meta, "error": str(exc)}
            except Exception as exc:  # provider/policy failure -> published fallback
                meta = {**meta, **getattr(exc, "metadata", {}), "error": type(exc).__name__,
                        "error_kind": getattr(exc, "kind", None)}
                failures[label], status = INVALID, "POLICY_ERROR"
            provenance.append({"tick_id": tick, "team": label, "status": status,
                               "latency_ms": round((time.monotonic() - started) * 1000, 3),
                               "metadata": _strip(meta)})
        if failures:
            reason = TIMEOUT if TIMEOUT in failures.values() else INVALID
            session.close_tick(tick, reason=reason)
    return {"config": config.as_dict(), "config_hash": config.config_hash(), "base_seed_id": _seed_id(base_seed),
            "rival_condition": config.rival_condition, "standings": session.standings(),
            "race_results": session.race_results, "journal": session.journal, "provenance": provenance}


def run_slot_swapped_pair(config: IntegratedConfig, base_seed: int, policies: Dict[str, Policy],
                          **kwargs) -> Dict[str, Any]:
    """Same seed twice, with the two controlled teams' car slots exchanged. The team effect is
    estimated from the slot-averaged margin, removing car/grid advantage."""
    first = run_season(config, base_seed, policies, **kwargs)
    second = run_season(config.swapped(), base_seed, policies, **kwargs)
    a, b = (t.label for t in config.teams)
    margins = [r["standings"]["team_points"][a] - r["standings"]["team_points"][b] for r in (first, second)]
    return {"estimand": f"{config.rival_condition} slot-averaged constructors' margin {a} - {b}",
            "slot_assignment": [{t.label: t.slot for t in config.teams},
                                {t.label: t.slot for t in config.swapped().teams}],
            "margins": margins, "slot_averaged_margin": sum(margins) / 2, "runs": [first, second]}


def _seed_id(seed: int) -> str:
    """Seed identifier for reports; the seed itself stays with trusted infrastructure."""
    import hashlib
    return hashlib.sha256(f"f1-seed:{seed}".encode()).hexdigest()[:16]


def _strip(meta: Dict[str, Any]) -> Dict[str, Any]:
    from track_c.engineer_runtime import redact_secrets
    return redact_secrets(copy.deepcopy(meta))
