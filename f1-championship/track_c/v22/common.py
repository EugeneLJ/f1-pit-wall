"""Shared isolated 2.2.0 M2/M7 opt-in and deterministic utilities."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import math
from typing import Any


@dataclass(frozen=True)
class V22Config:
    """All proposal modules are disabled unless explicitly enabled by their owner."""

    m2_enabled: bool = False
    m7_enabled: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.m2_enabled, bool) or not isinstance(self.m7_enabled, bool):
            raise ValueError("M2/M7 flags must be booleans")

    def as_dict(self) -> dict[str, bool]:
        return {"m2_enabled": self.m2_enabled, "m7_enabled": self.m7_enabled}


def validate_seed(seed: Any) -> int:
    if isinstance(seed, bool) or not isinstance(seed, int) or not 0 <= seed < 2**256:
        raise ValueError("seed must be a non-negative integer below 2^256")
    return seed


def finite(value: Any, *, minimum: float | None = None, maximum: float | None = None) -> float:
    if isinstance(value, dict) and set(value) == {"value", "provenance"}:
        value = value["value"]
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError("expected a finite number")
    number = float(value)
    if minimum is not None and number < minimum or maximum is not None and number > maximum:
        raise ValueError("number is outside its permitted interval")
    return number


def parts_key(value: tuple[Any, ...]) -> bytes:
    return json.dumps(value, sort_keys=False, separators=(",", ":"), allow_nan=False).encode("utf-8")


def uniform(seed: int, *parts: Any) -> float:
    """Domain-separated [0,1) draw; no global/action-order random state."""
    validate_seed(seed)
    digest = hashlib.sha256(parts_key((seed, *parts))).digest()
    return int.from_bytes(digest[:8], "big") / 2**64


def normal(seed: int, *parts: Any) -> float:
    u1 = uniform(seed, *parts, "box-muller-u1")
    u2 = uniform(seed, *parts, "box-muller-u2")
    return math.sqrt(-2.0 * math.log(u1)) * math.cos(2.0 * math.pi * u2)


def categorical(seed: int, labels: tuple[str, ...], weights: tuple[float, ...], *parts: Any) -> str:
    if len(labels) != len(weights) or not labels or len(set(labels)) != len(labels):
        raise ValueError("categorical labels/weights are malformed")
    if any(weight < 0 or not math.isfinite(weight) for weight in weights):
        raise ValueError("categorical weights must be finite and non-negative")
    total = sum(weights)
    if total <= 0:
        raise ValueError("categorical weights need positive mass")
    draw = uniform(seed, *parts) * total
    cumulative = 0.0
    for label, weight in zip(labels, weights):
        cumulative += weight
        if draw < cumulative:
            return label
    return labels[-1]


def reject_public_secrets(value: Any, path: str = "") -> None:
    """Key allow/deny projection guard for private analysis objects."""
    secret_parts = (
        "seed", "rng", "secret", "hidden", "true_rain", "rain_path", "random_draw",
        "future_draw", "tendency_assignment", "bias_assignment", "private",
    )
    if isinstance(value, dict):
        for key, child in value.items():
            name = str(key).lower()
            if any(part in name for part in secret_parts):
                raise ValueError(f"private M2/M7 field in public projection: {path}{key}")
            reject_public_secrets(child, f"{path}{key}.")
    elif isinstance(value, (list, tuple)):
        for index, child in enumerate(value):
            reject_public_secrets(child, f"{path}{index}.")
    elif isinstance(value, int) and not isinstance(value, bool) and value.bit_length() > 64:
        raise ValueError(f"oversized private-looking integer at {path}")
