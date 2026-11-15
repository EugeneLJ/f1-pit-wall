"""Adapter: exposes the agent's final script (scripts/app_strategist.py.txt, verbatim) as
decide_component(obs) / decide_strategy(obs) for analysis/reference_eval.py. No logic of its own."""
from importlib.machinery import SourceFileLoader
from importlib.util import module_from_spec, spec_from_loader
from pathlib import Path

_path = str(Path(__file__).resolve().parent / "scripts" / "app_strategist.py.txt")
_loader = SourceFileLoader("v110_gemini_02_script", _path)
_mod = module_from_spec(spec_from_loader(_loader.name, _loader))
_loader.exec_module(_mod)


def decide_component(obs):
    return _mod.decide_components(obs)


def decide_strategy(obs):
    return _mod.decide_race_strategy(obs)
