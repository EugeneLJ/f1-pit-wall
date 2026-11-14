"""Trusted multi-party replay of an integrated journal (journal_version 2).

The verifier trusts nothing the session concluded: it checks the hash chain, rebuilds a
fresh session from the configuration and the hidden seed, re-submits every recorded
submission (or re-applies the recorded timeout fallback), and recomputes every team's
observation hash before and after each tick. Engineer reports are re-supplied from the
trusted, hash-chained record store by exact observation hash (RECORDED replay), so a
report that was altered, missing or not the one delivered breaks the replay.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from ..journal import GENESIS_HASH, canonical, sha256_text
from .config import IntegratedConfig
from .session import CHAMPIONSHIP_COMPLETE, SUBMITTED, IntegratedSession


class ReplayError(ValueError):
    pass


def verify_chain(journal: List[Dict[str, Any]]) -> None:
    prev = GENESIS_HASH
    for number, entry in enumerate(journal, start=1):
        if entry.get("journal_version") != 2 or entry.get("seq") != number:
            raise ReplayError(f"entry {number}: wrong version or sequence")
        if entry.get("prev_hash") != prev:
            raise ReplayError(f"entry {number}: broken chain")
        body = {k: v for k, v in entry.items() if k != "entry_hash"}
        if sha256_text(prev + canonical(body)) != entry.get("entry_hash"):
            raise ReplayError(f"entry {number}: entry hash mismatch")
        prev = entry["entry_hash"]


def replay(config: IntegratedConfig, base_seed: int, journal: List[Dict[str, Any]],
           engineer_broker: Any = None, coeffs: Optional[dict] = None,
           require_complete: bool = True) -> Dict[str, Any]:
    """Replay and return the recomputed standings. Raises ReplayError on any mismatch."""
    verify_chain(journal)
    session = IntegratedSession(config, base_seed, coeffs=coeffs, engineer_broker=engineer_broker,
                                clock=lambda: 0.0)
    resolved = 0
    for entry in journal:
        if entry["kind"] == "rejected":
            continue
        if entry["kind"] != "resolved":
            raise ReplayError(f"unknown entry kind {entry['kind']}")
        if entry["tick_id"] != session.tick_id or entry["decision_type"] != session.decision_type:
            raise ReplayError(f"{entry['tick_id']}: tick or phase out of order")
        if session._obs_hash != entry["obs_before_sha256"]:
            raise ReplayError(f"{entry['tick_id']}: observation hash before the tick differs")
        recorded_hashes = {label: [r.get("record_hash") for r in recs]
                           for label, recs in session._engineer_records.items()}
        if recorded_hashes != entry["engineer_record_hashes"]:
            raise ReplayError(f"{entry['tick_id']}: Engineer records differ from the delivered ones")
        tick = session.tick_id
        late = []
        for label, sub in sorted(entry["submissions"].items()):
            if sha256_text(canonical(sub["action"])) != sub["action_sha256"]:
                raise ReplayError(f"{tick}: {label} action hash mismatch")
            if sub["status"] == SUBMITTED:
                session.submit(label, tick, sub["action"], submitted_via=sub["submitted_via"])
            else:
                late.append((label, sub))
        if late:
            for label, sub in late:
                if sub["action"] != session.fallback_action(label):
                    raise ReplayError(f"{tick}: {label} fallback differs from the published fallback")
            session.close_tick(tick, reason=late[0][1]["status"])
        if session._obs_hash != entry["obs_after_sha256"]:
            raise ReplayError(f"{tick}: observation hash after the tick differs")
        resolved += 1
    if require_complete and session.decision_type != CHAMPIONSHIP_COMPLETE:
        raise ReplayError("journal does not complete the championship")
    return {"resolved_ticks": resolved, "standings": session.standings(),
            "race_results": session.race_results}
