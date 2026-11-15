"""Configurable runtime axes for the 2.2.0 candidate (direct-API trusted runner, not the Harbor task).

Two independent axes, composed from the existing B6/B7 infrastructure (nothing is rebuilt):

  engineers: CHIEF_ONLY | GEMINI_LITE_ENGINEERS
             -> IntegratedConfig engineer condition + the trusted EngineerBroker with live
                Track C GeminiEngineerProvider (gemini-3.5-flash-lite) behind a CostGuard
  rival:     SCRIPTED      -> SOLO_COORDINATION: every other team follows the published rule
             ADAPTIVE_LLM  -> TWO_TEAM_COMPETITION, rival_condition ADAPTIVE: a DeepSeek Chief (Verda)
                              runs the second team live (providers.redbool_chief)
             FIXED_REPLAY  -> TWO_TEAM_COMPETITION, rival_condition FIXED_REPLAY: the second team's actions
                              are replayed from a recorded journal (match.ReplayPolicy); diagnostics only

Every combination runs through `match.run_season` (sealed simultaneous ticks, published fallback on any
provider failure) and is checked by `verify.replay`. Provider keys are read from environment variables by
name only; nothing here prints or stores a key. Optional `c5_weekend` composes with every combination.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable, Dict, Optional

from . import config as C
from . import match as M
from . import providers as PR
from . import verify as V
from .engineers import EngineerBroker

ENGINEER_AXIS = ("CHIEF_ONLY", "GEMINI_LITE_ENGINEERS")
RIVAL_AXIS = ("SCRIPTED", "ADAPTIVE_LLM", "FIXED_REPLAY")
SAMPLING = {"temperature": 0.0, "max_output_tokens": 8192}


class StopAfter(RuntimeError):
    """Raised by the tick limiter: the season stops cleanly at the open tick (smoke runs)."""


@dataclass(frozen=True)
class RuntimeSpec:
    engineers: str = "CHIEF_ONLY"
    rival: str = "SCRIPTED"
    benchmark_version: str = C.SCENARIO_VERSION
    c5_weekend: bool = False
    m2_tendencies: bool = False   # Kimi M2: hidden per-race tendencies of the uncontrolled (scripted) rivals
    m6_compliance: bool = False   # Kimi M6: WDC-dependent order compliance of the controlled team
    m7_weather: bool = False      # Kimi M7: weather, wet compounds, forecasts
    chief_model: str = "gemini-3.8-flash"
    engineer_model: str = "gemini-3.5-flash-lite"
    rival_model: str = PR.DEFAULT_REDBOOL_MODEL
    replay_journal: Optional[str] = None  # FIXED_REPLAY: a recorded two-team journal of the same configuration

    def validate(self) -> None:
        if self.engineers not in ENGINEER_AXIS:
            raise ValueError(f"engineers must be one of {ENGINEER_AXIS}")
        if self.rival not in RIVAL_AXIS:
            raise ValueError(f"rival must be one of {RIVAL_AXIS}")
        if self.rival == "FIXED_REPLAY" and not self.replay_journal:
            raise ValueError("FIXED_REPLAY needs replay_journal (a recorded two-team journal)")
        if self.rival != "FIXED_REPLAY" and self.replay_journal:
            raise ValueError("replay_journal is only used by FIXED_REPLAY")

    def features(self) -> list:
        return [name for name, on in (("C5", self.c5_weekend), ("M2", self.m2_tendencies),
                                      ("M6", self.m6_compliance), ("M7", self.m7_weather)) if on]

    def label(self) -> str:
        return "|".join([self.engineers, self.rival, self.benchmark_version] + self.features())


def build_config(spec: RuntimeSpec) -> C.IntegratedConfig:
    spec.validate()
    chief = {"provider": "google_genai", "model": spec.chief_model}
    if spec.rival == "SCRIPTED":
        cfg = C.solo_coordination(engineers=spec.engineers, chief=chief)
    else:
        cfg = C.two_team(2 if spec.engineers == "GEMINI_LITE_ENGINEERS" else 1, mclearn_chief=chief,
                         redbool_chief={"provider": "verda_openai_compatible", "model": spec.rival_model},
                         rival_condition="ADAPTIVE" if spec.rival == "ADAPTIVE_LLM" else "FIXED_REPLAY",
                         mclearn_engineers=spec.engineers)
    cfg = C.with_version(cfg, spec.benchmark_version)
    if spec.m2_tendencies or spec.m6_compliance or spec.m7_weather:
        cfg = C.with_features(cfg, {"m2_tendencies": spec.m2_tendencies, "m6_compliance": spec.m6_compliance,
                                    "m7_weather": spec.m7_weather})
    if spec.c5_weekend:
        if spec.benchmark_version != C.SCENARIO_VERSION:
            raise ValueError("c5_weekend requires benchmark 2.2.0")
        cfg = C.with_c5_weekend(cfg)
    return cfg


def read_journal(path: str) -> list:
    return [json.loads(line) for line in Path(path).read_text(encoding="utf-8").splitlines() if line]


def build_runtime(spec: RuntimeSpec, out_dir: Path, guard: PR.CostGuard, *,
                  chief: Optional[Callable] = None, chief_transport: Any = None,
                  engineer_transport: Any = None, rival_transport: Any = None,
                  chief_key_env: str = "GEMINI_API_KEY", rival_key_env: str = "VERDA_INFERENCE_API_KEY"):
    """Returns (config, policies, engineer_broker). `chief` replaces the Gemini Chief (tests, scripted
    baselines); transports replace the real provider clients (tests)."""
    cfg = build_config(spec)
    own = cfg.teams[0].label
    if chief is None:
        llm = PR.gemini_chief(own, spec.chief_model, chief_key_env, chief_transport, sampling=dict(SAMPLING),
                              timeout_sec=120.0, max_retries=1, price=PR.GEMINI_38_FLASH_PRICE_2026_11_14)
        chief = PR.GuardedChief(llm, guard, PR.GEMINI_38_FLASH_CEILING_PRICE)
    policies: Dict[str, Callable] = {own: chief}
    broker = None
    if spec.engineers == "GEMINI_LITE_ENGINEERS":
        from track_c.engineer_runtime import GeminiEngineerProvider
        live = {eid: PR.GuardedEngineer(GeminiEngineerProvider(eid, model=spec.engineer_model, retries=0,
                                                               transport=engineer_transport), guard, own)
                for eid in ("engineer_a", "engineer_b")}
        broker = EngineerBroker(Path(out_dir) / "engineers", live_providers={own: live})
    if spec.rival != "SCRIPTED":
        rival = cfg.teams[1].label
        if spec.rival == "ADAPTIVE_LLM":
            llm = PR.redbool_chief(rival, spec.rival_model, rival_key_env, rival_transport,
                                   sampling=dict(SAMPLING), timeout_sec=120.0, max_retries=1)
            if hasattr(chief, "chief"):
                PR.assert_isolated({own: chief.chief, rival: llm})
            policies[rival] = PR.GuardedChief(llm, guard, PR.VERDA_DEEPSEEK_PRICE_2026_11_14)
        else:
            policies[rival] = M.ReplayPolicy(read_journal(spec.replay_journal), rival)
    return cfg, policies, broker


def _limit(policy: Callable, max_ticks: int) -> Callable:
    def limited(obs):
        if int(obs["tick_id"][1:]) > max_ticks:
            raise StopAfter(f"tick limit {max_ticks} reached")
        return policy(obs)
    return limited


def run(spec: RuntimeSpec, base_seed: int, out_dir: Path, guard: PR.CostGuard, *, max_ticks: Optional[int] = None,
        observer: Optional[Callable] = None, **kwargs) -> Dict[str, Any]:
    """Play a season (or its first `max_ticks` ticks) and verify the journal by replay."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    cfg, policies, broker = build_runtime(spec, out_dir, guard, **kwargs)
    if max_ticks is not None:
        policies = {label: _limit(p, max_ticks) for label, p in policies.items()}
    result = M.run_season(cfg, base_seed, policies, engineer_broker=broker, observer=observer,
                          abort_on=(PR.BudgetExceeded, StopAfter))
    replay_broker = EngineerBroker.replaying(out_dir / "engineers") if broker is not None else None
    try:
        replayed = V.replay(cfg, base_seed, result["journal"], engineer_broker=replay_broker,
                            require_complete=result["complete"])
        replay = {"ok": replayed["standings"] == result["standings"], "resolved_ticks": replayed["resolved_ticks"]}
    except Exception as exc:  # reported, never hidden
        replay = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
    statuses: Dict[str, Dict[str, int]] = {}
    for p in result["provenance"]:
        statuses.setdefault(p["team"], {}).setdefault(p["status"], 0)
        statuses[p["team"]][p["status"]] += 1
    return {"spec": asdict(spec), "label": spec.label(), "config": result["config"], "config_hash": result["config_hash"],
            "rival_condition": result["rival_condition"], "complete": result["complete"], "aborted": result["aborted"],
            "standings": result["standings"], "race_results": result["race_results"], "replay": replay,
            "provenance_status": statuses, "cost": guard.summary(), "journal": result["journal"],
            "provenance": result["provenance"]}
