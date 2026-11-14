"""Hash-chained decision journal shared by the simulator sidecar and the verifier.

The sidecar appends one entry per request that touches the championship. The
verifier never trusts the sidecar's conclusions: it re-checks the hash chain and
replays every accepted action from the hidden seed with its own trusted copy of
this package, recomputing each observation hash.
"""

from __future__ import annotations

import copy
import hashlib
import json
from typing import Any, Dict, List, Optional

from .championship_contract import CHAMPIONSHIP_COMPLETE, ChampionshipSession

JOURNAL_VERSION = 1
GENESIS_HASH = "0" * 64
ENTRY_KINDS = ("accepted", "rejected")
ENTRY_FIELDS = {
    "journal_version", "seq", "kind", "decision_id", "decision_type", "action",
    "error_code", "obs_before_sha256", "obs_after_sha256", "t_received", "t_done",
    "prev_hash", "entry_hash",
}


def canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def observation_hash(observation: Dict[str, Any]) -> str:
    return sha256_text(canonical(observation))


def decision_id(accepted_count: int) -> str:
    """Public identifier of the next decision; changes after every accepted action."""
    return f"d{accepted_count + 1:03d}"


def seal_entry(entry: Dict[str, Any], prev_hash: str) -> Dict[str, Any]:
    body = dict(entry)
    body["prev_hash"] = prev_hash
    body.pop("entry_hash", None)
    body["entry_hash"] = sha256_text(prev_hash + canonical(body))
    return body


class JournalError(ValueError):
    """The journal is malformed, out of order, or inconsistent with replay."""


def parse_journal(text: str) -> List[Dict[str, Any]]:
    entries = []
    for number, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            raise JournalError(f"blank journal line {number}")
        try:
            entry = json.loads(line)
        except json.JSONDecodeError as exc:
            raise JournalError(f"journal line {number} is not JSON") from exc
        if not isinstance(entry, dict) or set(entry) != ENTRY_FIELDS:
            raise JournalError(f"journal line {number} has missing or unknown fields")
        entries.append(entry)
    return entries


def verify_chain(entries: List[Dict[str, Any]]) -> None:
    prev = GENESIS_HASH
    for index, entry in enumerate(entries):
        if entry["journal_version"] != JOURNAL_VERSION:
            raise JournalError("unsupported journal version")
        if entry["seq"] != index + 1:
            raise JournalError(f"journal sequence break at entry {index + 1}")
        if entry["kind"] not in ENTRY_KINDS:
            raise JournalError(f"unknown entry kind at entry {index + 1}")
        if entry["prev_hash"] != prev:
            raise JournalError(f"hash chain break at entry {index + 1}")
        if seal_entry(entry, prev)["entry_hash"] != entry["entry_hash"]:
            raise JournalError(f"entry hash mismatch at entry {index + 1}")
        prev = entry["entry_hash"]


def replay(entries: List[Dict[str, Any]], base_seed: int) -> Dict[str, Any]:
    """Verify the chain, then replay every entry from the hidden seed.

    Accepted entries must reproduce the recorded before/after observations.
    Rejected entries must reproduce the recorded before-observation and must
    also be rejected by the trusted session (or be a protocol-level rejection
    that never reached the session). Returns the final trusted session state.
    """
    verify_chain(entries)
    session = ChampionshipSession(base_seed=base_seed)
    accepted = 0
    rejected = 0
    for entry in entries:
        before = observation_hash(session.observation())
        if entry["obs_before_sha256"] != before:
            raise JournalError(f"observation mismatch before entry {entry['seq']}")
        if entry["kind"] == "accepted":
            if entry["decision_id"] != decision_id(accepted):
                raise JournalError(f"decision id out of order at entry {entry['seq']}")
            if entry["decision_type"] != session.decision_type:
                raise JournalError(f"decision type mismatch at entry {entry['seq']}")
            try:
                session.submit(copy.deepcopy(entry["action"]))
            except ValueError as exc:
                raise JournalError(f"accepted entry {entry['seq']} fails trusted replay") from exc
            accepted += 1
            if entry["obs_after_sha256"] != observation_hash(session.observation()):
                raise JournalError(f"observation mismatch after entry {entry['seq']}")
        else:
            rejected += 1
            if entry["obs_after_sha256"] is not None:
                raise JournalError(f"rejected entry {entry['seq']} claims a transition")
            if entry["error_code"] == "invalid_action":
                probe = copy.deepcopy(session)
                try:
                    probe.submit(copy.deepcopy(entry["action"]))
                except ValueError:
                    pass
                else:
                    raise JournalError(f"rejected entry {entry['seq']} is legal under replay")
    return {
        "session": session,
        "accepted": accepted,
        "rejected": rejected,
        "complete": session.decision_type == CHAMPIONSHIP_COMPLETE,
        "head_hash": entries[-1]["entry_hash"] if entries else GENESIS_HASH,
    }
