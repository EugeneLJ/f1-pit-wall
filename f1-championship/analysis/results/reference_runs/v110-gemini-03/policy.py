"""Adapter: exposes the agent's final script (scripts/app_strategist.py.txt, verbatim) as
decide_component(obs) / decide_strategy(obs) for analysis/reference_eval.py. No logic of its own:
the RaceEvaluator is built from the observation exactly as the script's main() does at each new race."""
from importlib.machinery import SourceFileLoader
from importlib.util import module_from_spec, spec_from_loader
from pathlib import Path

_path = str(Path(__file__).resolve().parent / "scripts" / "app_strategist.py.txt")
_loader = SourceFileLoader("v110_gemini_03_script", _path)
_mod = module_from_spec(spec_from_loader(_loader.name, _loader))
_loader.exec_module(_mod)
_cache = {}


def decide_component(obs):
    return _mod.choose_component_decision(obs)


def decide_strategy(obs):
    key = (obs["championship"]["race_index"], obs["current_track"]["name"])
    if key not in _cache:
        _cache.clear()
        track, pit = obs["current_track"], obs["race_progress"]["pit"]
        _cache[key] = _mod.RaceEvaluator(track["tyre_degradation"], pit["loss_sec"]["GREEN"],
                                         pit["out_lap_warmup_sec"], track["overtaking_difficulty"])
    act_a, act_b = _mod.choose_race_strategy(obs, _cache[key])
    return {"type": "RACE_STRATEGY", "driver_a": act_a, "driver_b": act_b}
