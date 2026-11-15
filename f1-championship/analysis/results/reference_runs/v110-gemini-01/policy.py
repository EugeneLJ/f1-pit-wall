"""Adapter: exposes the agent's final script (scripts/app_strategy_agent.py.txt, verbatim) as
decide_component(obs) / decide_strategy(obs) for analysis/reference_eval.py. No logic of its own;
TYRE_PARAMS is the literal the script's own main() passes to choose_race_strategy."""
from importlib.machinery import SourceFileLoader
from importlib.util import module_from_spec, spec_from_loader
from pathlib import Path

_path = str(Path(__file__).resolve().parent / "scripts" / "app_strategy_agent.py.txt")
_loader = SourceFileLoader("v110_gemini_01_script", _path)
_mod = module_from_spec(spec_from_loader(_loader.name, _loader))
_loader.exec_module(_mod)
TYRE_PARAMS = {
    'SOFT': {'offset': -0.55, 'deg': 0.35, 'life': 10, 'warmup': 0.3},
    'MEDIUM': {'offset': 0.0, 'deg': 0.14, 'life': 16, 'warmup': 0.6},
    'HARD': {'offset': 0.28, 'deg': 0.055, 'life': 24, 'warmup': 1.0},
}


def decide_component(obs):
    return _mod.choose_component_decision(obs)


def decide_strategy(obs):
    return _mod.choose_race_strategy(obs, TYRE_PARAMS)
