"""Socket-free accounting contracts for local embeddings (owner decision 2026-11-17)."""

from __future__ import annotations

import argparse
import json
import tempfile
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from itertools import count
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import Mock

import pytest

from tests.unit._rdagent_support import coder_parts
from tests.unit.test_rdagent_factor_launch import launch
from workers.rdagent import model_gateway as gw


@pytest.fixture
def model(monkeypatch: pytest.MonkeyPatch) -> Iterator[gw.Gateway]:
    def local_post(*args: Any, **kwargs: Any) -> dict[str, Any]:
        return {"embeddings": [[1.0]], "prompt_eval_count": 1}

    # This sandbox marks /tmp as a git tree too. Directory policy has its own tests;
    # this fixture isolates accounting and never opens a socket or a real provider.
    def storage_only(settings: gw.Settings) -> None:
        settings.state_dir.mkdir(exist_ok=True)

    monkeypatch.setattr(gw.Settings, "validate", storage_only)
    monkeypatch.setattr(gw, "post_json", local_post)
    with tempfile.TemporaryDirectory(prefix="embedding-cap-", dir="/tmp") as directory:
        yield gw.Gateway(gw.Settings(data_dir=Path(directory), run_id="test", chat_route="fake"))


def chat() -> dict[str, Any]:
    return {
        "model": "alpha-chat",
        "messages": [{"role": "system", "content": "system"}, {"role": "user", "content": "hello"}],
    }


_INPUT_IDS = count()


def embed(model: gw.Gateway, **extra: Any) -> dict[str, Any]:
    return model.embeddings({"model": "alpha-embed", "input": f"{next(_INPUT_IDS):05d}", **extra})


def rows(model: gw.Gateway) -> list[dict[str, Any]]:
    return [json.loads(line) for line in model.log_path.read_text().splitlines()]


def test_sixty_paid_calls_plus_local_embeddings(model: gw.Gateway) -> None:
    class PaidChat:
        def complete(self, *args: Any) -> gw.ChatResult:
            return gw.ChatResult("ok", "paid", usd=0.01)

    model.chat_backend = PaidChat()
    for _ in range(60):
        model.chat(chat())
        for _ in range(3):
            embed(model)
    with pytest.raises(gw.GatewayError, match="run_max_calls") as error:
        model.chat(chat())
    assert error.value.code == "budget_exhausted"
    embed(model)  # paid allowance exhaustion does not spend the local allowance
    status = model.budget.status()
    for entry in (status["runs"]["test"], status["months"][gw.month()]):
        assert entry["calls"] == entry["counted_calls"] == 60
        assert entry["local_embedding_calls"] == 181
        assert entry["usd"] == pytest.approx(0.6)
    split = launch.call_split(rows(model))
    assert split["counted_calls"] == split["counted_toward_call_cap"] == 60
    assert split["local_embedding_calls"] == 181


def test_paid_embedding_backend_counts_despite_local_route_and_alias(model: gw.Gateway) -> None:
    class PaidEmbedding:
        def embed(self, inputs: list[str]) -> gw.EmbeddingResult:
            return gw.EmbeddingResult([[1.0]], "nomic-embed-text")

    model.embedding_backend = PaidEmbedding()
    for _ in range(60):
        embed(model)
    with pytest.raises(gw.GatewayError, match="run_max_calls"):
        embed(model)
    state = model.budget.status()["runs"]["test"]
    assert state["counted_calls"] == 60 and state["local_embedding_calls"] == 0
    assert state["usd"] == 0  # embeddings carry no dollars, as before
    split = launch.call_split(rows(model))
    assert split["provider_embedding"]["attempts"] == 60
    assert split["counted_calls"] == 60 and split["local_embedding_calls"] == 0


@pytest.mark.parametrize("field", ["local_embedding", "local_embedding_calls", "counted_calls"])
def test_caller_cannot_claim_local_exemption(model: gw.Gateway, field: str) -> None:
    with pytest.raises(gw.GatewayError) as error:
        embed(model, **{field: True})
    assert error.value.code == "unsupported_parameter"
    with pytest.raises(gw.GatewayError):
        model.chat({**chat(), **{field: True}})
    assert model.budget.status()["runs"] == {}


def test_local_guard_allows_2000_then_refuses_and_survives_restart(model: gw.Gateway) -> None:
    assert gw.EMBEDDING_CALLS_PER_RUN == 2000
    for _ in range(2000):
        embed(model)
    restarted = gw.Gateway(model.settings)
    with pytest.raises(gw.GatewayError, match="EMBEDDING_CALLS_PER_RUN.*2000") as error:
        embed(restarted)
    assert error.value.code == "budget_exhausted" and error.value.status == 429
    assert rows(model)[-1]["attempts"] == 0
    assert restarted.budget.status()["runs"]["test"]["local_embedding_calls"] == 2000
    assert "2000" in launch.exit_reason(
        1,
        {"this_run": restarted.budget.status()["runs"]["test"]},
        argparse.Namespace(run_max_calls=60),
    )
    model.chat(chat())


def test_local_guard_is_atomic(model: gw.Gateway) -> None:
    def attempt(_: int) -> bool:
        try:
            embed(model)
            return True
        except gw.GatewayError as error:
            assert error.code == "budget_exhausted"
            return False

    model.budget.write(
        {
            "schema_version": 1,
            "runs": {"test": {"calls": 0, "usd": 0, "local_embedding_calls": 1998}},
            "months": {},
        }
    )
    with ThreadPoolExecutor(max_workers=8) as pool:
        assert sum(pool.map(attempt, range(8))) == 2


def test_local_chunk_retry_uses_local_guard(
    model: gw.Gateway, monkeypatch: pytest.MonkeyPatch
) -> None:
    def refuse(*args: Any, **kwargs: Any) -> dict[str, Any]:
        raise gw.GatewayError(400, "input_too_long", "input too long")

    monkeypatch.setattr(gw, "post_json", refuse)
    model.budget.write(
        {
            "schema_version": 1,
            "runs": {"test": {"calls": 0, "usd": 0, "local_embedding_calls": 1999}},
            "months": {},
        }
    )
    with pytest.raises(gw.GatewayError, match="EMBEDDING_CALLS_PER_RUN"):
        model.embeddings({"model": "alpha-embed", "input": "word. " * 500})
    assert rows(model)[-1]["attempts"] == 1
    assert model.budget.status()["runs"]["test"]["calls"] == 0


@pytest.mark.parametrize("cap", ["run_max_usd", "month_max_usd", "month_max_calls"])
def test_money_and_monthly_caps_still_apply_to_counted_calls(model: gw.Gateway, cap: str) -> None:
    model.budget.reserve(10)
    if cap.startswith("month"):
        model.settings.run_id = "other"
        setattr(model.settings, cap, 10 if cap.endswith("usd") else 1)
    embed(model)
    with pytest.raises(gw.GatewayError, match=cap):
        model.budget.reserve(0.01)


def test_legacy_state_and_call_rows_keep_past_embeddings_counted(model: gw.Gateway) -> None:
    old = {
        "schema_version": 1,
        "runs": {"test": {"calls": 59, "usd": 1.0}},
        "months": {gw.month(): {"calls": 59, "usd": 1.0}},
    }
    model.budget.write(old)
    embed(model)
    model.chat(chat())
    assert model.budget.status()["runs"]["test"]["counted_calls"] == 60
    assert model.budget.status()["runs"]["test"]["local_embedding_calls"] == 1
    old_receipt = {
        "schema": "AlphaRdagentFactorRunReceiptV1",
        "gateway_status": {"this_run": {"calls": 60, "usd": 1.0}},
    }
    assert "60 of 60" in launch.exit_reason(
        1, old_receipt["gateway_status"], argparse.Namespace(run_max_calls=60)
    )
    old_calls = [{"endpoint": "/v1/embeddings", "route": "ollama", "attempts": 3, "status": 200}]
    split = launch.call_split(old_calls)
    assert split["counted_toward_call_cap"] == 3 and split["local_embedding_calls"] == 0
    assert split["local_embedding"]["attempts"] == 3


@pytest.mark.parametrize("bad", [-1, True, "1", 1.2])
def test_corrupt_local_counter_fails_closed(model: gw.Gateway, bad: Any) -> None:
    model.budget.write(
        {
            "schema_version": 1,
            "runs": {"test": {"calls": 0, "usd": 0, "local_embedding_calls": bad}},
            "months": {},
        }
    )
    with pytest.raises(gw.GatewayError) as error:
        embed(model)
    assert error.value.code == "budget_state_unreadable"


def test_receipt_uses_reserved_counts_even_without_call_logs(
    model: gw.Gateway, monkeypatch: pytest.MonkeyPatch
) -> None:
    model.chat(chat())
    embed(model)
    directory = model.settings.data_dir
    args = argparse.Namespace(
        run_dir=directory / "run",
        gateway_data_dir=directory,
        run_id="test",
        loop_n=1,
        run_max_calls=60,
    )
    job = launch.Launch(
        args, {"ALPHA_RDAGENT_SOURCE": directory, "ALPHA_FACTOR_PYTHON": directory / "a/b/c/python"}
    )
    job.run.mkdir()
    monkeypatch.setattr(
        job, "gateway_status", lambda: {"this_run": model.budget.status()["runs"]["test"]}
    )
    job.finish(0, "done")
    receipt = json.loads((job.run / "receipt.json").read_text())
    assert receipt["counted_calls"] == 1 and receipt["local_embedding_calls"] == 1
    assert receipt["call_cap_note"] == (
        "Local embeddings are free and are not counted toward the 60-call cap."
    )


def test_paid_chat_cannot_claim_exemption_through_api_fields(model: gw.Gateway) -> None:
    class PaidChat:
        def complete(self, *args: Any) -> gw.ChatResult:
            return gw.ChatResult("ok", "alpha-embed", usd=0.01)

    model.settings.chat_route = "api"
    model.settings.api_price_in_per_mtok = 1
    model.settings.api_price_out_per_mtok = 1
    model.chat_backend = PaidChat()
    model.chat({**chat(), "local_embedding": True, "counted_calls": 0})
    state = model.budget.status()["runs"]["test"]
    assert state["counted_calls"] == 1 and state["local_embedding_calls"] == 0
    assert state["usd"] == 0.01


def test_timeout_retry_stays_counted_after_local_embeddings(model: gw.Gateway) -> None:
    class TimeoutThenReply:
        calls = 0

        def complete(self, *args: Any) -> gw.ChatResult:
            self.calls += 1
            if self.calls == 1:
                raise gw.GatewayError(504, "provider_timeout", "deadline reached")
            return gw.ChatResult("ok", "paid", usd=0.01)

    for _ in range(59):
        model.budget.reserve(0)
    embed(model)
    model.chat_backend = TimeoutThenReply()
    with pytest.raises(gw.GatewayError, match="run_max_calls"):
        model.chat(chat())
    assert model.chat_backend.calls == 1
    assert model.budget.status()["runs"]["test"]["counted_calls"] == 60
    assert rows(model)[-1]["timeout_retry_attempts"] == 0


# Review fixes (2026-11-17): bare-text refusals, unchanged dollars, built-in backend only.


@pytest.mark.parametrize("cap", ["local_guard", "call_cap"])
def test_both_cap_refusals_stop_the_coder_even_as_bare_text(model: gw.Gateway, cap: str) -> None:
    """The client may keep only the message text; the coder must still see a budget refusal."""
    if cap == "local_guard":
        model.budget.write(
            {
                "schema_version": 1,
                "runs": {"test": {"calls": 0, "usd": 0, "local_embedding_calls": 2000}},
                "months": {},
            }
        )
    else:
        model.budget.write(
            {"schema_version": 1, "runs": {"test": {"calls": 60, "usd": 0}}, "months": {}}
        )
        model.embedding_backend = PaidLikeOllama(model.settings)
    with pytest.raises(gw.GatewayError) as refused:
        embed(model)
    ns = coder_parts()
    graph = SimpleNamespace(add_node=Mock(side_effect=RuntimeError(refused.value.message)))
    with tempfile.TemporaryDirectory() as directory:
        record = Path(directory) / "memory-skips.jsonl"
        with (
            pytest.raises(ns["BudgetExhausted"]),
            ns["tolerant_embeddings"](graph, record),
        ):
            graph.add_node(SimpleNamespace(embedding=None))
        assert not record.exists()


class PaidLikeOllama(gw.OllamaEmbeddings):
    """A subclass is not the gateway's built-in local backend, whatever it calls itself."""


def test_embedding_money_accounting_is_unchanged(
    model: gw.Gateway, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Embeddings never carried dollars, even when the backend fails; no new pricing rule."""

    def broken(*args: Any, **kwargs: Any) -> dict[str, Any]:
        raise gw.GatewayError(502, "invalid_provider_response", "no vectors")

    model.settings.api_price_in_per_mtok = 1000.0
    model.embedding_backend = PaidLikeOllama(model.settings)
    embed(model)
    monkeypatch.setattr(gw, "post_json", broken)
    with pytest.raises(gw.GatewayError, match="no vectors"):
        embed(model)
    state = model.budget.status()["runs"]["test"]
    assert state["counted_calls"] == 2 and state["local_embedding_calls"] == 0
    assert state["usd"] == 0
    assert [row["usd"] for row in rows(model)] == [0, 0]
    assert rows(model)[-1]["local_embedding"] is False


def test_ollama_backend_off_this_machine_is_not_exempt(model: gw.Gateway) -> None:
    model.settings.ollama_url = "https://embeddings.example.com"
    embed(model)
    state = model.budget.status()["runs"]["test"]
    assert state["counted_calls"] == 1 and state["local_embedding_calls"] == 0


def test_a_chat_row_is_never_split_as_local() -> None:
    forged = [{"endpoint": "/v1/chat/completions", "attempts": 2, "local_embedding": True}]
    split = launch.call_split(forged)
    assert split["counted_calls"] == split["counted_toward_call_cap"] == 2
    assert split["local_embedding_calls"] == 0


@pytest.fixture
def almost_capped_model(model: gw.Gateway, monkeypatch: pytest.MonkeyPatch) -> gw.Gateway:
    from tests.unit.test_rdagent_provider_embeddings import provider

    provider(model, monkeypatch)
    model.budget.write(
        {
            "schema_version": 1,
            "runs": {"test": {"calls": 0, "usd": 0, "local_embedding_calls": 1999}},
            "months": {},
        }
    )
    return model


def test_provider_batch_requests_stop_at_embedding_cap(
    almost_capped_model: gw.Gateway, monkeypatch: pytest.MonkeyPatch
) -> None:
    model = almost_capped_model
    sent = Mock(
        side_effect=lambda url, body, *a, **kw: {
            "model": "model-a",
            "data": [{"index": i, "embedding": [1.0]} for i in range(len(body["input"]))],
        }
    )
    monkeypatch.setattr(gw, "post_json", sent)
    with pytest.raises(gw.GatewayError, match="EMBEDDING_CALLS_PER_RUN"):
        model.embeddings({"model": "alpha-embed", "input": [str(i) for i in range(33)]})
    assert sent.call_count == 1


def test_local_route_call_rows_and_requests_are_unchanged(model: Any) -> None:
    result = model.embeddings({"model": "alpha-embed", "input": ["a"]})
    assert len(result["data"]) == 1 and len(rows(model)) == 1
    added = {"response_model", "reserved_usd", "input_count", "single_retry", "model_check"}
    assert not added & set(rows(model)[0])


def test_successful_batch_is_cached_even_when_later_batch_hits_cap(
    almost_capped_model: gw.Gateway, monkeypatch: pytest.MonkeyPatch
) -> None:
    model = almost_capped_model

    def post(url: str, body: dict[str, Any], *args: Any, **kwargs: Any) -> dict[str, Any]:
        return {
            "model": "model-a",
            "data": [{"index": i, "embedding": [float(t)]} for i, t in enumerate(body["input"])],
        }

    monkeypatch.setattr(gw, "post_json", post)
    with pytest.raises(gw.GatewayError, match="EMBEDDING_CALLS_PER_RUN"):
        model.embeddings({"model": "alpha-embed", "input": [str(i) for i in range(33)]})
    assert model.embeddings({"model": "alpha-embed", "input": "0"})["data"][0]["embedding"] == [0.0]
