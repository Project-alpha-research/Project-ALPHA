"""Socket-free worker regressions; upstream classes are replaced only at import seams."""

from __future__ import annotations

import ast
import importlib
import json
import sys
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import Mock

import pytest
from tests.unit.test_rdagent_factor_judge import swing_parts

WORKER = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(WORKER))
launch = importlib.import_module("factor_loop_launch")
memory = importlib.import_module("research_memory")
gateway = importlib.import_module("model_gateway")


def coder_parts() -> dict[str, Any]:
    tree = ast.parse((WORKER / "alpha_factor_coder.py").read_text())
    selected = {"BudgetExhausted", "embedding_failure", "_record_skip", "tolerant_embeddings"}
    nodes = [
        n
        for n in tree.body
        if isinstance(n, (ast.FunctionDef, ast.ClassDef)) and n.name in selected
    ]
    namespace: dict[str, Any] = {
        "Any": Any,
        "Path": Path,
        "Iterator": Iterator,
        "contextmanager": contextmanager,
        "datetime": datetime,
        "UTC": UTC,
        "json": json,
        "hashlib": importlib.import_module("hashlib"),
    }
    exec(compile(ast.Module(body=nodes, type_ignores=[]), "coder-contract", "exec"), namespace)
    return namespace


@pytest.mark.parametrize("wrapped", [False, True])
def test_budget_refusal_is_not_a_memory_skip(tmp_path: Path, wrapped: bool) -> None:
    ns = coder_parts()
    cap = gateway.GatewayError(429, "budget_exhausted", "budget exhausted: run calls")
    error: Exception = RuntimeError("Failed to get chat completion") if wrapped else cap
    if wrapped:
        error.__cause__ = cap
    graph = SimpleNamespace(add_node=Mock(side_effect=error))
    record = tmp_path / "memory-skips.jsonl"
    with (
        pytest.raises(ns["BudgetExhausted"], match="budget exhausted"),
        ns["tolerant_embeddings"](graph, record),
    ):
        graph.add_node(SimpleNamespace(embedding=None))
    assert not record.exists()


def test_only_input_refusals_skip_and_log_the_real_cause(tmp_path: Path) -> None:
    ns = coder_parts()
    refusal = gateway.GatewayError(
        400, "embedding_input_refused", "embedding input exceeds context"
    )
    outer = RuntimeError("Failed to get chat completion")
    outer.__cause__ = refusal
    graph = SimpleNamespace(add_node=Mock(side_effect=outer))
    record = tmp_path / "memory-skips.jsonl"
    with ns["tolerant_embeddings"](graph, record):
        graph.add_node(SimpleNamespace(embedding=None))
    assert "embedding input exceeds context" in json.loads(record.read_text())["error"]
    graph.add_node = Mock(side_effect=RuntimeError("unrelated failure"))
    with (
        pytest.raises(RuntimeError, match="unrelated"),
        ns["tolerant_embeddings"](graph, record),
    ):
        graph.add_node(SimpleNamespace(embedding=None))


def test_ridge_composite_inherits_every_input_family() -> None:
    ns = swing_parts()
    description = "Ridge composite of volatility_28d, drawdown_90d, skew_28d and autocorr_7d"
    families = ns["idea_family"]("ml_ridge", description, "ridge(features)").split("; ")
    assert set(families) == {
        "volatility and beta",
        "drawdown",
        "skewness and lottery returns",
        "momentum and trend",
    }
    rows = [
        {
            "name": "ml_ridge",
            "description": description,
            "formulation": "ridge(features)",
            "schema": "AlphaRdagentFactorTrialV2",
            "status": "FAILED",
            "screen": {},
        }
        for _ in range(3)
    ]
    summary = ns["family_summary"](rows, 3)
    for family in families:
        assert f"{family}: 3 tries" in summary
    assert "Do not propose" in summary and "composites" in summary
    assert (
        ns["idea_family"]("ml_ridge", "unknown features", "ridge(x)") == "composite: unknown inputs"
    )


def test_resume_ignores_partial_checkpoint_and_records_abandonment(tmp_path: Path) -> None:
    old = tmp_path / "old/work/log/__session__"
    for folder, name in (("0", "4_record"), ("1", "1_coding")):
        (old / folder).mkdir(parents=True)
        (old / folder / name).write_bytes(b"checkpoint")
    current = tmp_path / "new"
    current.mkdir()
    plan = memory.prepare(
        tmp_path / "memory",
        run_id="new",
        run_dir=current,
        source_sha256="pin",
        judge_sha256="judge",
    )
    loaded = SimpleNamespace(trace=SimpleNamespace(hist=["completed-round"], scen="scene"))
    cls = Mock(return_value=SimpleNamespace(trace=SimpleNamespace(hist=[], scen="scene")))
    cls.load.return_value = loaded
    env = {
        **plan.env,
        "ALPHA_RDAGENT_CONTINUE_SESSION": str(old),
        "ALPHA_RDAGENT_CONTINUE_LOOPS": "1",
        "LOG_TRACE_PATH": str(current / "log"),
    }
    loop, total = memory.open_factor_loop(cls, SimpleNamespace(), 2, env)
    assert cls.load.call_args.args[0] == old / "0/4_record"
    assert loop.trace.hist == ["completed-round"]
    assert total == 2  # fresh scheduler, shared completed history
    abandoned = json.loads((tmp_path / "old/rounds.jsonl").read_text())
    assert abandoned["status"] == "abandoned_at_cap" and abandoned["loop"] == 1
    assert not (tmp_path / "old/evaluations.jsonl").exists()


def test_call_split_counts_only_reserved_timeout_retries() -> None:
    calls = [
        {
            "endpoint": "/v1/chat/completions",
            "attempts": 2,
            "status": 429,
            "provider_errors": ["provider_timeout", "provider_timeout"],
            "error_code": "budget_exhausted",
        },
        {"endpoint": "/v1/embeddings", "route": "ollama", "attempts": 2, "status": 200},
    ]
    split = launch.call_split(calls)
    assert split["timeout_retry_attempts"] == 1
    assert split["local_embedding"]["attempts"] == 2
    assert split["counted_toward_call_cap"] == 4


def test_reasoning_limit_unconfirmed_default_is_unset() -> None:
    args = launch.parser().parse_args(
        [
            "run",
            "--data-dir",
            "/data",
            "--run-dir",
            "/run",
            "--gateway-data-dir",
            "/gateway",
            "--trial-ledger",
            "/ledger",
            "--run-id",
            "id",
        ]
    )
    assert args.coding_reasoning_tokens is None
    assert gateway.Settings(data_dir=Path("/data"), run_id="id").coding_reasoning_tokens is None


def test_gateway_counts_timeout_retry_only_after_reservation() -> None:
    with tempfile.TemporaryDirectory(dir="/tmp") as directory:
        settings = gateway.Settings(
            data_dir=Path(directory),
            run_id="id",
            chat_route="fake",
            embedding_route="fake",
            provider_retries=2,
            run_max_calls=2,
        )
        backend = Mock()
        backend.complete.side_effect = gateway.GatewayError(504, "provider_timeout", "timed out")
        model = gateway.Gateway(settings, chat_backend=backend)
        with pytest.raises(gateway.GatewayError, match="budget exhausted"):
            model.chat({"model": "alpha-chat", "messages": [{"role": "user", "content": "x"}]})
        row = json.loads(model.log_path.read_text())
        assert row["timeout_retry_attempts"] == 1 and row["attempts"] == 2


def test_completed_rounds_add_to_inherited_count(tmp_path: Path) -> None:
    root = tmp_path / "memory"
    old = tmp_path / "old"
    old_session = old / "work/log/__session__/0"
    old_session.mkdir(parents=True)
    (old_session / "4_record").touch()
    plan = memory.prepare(
        root, run_id="old", run_dir=old, source_sha256="pin", judge_sha256="judge"
    )
    memory.record(plan, run_id="old", run_dir=old, started_at="start", ended_at="end", secrets=())
    new = tmp_path / "new"
    own = new / "work/log/__session__/0"
    own.mkdir(parents=True)
    (own / "4_record").touch()
    plan = memory.prepare(
        root, run_id="new", run_dir=new, source_sha256="pin", judge_sha256="judge"
    )
    result = memory.record(
        plan, run_id="new", run_dir=new, started_at="start", ended_at="end", secrets=()
    )
    assert result["loops_before"] == 1 and result["loops_after"] == 2


@pytest.mark.parametrize(
    "feedback,expected",
    [
        (
            SimpleNamespace(
                execution_feedback="ValueError: bad input\ntrace", final_decision=False
            ),
            "exception",
        ),
        (
            SimpleNamespace(execution_feedback="call cap reached", final_decision=False),
            "cap_reached",
        ),
    ],
)
def test_runner_keeps_execution_reason_before_critic(feedback: Any, expected: str) -> None:
    from tests.unit.test_rdagent_factor_judge import judge_parts

    class Feedback:
        execution_feedback = feedback.execution_feedback

        def __bool__(self) -> bool:
            return False

    cls = judge_parts("AlphaFactorRunner")["AlphaFactorRunner"]
    values, reason, detail = cls.execute_factor(Mock(), Feedback())
    assert values is None and reason == expected
    assert "\n" not in detail


def test_runner_records_exception_and_bad_shape() -> None:
    import pandas as pd
    from tests.unit.test_rdagent_factor_judge import judge_parts

    cls = judge_parts("AlphaFactorRunner")["AlphaFactorRunner"]
    workspace = Mock()
    workspace.execute.side_effect = ValueError("broken first line\nsecond line")
    assert cls.execute_factor(workspace, True) == (
        None,
        "exception",
        "ValueError: broken first line",
    )
    workspace.execute.side_effect = None
    workspace.execute.return_value = ("ran", pd.DataFrame({"a": [1], "b": [2]}))
    assert cls.execute_factor(workspace, True)[1] == "bad_output"
    assert cls.execute_factor(workspace, False)[1] == "critic_rejected"


def test_invalid_embedding_model_is_not_an_input_refusal() -> None:
    # Only validation/error translation is exercised: no budget, storage, socket or backend.
    model = Mock()
    model.record.return_value = {"refused": []}
    model.check_model.side_effect = gateway.GatewayError(
        400, "model_not_served", "wrong model", "model"
    )
    with pytest.raises(gateway.GatewayError) as caught:
        gateway.Gateway.embeddings(model, {"model": "wrong"})
    assert caught.value.code == "model_not_served"
    model.budget.reserve.assert_not_called()


def test_bad_factor_format_is_recorded_before_prefix_check() -> None:
    import pandas as pd
    from tests.unit.test_rdagent_factor_judge import judge_parts

    frame = pd.DataFrame(
        {"factor": ["not numeric"]}, index=pd.MultiIndex.from_tuples([("bad date", "A")])
    )
    workspace = Mock()
    workspace.execute.return_value = ("ran", frame)
    runner = judge_parts("AlphaFactorRunner")["AlphaFactorRunner"]
    assert runner.execute_factor(workspace, True)[1] == "bad_output"
