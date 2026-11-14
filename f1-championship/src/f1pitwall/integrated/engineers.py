"""Engineer A/B integration (Track C runtime, a461a98) under trusted session ownership.

The broker is owned by the trusted host of the session (never the agent): it projects the
Chief's team-local snapshot to driver-local Engineer observations, runs the configured
provider through Track C's `EngineerRuntimeHarness`, and appends every record (VALID,
MISSING or INVALID) to a hash-chained store in a directory the agent cannot write. The
session puts the validated reports into the Chief's observation (so they are covered by the
journal's observation hashes) and journals the record hashes. Reports are data: nothing here
can submit an action or touch race state.

Replay: `EngineerBroker.replaying(store_dir)` re-supplies the exact recorded records by
(team, tick, engineer, observation hash); a missing or altered record raises.
"""

from __future__ import annotations

import copy
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

CONDITION_TO_RUNTIME = {
    "MOCK_ENGINEERS": "NOMINAL_CONFIDENCE_CONTROL",
    "NOMINAL_CONFIDENCE_CONTROL": "NOMINAL_CONFIDENCE_CONTROL",
    "HIGH_SELF_REPORTED_CONFIDENCE_CONTROL": "HIGH_SELF_REPORTED_CONFIDENCE_CONTROL",
    "CONFLICTING_LOCAL_RECOMMENDATIONS": "CONFLICTING_LOCAL_RECOMMENDATIONS",
    "GEMINI_LITE_ENGINEERS": "GEMINI_LITE_ENGINEERS",
}


def _slug(label: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", label.lower()).strip("_")


class EngineerBroker:
    def __init__(self, store_dir: Path, live_providers: Optional[Dict[str, Dict[str, Any]]] = None,
                 recorded_from: Optional[Path] = None, replay_exact: bool = False) -> None:
        """live_providers: {team label: {engineer_id: provider}} for GEMINI_LITE_ENGINEERS.
        recorded_from: store directory whose records serve RECORDED_RECOMMENDATIONS.
        replay_exact: verification mode, every record must come from store_dir."""
        from track_c.engineer_runtime import ImmutableRecommendationStore  # noqa: F401 (import check)
        self.store_dir = Path(store_dir)
        self.live = live_providers or {}
        self.recorded_from = Path(recorded_from) if recorded_from else None
        self.replay_exact = replay_exact

    @classmethod
    def replaying(cls, store_dir: Path) -> "EngineerBroker":
        return cls(store_dir, replay_exact=True)

    def _store(self, root: Path, label: str):
        from track_c.engineer_runtime import ImmutableRecommendationStore
        return ImmutableRecommendationStore(root / _slug(label) / "engineer_records.jsonl")

    def collect(self, label: str, condition: str, chief_observation: Dict[str, Any], tick_id: str) -> List[Dict[str, Any]]:
        from track_c.engineer_runtime import (EngineerRuntimeHarness, build_runtime_record,
                                              format_runtime_observation, observation_hash)
        if self.replay_exact:
            return self._replay(self.store_dir, label, chief_observation, tick_id, original=True)
        if condition == "RECORDED_RECOMMENDATIONS":
            if self.recorded_from is None:
                raise ValueError("RECORDED_RECOMMENDATIONS needs a recorded store")
            records = self._recorded(label, chief_observation)
        else:
            runtime = CONDITION_TO_RUNTIME.get(condition)
            if runtime is None:
                raise ValueError(f"unsupported Engineer condition {condition}")
            harness = EngineerRuntimeHarness(live_providers=self.live.get(label) or None)
            records = harness.collect(chief_observation, runtime)
        store = self._store(self.store_dir, label)
        out = []
        for record in records:
            body = {k: v for k, v in record.items() if k not in ("record_hash", "previous_record_hash")}
            body.update({"team": label, "tick_id": tick_id, "condition": condition})
            out.append(store.append(body))
        return out

    def _recorded(self, label, chief_observation):
        """Exact-observation reuse of earlier VALID records (RECORDED_RECOMMENDATIONS).
        Because observations include the tick id and race state, a recording only matches the
        same seed, configuration and trajectory; otherwise the record is explicitly MISSING."""
        from track_c.engineer_runtime import build_runtime_record, format_runtime_observation, observation_hash
        store = self._store(self.recorded_from, label)
        out = []
        for engineer_id in ("engineer_a", "engineer_b"):
            local = format_runtime_observation(chief_observation, engineer_id)
            try:
                found = store.replay(engineer_id, local)
                out.append(build_runtime_record(engineer_id=engineer_id, observation=local,
                                                source="RECORDED_REPLAY", recommendation=found["recommendation"],
                                                metadata={"replayed_record_hash": found["record_hash"]}))
            except KeyError:
                out.append(build_runtime_record(engineer_id=engineer_id, observation=local, source="MISSING",
                                                recommendation=None, error="no_exact_recorded_recommendation"))
        return out

    def _replay(self, root, label, chief_observation, tick_id, original):
        from track_c.engineer_runtime import format_runtime_observation, observation_hash
        records = [r for r in self._store(root, label).read_all() if r.get("tick_id") == tick_id]
        out = []
        for engineer_id in ("engineer_a", "engineer_b"):
            target = observation_hash(format_runtime_observation(chief_observation, engineer_id))
            match = [r for r in records if r["engineer_id"] == engineer_id and r["observation_hash"] == target]
            if len(match) != 1:
                raise ValueError(f"{label} {tick_id} {engineer_id}: no unique record for this exact observation")
            out.append(copy.deepcopy(match[0]))
        return out
