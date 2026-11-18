"""Budget refusals stop the loop and account for reserved retries."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import Mock

import pytest

from tests.unit._rdagent_support import _Backend, _upstream_graph, coder_parts, failed_call
from tests.unit._rdagent_support import unfinished_session as unfinished_session
from workers.rdagent import model_gateway as gateway


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


def test_budget_refusal_behind_upstream_retries_stops_at_once(tmp_path: Path) -> None:
    """The real 2026-11-17 shape: the RuntimeError carries no cause, yet the cap is seen."""
    ns = coder_parts()
    _Backend.failures = [gateway.GatewayError(429, "budget_exhausted", "budget exhausted: run")]
    _Backend.calls = 0
    unpatched = _Backend._create_embedding_with_cache
    graph = _upstream_graph()
    record = tmp_path / "memory-skips.jsonl"
    with (
        pytest.raises(ns["BudgetExhausted"], match="budget exhausted"),
        ns["tolerant_embeddings"](graph, record, _Backend),
    ):
        graph.add_node(SimpleNamespace(embedding=None))
    assert _Backend.calls == 1  # no upstream retry after a budget refusal
    assert not record.exists()
    assert _Backend._create_embedding_with_cache is unpatched  # nothing of ALPHA's stays


def test_gateway_counts_timeout_retry_only_after_reservation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Three tries allowed, two calls left: the timeout retry that was reserved counts once."""
    monkeypatch.setenv("ALPHA_GATEWAY_API_KEY", "sk-test-not-real")
    monkeypatch.setenv("ALPHA_GATEWAY_API_BASE", "https://example.com/api/v1")

    def timed_out(*args: Any) -> dict[str, Any]:
        raise gateway.GatewayError(504, "provider_timeout", "provider read timed out")

    monkeypatch.setattr(gateway, "_post_json", timed_out)
    # The gateway refuses a data dir inside any git checkout, so this test uses /tmp directly.
    with tempfile.TemporaryDirectory(prefix="gateway-unit-", dir="/tmp") as directory:
        settings = gateway.Settings(
            data_dir=Path(directory),
            run_id="id",
            chat_route="api",
            embedding_route="fake",
            api_model="deepseek/test-model",
            api_price_in_per_mtok=1,
            api_price_out_per_mtok=2,
            api_openrouter=True,
            provider_retries=2,
            run_max_calls=2,
        )
        model = gateway.Gateway(settings)
        with pytest.raises(gateway.GatewayError, match="budget exhausted"):
            model.chat({"model": "alpha-chat", "messages": [{"role": "user", "content": "x"}]})
        row = json.loads(model.log_path.read_text().splitlines()[-1])
        assert row["attempts"] == 2 and row["timeout_retry_attempts"] == 1
        assert row["provider_errors"] == ["provider_timeout", "provider_timeout"]


def test_budget_refusal_not_converted_to_failed_round(tmp_path: Path) -> None:
    from workers.rdagent.loop_guard import ProviderGuard

    calls = tmp_path / "calls.jsonl"

    def refused(exp: Any) -> Any:
        calls.write_text(
            json.dumps(
                {
                    "run_id": "test",
                    "endpoint": "/v1/chat/completions",
                    "error_code": "budget_exhausted",
                }
            )
            + "\n"
        )
        raise RuntimeError("Failed to create chat completion after 1 retries.")

    guard = ProviderGuard(
        SimpleNamespace(develop=refused),
        SimpleNamespace(loop_idx=0),
        "coding",
        tmp_path,
        calls,
        "test",
        ValueError,
        SimpleNamespace,
    )
    with pytest.raises(SystemExit, match="budget"):
        guard.develop(None)
    assert not (tmp_path / "rounds.jsonl").exists()


def test_budget_finish_closes_round_at_cap_before_receipt_exists(
    tmp_path: Path, unfinished_session: Path
) -> None:
    from workers.rdagent.research_memory import close_unfinished_rounds

    close_unfinished_rounds(unfinished_session, exit_reason="budget exhausted")
    assert json.loads((tmp_path / "rounds.jsonl").read_text())["status"] == "abandoned_at_cap"


def test_critic_budget_refusal_still_ends_run(tmp_path: Path) -> None:
    from workers.rdagent.loop_guard import CriticEvaluator, ProviderGuard

    calls = tmp_path / "calls.jsonl"
    evaluator = SimpleNamespace(
        code_evaluator=SimpleNamespace(evaluate=lambda: failed_call(calls, "budget_exhausted")),
        value_evaluator=SimpleNamespace(evaluate=Mock()),
        final_decision_evaluator=SimpleNamespace(evaluate=Mock()),
    )
    evaluator.evaluate = lambda *args: evaluator.code_evaluator.evaluate()
    guard = ProviderGuard(
        None, SimpleNamespace(loop_idx=0), "coding", tmp_path, calls, "test", ValueError, None
    )
    wrapped = CriticEvaluator(evaluator, guard)
    with pytest.raises(SystemExit, match="budget exhausted"):
        wrapped.evaluate(SimpleNamespace(factor_name="factor"), None)
    wrapped.record()
    assert not (tmp_path / "rounds.jsonl").exists()
