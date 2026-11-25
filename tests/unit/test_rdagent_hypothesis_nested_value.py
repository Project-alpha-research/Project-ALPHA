"""A nested value in a hypothesis text field must reach RD-Agent as JSON text.

RD-Agent's hypothesis step asks the model for ``dict[str, str]`` and its backend refuses a
reply whose values are not all strings. The stub backend below mirrors that check; the
upstream proposer is a stub too, so the test runs offline without RD-Agent installed.
"""

from __future__ import annotations

import importlib.util
import json
import sys
import typing
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

WORKER = Path(__file__).resolve().parents[2] / "workers/rdagent"
PROPOSAL = "rdagent.scenarios.qlib.proposal.factor_proposal"
MODEL: dict[str, Any] = {}


def check_target(text: str, target: Any) -> None:
    value = json.loads(text)
    flat = isinstance(value, dict) and all(
        isinstance(k, str) and isinstance(v, str) for k, v in value.items()
    )
    wants_text = typing.get_origin(target) is dict and typing.get_args(target) == (str, str)
    if wants_text and not flat:
        raise ValueError("model reply does not match dict[str, str]")
    MODEL["checked"].append(target)


def make_backend() -> type:
    class APIBackend:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            pass

        def build_messages_and_create_chat_completion(
            self,
            user_prompt: str,
            system_prompt: str | None = None,
            *,
            json_mode: bool = False,
            json_target_type: Any = None,
            **kwargs: Any,
        ) -> str:
            messages = [
                {"role": "system", "content": system_prompt or ""},
                {"role": "user", "content": user_prompt},
            ]
            return self._create_chat_completion_auto_continue(
                messages=messages, json_mode=json_mode, json_target_type=json_target_type
            )

        def _create_chat_completion_auto_continue(
            self,
            messages: list[dict[str, str]],
            json_mode: bool = False,
            json_target_type: Any = None,
            **kwargs: Any,
        ) -> str:
            text = self._create_chat_completion_inner_function(
                messages=messages, json_mode=json_mode
            )
            if json_target_type is not None:
                check_target(text, json_target_type)
            return text

        def _create_chat_completion_inner_function(
            self, messages: list[dict[str, str]], json_mode: bool = False, **kwargs: Any
        ) -> str:
            return str(MODEL["reply"])

    return APIBackend


class UpstreamHypothesisGen:
    """Stands in for QlibFactorHypothesisGen: one JSON call typed dict[str, str]."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        pass

    def prepare_context(self, trace: Any) -> tuple[dict[str, Any], bool]:
        return {"hypothesis_and_feedback": ""}, True

    def gen(self, trace: Any, plan: Any = None) -> Any:
        backend = sys.modules[PROPOSAL].APIBackend()
        reply = backend.build_messages_and_create_chat_completion(
            user_prompt="propose one factor hypothesis",
            system_prompt="scenario",
            json_mode=True,
            json_target_type=dict[str, str],
        )
        return json.loads(reply)


def plain(name: str, base: type = object) -> type:
    def init(self: Any, *args: Any, **kwargs: Any) -> None:
        pass

    return type(name, (base,), {"__init__": init})


class Template:
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        pass

    def r(self, **kwargs: Any) -> str:
        return ""


@pytest.fixture
def judge(monkeypatch: pytest.MonkeyPatch) -> ModuleType:
    MODEL.clear()
    MODEL.update(reply="", checked=[])
    for name in (
        "ALPHA_FACTOR_TRIAL_LEDGER",
        "ALPHA_FACTOR_DISCUSS",
        "ALPHA_FACTOR_RUN_DIR",
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.syspath_prepend(str(WORKER))
    backend = make_backend()

    def stub(name: str, package: bool = False, **attrs: Any) -> ModuleType:
        module = ModuleType(name)
        if package:
            module.__path__ = []
        for key, value in attrs.items():
            setattr(module, key, value)
        monkeypatch.setitem(sys.modules, name, module)
        return module

    for name in (
        "rdagent",
        "rdagent.core",
        "rdagent.oai",
        "rdagent.scenarios",
        "rdagent.scenarios.qlib",
        "rdagent.scenarios.qlib.experiment",
        "rdagent.scenarios.qlib.proposal",
        "rdagent.utils.agent",
    ):
        stub(name, package=True)
    stub("rdagent.core.developer", Developer=plain("Developer"))
    stub("rdagent.core.exception", FactorEmptyError=plain("FactorEmptyError", Exception))
    stub(
        "rdagent.core.proposal",
        Experiment2Feedback=plain("Experiment2Feedback"),
        HypothesisFeedback=plain("HypothesisFeedback"),
    )
    stub("rdagent.oai.llm_utils", APIBackend=backend)
    stub(
        "rdagent.scenarios.qlib.experiment.factor_experiment",
        QlibFactorScenario=plain("QlibFactorScenario"),
    )
    stub(
        "rdagent.scenarios.qlib.experiment.quant_experiment",
        QlibQuantScenario=plain("QlibQuantScenario"),
    )
    stub(PROPOSAL, APIBackend=backend, QlibFactorHypothesisGen=UpstreamHypothesisGen)
    stub(
        "rdagent.utils",
        package=True,
        convert2bool=lambda value: str(value).lower() in {"true", "yes", "1"},
    )
    stub("rdagent.utils.agent.tpl", T=Template)
    stub("alpha_factor_coder", demote_in_file=lambda *args, **kwargs: None)
    stub(
        "alpha_factor_data",
        check_prefix_invariance=lambda *args, **kwargs: {"status": "PASS"},
        current_universe=lambda *args, **kwargs: "test universe",
    )

    spec = importlib.util.spec_from_file_location(
        "alpha_factor_judge", WORKER / "alpha_factor_judge.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, "alpha_factor_judge", module)
    spec.loader.exec_module(module)
    return module


def test_nested_value_in_text_field_arrives_as_json_text(judge: ModuleType) -> None:
    nested = {"mechanism": "overreaction", "horizon_days": 5, "liquid_only": True}
    MODEL["reply"] = json.dumps(
        {
            "hypothesis": "Short-term reversal on liquid coins",
            "reason": nested,
            "concise_reason": "Prices overshoot after large moves",
        }
    )

    result = judge.AlphaFactorHypothesisGen().gen(None)

    assert result["hypothesis"] == "Short-term reversal on liquid coins"
    assert result["concise_reason"] == "Prices overshoot after large moves"
    assert isinstance(result["reason"], str)
    assert json.loads(result["reason"]) == nested


def test_flat_reply_passes_unchanged(judge: ModuleType) -> None:
    reply = {
        "hypothesis": "Volume surge predicts continuation",
        "reason": "Attention brings follow-on buying",
        "concise_reason": "Attention effect",
    }
    MODEL["reply"] = json.dumps(reply)

    result = judge.AlphaFactorHypothesisGen().gen(None)

    assert result == reply
