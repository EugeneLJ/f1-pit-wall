"""Adapter: the agent's final script (scripts/tmp_run_season.py.txt, verbatim) as one policy callable
for analysis/reference21_eval.py and b21_decisions.py. No logic of its own; `rules` is unused by
this script (it reads everything from the observation)."""
from importlib.machinery import SourceFileLoader
from importlib.util import module_from_spec, spec_from_loader
from pathlib import Path

_path = str(Path(__file__).resolve().parent / "scripts" / "tmp_run_season.py.txt")
_loader = SourceFileLoader("v21_gemini_03_script", _path)
_mod = module_from_spec(spec_from_loader(_loader.name, _loader))
_loader.exec_module(_mod)


def make(rules):
    def policy(obs):
        if obs["decision_type"] == "COMPONENT_DECISION":
            return _mod.handle_component_decision(obs)
        return _mod.handle_race_strategy(obs)
    return policy
