"""The hypothesis step swaps APIBackend in the module whose gen reads it.

Upstream RD-Agent defines ``gen`` in ``rdagent.components.proposal`` and looks up
``APIBackend`` in that module's globals. Swapping the name anywhere else (for
example in ``rdagent.scenarios.qlib.proposal.factor_proposal``) leaves the
nested-value tolerance unused.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

WORKER = Path(__file__).resolve().parents[2] / "workers/rdagent"


class UpstreamBackend:
    """Stands in for rdagent.oai.llm_utils.APIBackend."""

    reply = json.dumps({"hypothesis": {"window": 5, "skip": 1}, "reason": "plain"})

    def _create_chat_completion_auto_continue(self, *args: Any, **kwargs: Any) -> str:
        return self.reply


def _permissive(name: str) -> ModuleType:
    module = ModuleType(name)

    def __getattr__(attr: str) -> Any:
        if attr.startswith("__"):
            raise AttributeError(attr)
        made = type(attr, (), {"__init__": lambda self, *a, **k: None})
        setattr(module, attr, made)
        return made

    module.__getattr__ = __getattr__  # type: ignore[method-assign]
    return module


def _load_judge(
    monkeypatch: pytest.MonkeyPatch, seen: list[Any]
) -> tuple[Any, ModuleType, ModuleType]:
    names = [
        "rdagent",
        "rdagent.core",
        "rdagent.core.developer",
        "rdagent.core.exception",
        "rdagent.core.proposal",
        "rdagent.oai",
        "rdagent.oai.llm_utils",
        "rdagent.components",
        "rdagent.components.proposal",
        "rdagent.scenarios",
        "rdagent.scenarios.qlib",
        "rdagent.scenarios.qlib.experiment",
        "rdagent.scenarios.qlib.experiment.factor_experiment",
        "rdagent.scenarios.qlib.experiment.quant_experiment",
        "rdagent.scenarios.qlib.proposal",
        "rdagent.scenarios.qlib.proposal.factor_proposal",
        "rdagent.utils",
        "rdagent.utils.agent",
        "rdagent.utils.agent.tpl",
        "alpha_factor_coder",
    ]
    modules = {name: _permissive(name) for name in names}
    components = modules["rdagent.components.proposal"]
    factor_proposal = modules["rdagent.scenarios.qlib.proposal.factor_proposal"]
    modules["rdagent.oai.llm_utils"].APIBackend = UpstreamBackend  # type: ignore[attr-defined]
    components.APIBackend = UpstreamBackend  # type: ignore[attr-defined]
    factor_proposal.APIBackend = UpstreamBackend  # type: ignore[attr-defined]

    class QlibFactorHypothesisGen:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            pass

        def gen(self, trace: Any, plan: Any = None) -> Any:
            # Like upstream: gen is defined in rdagent.components.proposal and reads
            # APIBackend from that module's globals.
            backend = sys.modules["rdagent.components.proposal"].APIBackend
            seen.append(backend)
            return json.loads(
                backend()._create_chat_completion_auto_continue(json_target_type=dict[str, str])
            )

    factor_proposal.QlibFactorHypothesisGen = QlibFactorHypothesisGen  # type: ignore[attr-defined]
    for name, module in modules.items():
        monkeypatch.setitem(sys.modules, name, module)
    monkeypatch.syspath_prepend(str(WORKER))
    spec = importlib.util.spec_from_file_location(
        "alpha_factor_judge_right_module", WORKER / "alpha_factor_judge.py"
    )
    assert spec is not None and spec.loader is not None
    judge = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, "alpha_factor_judge_right_module", judge)
    spec.loader.exec_module(judge)
    return judge, components, factor_proposal


def test_gen_swaps_backend_in_components_proposal(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[Any] = []
    judge, _, _ = _load_judge(monkeypatch, seen)
    result = judge.AlphaFactorHypothesisGen().gen(None)
    assert len(seen) == 1
    used = seen[0]
    assert used is not UpstreamBackend, (
        "gen read the unwrapped APIBackend from rdagent.components.proposal"
    )
    assert issubclass(used, UpstreamBackend)
    assert result == {"hypothesis": json.dumps({"window": 5, "skip": 1}), "reason": "plain"}


def test_gen_restores_backends_after_round(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[Any] = []
    judge, components, factor_proposal = _load_judge(monkeypatch, seen)
    judge.AlphaFactorHypothesisGen().gen(None)
    assert components.APIBackend is UpstreamBackend
    assert factor_proposal.APIBackend is UpstreamBackend


def test_text_field_backend_turns_nested_value_into_json_text(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    judge, _, _ = _load_judge(monkeypatch, [])
    wrapped = judge.text_field_backend(UpstreamBackend)
    text = wrapped()._create_chat_completion_auto_continue(json_target_type=dict[str, str])
    assert json.loads(text) == {
        "hypothesis": json.dumps({"window": 5, "skip": 1}),
        "reason": "plain",
    }
    other = wrapped()._create_chat_completion_auto_continue(json_target_type=None)
    assert other == UpstreamBackend.reply
