"""Adapter: the agent's final script (scripts/app_run_championship.py.txt, verbatim) as one policy
callable for analysis/reference21_eval.py. `rules` is the public `f1ctl rules` payload, as the
script's own run_season() passes it. No logic of its own."""
from importlib.machinery import SourceFileLoader
from importlib.util import module_from_spec, spec_from_loader
from pathlib import Path

_path = str(Path(__file__).resolve().parent / "scripts" / "app_run_championship.py.txt")
_loader = SourceFileLoader("v21_gemini_01_script", _path)
_mod = module_from_spec(spec_from_loader(_loader.name, _loader))
_loader.exec_module(_mod)


def make(rules):
    def policy(obs):
        if obs["decision_type"] == "COMPONENT_DECISION":
            return _mod.decide_components(obs, rules)
        return _mod.decide_race_strategy(obs, rules)
    return policy
