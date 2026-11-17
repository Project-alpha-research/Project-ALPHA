"""Paid embeddings, with a deterministic transport and no sockets or credentials on disk."""

from __future__ import annotations

import json
import secrets
from pathlib import Path
from typing import Any

import pytest

from tests.unit.test_rdagent_embedding_cap import chat, embed, model, rows
from tests.unit.test_rdagent_factor_launch import launch
from workers.rdagent import model_gateway as gw

__all__ = ["model"]


def provider(model: gw.Gateway, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ALPHA_GATEWAY_API_BASE", "https://provider.invalid/v1")
    monkeypatch.setenv("ALPHA_GATEWAY_API_KEY", secrets.token_urlsafe())
    model.settings.embedding_route = "provider"
    model.settings.provider_embed_model = "model-a"
    model.settings.provider_embed_usd_per_mtok = 3.0
    model.embedding_backend = gw.ProviderEmbeddings(model.settings)


def test_whole_inputs_reserve_then_settle(
    model: gw.Gateway, monkeypatch: pytest.MonkeyPatch
) -> None:
    provider(model, monkeypatch)
    text = "abc" * 4000

    def post(url: str, body: dict[str, Any], key: str, **kwargs: Any) -> dict[str, Any]:
        assert url == "https://provider.invalid/v1/embeddings"
        assert body == {"model": "model-a", "input": [text]}
        assert model.budget.status()["runs"]["test"]["usd"] == pytest.approx(0.012)
        return {"data": [{"index": 0, "embedding": [1.0, 2.0]}], "usage": {"total_tokens": 12}}

    monkeypatch.setattr(gw, "post_json", post)
    result = model.embeddings({"model": "alpha-embed", "input": text})
    assert result["model"] == "model-a"
    state = model.budget.status()["runs"]["test"]
    assert state["calls"] == state["local_embedding_calls"] == 0
    assert state["provider_embedding_calls"] == 1
    assert state["provider_embedding_tokens"] == 12
    assert state["usd"] == state["provider_embedding_usd"] == pytest.approx(0.000036)
    split = launch.call_split(rows(model))
    assert split["provider_embedding_calls"] == 1 and split["counted_calls"] == 0
    assert split["embedding_route"] == "provider" and split["embedding_model"] == "model-a"
    assert split["provider_embedding_tokens"] == 12
    assert split["provider_embedding_usd"] == pytest.approx(0.000036)


@pytest.mark.parametrize(
    "failure,usage,expected", [(False, None, 5e-6), (True, None, 0), (True, 7, 21e-6)]
)
def test_settlement_on_success_and_error(
    model: gw.Gateway,
    monkeypatch: pytest.MonkeyPatch,
    failure: bool,
    usage: int | None,
    expected: float,
) -> None:
    provider(model, monkeypatch)

    def post(*args: Any, **kwargs: Any) -> dict[str, Any]:
        if failure:
            raise gw.GatewayError(
                400, "input_too_long", "input too long", payload={"usage": {"total_tokens": usage}}
            )
        return {"data": [{"index": 0, "embedding": [1.0]}]}

    monkeypatch.setattr(gw, "post_json", post)
    if failure:
        with pytest.raises(gw.GatewayError):
            embed(model)
    else:
        embed(model)
    state = model.budget.status()["runs"]["test"]
    assert state["usd"] == state["provider_embedding_usd"] == pytest.approx(expected)
    assert state["provider_embedding_calls"] == 1


def test_provider_does_not_spend_chat_calls(
    model: gw.Gateway, monkeypatch: pytest.MonkeyPatch
) -> None:
    provider(model, monkeypatch)
    monkeypatch.setattr(
        gw, "post_json", lambda *a, **kw: {"data": [{"index": 0, "embedding": [1.0]}]}
    )
    for _ in range(60):
        model.chat(chat())
        embed(model)
    with pytest.raises(gw.GatewayError, match="run_max_calls"):
        model.chat(chat())
    embed(model)
    assert model.budget.status()["runs"]["test"]["provider_embedding_calls"] == 61


@pytest.mark.parametrize("cap", ["run_max_usd", "month_max_usd"])
def test_money_caps_refuse_before_transport(
    model: gw.Gateway, monkeypatch: pytest.MonkeyPatch, cap: str
) -> None:
    provider(model, monkeypatch)
    setattr(model.settings, cap, 1e-6)

    def post(*args: Any, **kwargs: Any) -> dict[str, Any]:
        pytest.fail("transport called after cap")

    monkeypatch.setattr(gw, "post_json", post)
    with pytest.raises(gw.GatewayError, match=cap):
        embed(model)
    assert model.budget.status()["runs"] == {}


def test_shared_embedding_guard(model: gw.Gateway, monkeypatch: pytest.MonkeyPatch) -> None:
    provider(model, monkeypatch)
    model.budget.write(
        {
            "schema_version": 1,
            "runs": {"test": {"calls": 0, "usd": 0, "local_embedding_calls": 2000}},
            "months": {},
        }
    )
    with pytest.raises(gw.GatewayError, match="budget exhausted.*EMBEDDING_CALLS_PER_RUN") as error:
        embed(model)
    assert error.value.code == "budget_exhausted"


def test_no_split_and_no_secret_in_errors(
    model: gw.Gateway, monkeypatch: pytest.MonkeyPatch
) -> None:
    provider(model, monkeypatch)
    import os

    key = os.environ["ALPHA_GATEWAY_API_KEY"]

    def post(*args: Any, **kwargs: Any) -> dict[str, Any]:
        raise gw.GatewayError(400, "input_too_long", key, payload={"error": {"message": key}})

    monkeypatch.setattr(gw, "post_json", post)
    with pytest.raises(gw.GatewayError) as error:
        model.embeddings({"model": "alpha-embed", "input": "long " * 3000})
    assert key not in str(error.value) + json.dumps(error.value.body()) + model.log_path.read_text()
    assert rows(model)[-1]["attempts"] == 1 and rows(model)[-1]["chunks"] == 0


def test_default_is_local() -> None:
    assert gw.Settings(Path("/tmp"), "test").embedding_route == "local"


@pytest.mark.parametrize("missing", ["provider_embed_model", "provider_embed_usd_per_mtok"])
def test_missing_provider_configuration_refuses(missing: str) -> None:
    from workers.rdagent.gateway_embeddings import validate_settings

    settings = gw.Settings(
        Path("/tmp"),
        "test",
        embedding_route="provider",
        provider_embed_model="model-a",
        provider_embed_usd_per_mtok=3,
    )
    setattr(settings, missing, None)
    with pytest.raises(ValueError, match=missing):
        validate_settings(settings)


def test_memory_reembeds_models_and_skips_failures(tmp_path: Path) -> None:
    from types import SimpleNamespace

    from workers.rdagent.research_memory import EmbeddingMemory

    sidecar = tmp_path / "embeddings.json"
    events = tmp_path / "reembedded.jsonl"
    graph = SimpleNamespace(
        nodes={
            "a": SimpleNamespace(content="a", embedding=[9.0]),
            "b": SimpleNamespace(content="b", embedding=[9.0]),
        }
    )
    calls: list[str] = []

    def first(text: str) -> tuple[str, list[float]]:
        calls.append(text)
        return "A", [1.0, 0.0]

    cache = EmbeddingMemory(sidecar, events, "A", first)
    assert cache.prepare(graph, lambda node, error: None) == {}
    assert calls == ["a", "b"]
    assert json.loads(sidecar.read_text())["entries"]["a"]["dimension"] == 2

    def second(text: str) -> tuple[str, list[float]]:
        calls.append(text)
        if text == "b":
            raise RuntimeError("embedding_input_refused: too long")
        return "B", [0.0, 0.0, 1.0]

    skipped: list[str] = []
    cache = EmbeddingMemory(sidecar, events, "B", second)
    removed = cache.prepare(graph, lambda node, error: skipped.append(str(error)))
    assert set(removed) == {"b"} and set(graph.nodes) == {"a"}
    assert graph.nodes["a"].embedding == [0.0, 0.0, 1.0]
    assert skipped == ["embedding_input_refused: too long"]
    assert len(events.read_text().splitlines()) == 3
    cache.prepare(graph, lambda node, error: None)
    assert calls == ["a", "b", "a", "b"]
    # A restart loads the sidecar, but only vectors from B are reusable under B.
    graph.nodes["a"].embedding = [9.0]
    restarted = EmbeddingMemory(sidecar, events, "B", second)
    restarted.prepare(graph, lambda node, error: None)
    assert graph.nodes["a"].embedding == [0.0, 0.0, 1.0] and len(calls) == 4


def test_memory_budget_failure_stops_without_skip(tmp_path: Path) -> None:
    from types import SimpleNamespace

    from tests.unit.test_rdagent_loop_fixups_2 import coder_parts
    from workers.rdagent.research_memory import EmbeddingMemory

    ns = coder_parts()

    def embed_text(text: str) -> tuple[str, list[float]]:
        raise gw.GatewayError(429, "budget_exhausted", "budget exhausted")

    def skip(node: Any, error: Exception) -> None:
        ns["embedding_failure"](error)
        pytest.fail("budget failure must stop")

    graph = SimpleNamespace(nodes={"a": SimpleNamespace(content="a", embedding=[9.0])})
    cache = EmbeddingMemory(tmp_path / "sidecar.json", tmp_path / "events.jsonl", "B", embed_text)
    with pytest.raises(ns["BudgetExhausted"]):
        cache.prepare(graph, skip)


def test_harness_can_request_split_counts_without_changing_default_reply(
    model: gw.Gateway, monkeypatch: pytest.MonkeyPatch
) -> None:
    attempts = 0

    def post(url: str, body: dict[str, Any], *args: Any, **kwargs: Any) -> dict[str, Any]:
        nonlocal attempts
        attempts += 1
        if attempts % 2:
            raise gw.GatewayError(400, "input_too_long", "too long")
        return {"embeddings": [[1.0] for _ in body["input"]]}

    monkeypatch.setattr(gw, "post_json", post)
    request = {"model": "alpha-embed", "input": "word. " * 600}
    assert "chunked_inputs" not in model.embeddings(request)
    assert model.embeddings({**request, "report_embedding_stats": True})["chunked_inputs"] == 0
    assert attempts == 2  # cached vectors do not repeat chunking or a provider request


def test_launcher_provider_options_and_receipt(
    model: gw.Gateway, monkeypatch: pytest.MonkeyPatch
) -> None:
    import argparse

    provider(model, monkeypatch)
    monkeypatch.setattr(
        gw,
        "post_json",
        lambda *a, **kw: {"data": [{"index": 0, "embedding": [1.0]}], "usage": {"total_tokens": 2}},
    )
    embed(model)
    directory = model.settings.data_dir
    args = argparse.Namespace(
        run_dir=directory / "run",
        gateway_data_dir=directory,
        run_id="test",
        loop_n=1,
        run_max_calls=60,
        embedding_route="provider",
        provider_embed_model="model-a",
        provider_embed_usd_per_mtok=3,
    )
    instance = launch.Launch(
        args,
        {
            "ALPHA_RDAGENT_SOURCE": directory,
            "ALPHA_FACTOR_PYTHON": directory / "runtime/venv/bin/python",
        },
    )
    instance.run.mkdir()
    (instance.run / "memory-reembedded.jsonl").write_text("{}\n{}\n")
    monkeypatch.setattr(
        instance, "gateway_status", lambda: {"this_run": model.budget.status()["runs"]["test"]}
    )
    monkeypatch.setattr(instance, "write_call_labels", lambda: {})
    instance.finish(0, "done")
    receipt = json.loads((instance.run / "receipt.json").read_text())
    assert receipt["provider_embedding_calls"] == 1
    assert receipt["provider_embedding_tokens"] == 2
    assert receipt["provider_embedding_usd"] == pytest.approx(6e-6)
    assert receipt["embedding_route"] == "provider" and receipt["embedding_model"] == "model-a"
    assert receipt["memory_entries_reembedded"] == 2
    assert "money caps" in receipt["call_cap_note"]
    parsed = launch.parser().parse_args(
        [
            "run",
            "--data-dir",
            "/tmp/data",
            "--run-dir",
            "/tmp/run",
            "--gateway-data-dir",
            "/tmp/gateway",
            "--trial-ledger",
            "/tmp/ledger",
            "--run-id",
            "test",
            "--embedding-route",
            "provider",
            "--provider-embed-model",
            "model-a",
            "--provider-embed-usd-per-mtok",
            "3",
        ]
    )
    assert parsed.embedding_route == "provider" and parsed.provider_embed_usd_per_mtok == 3


@pytest.mark.parametrize(
    "cause", ["provider_unavailable", "provider_timeout", "invalid_provider_response"]
)
def test_transport_failures_settle_conservatively(
    model: gw.Gateway, monkeypatch: pytest.MonkeyPatch, cause: str
) -> None:
    provider(model, monkeypatch)

    def post(*args: Any, **kwargs: Any) -> dict[str, Any]:
        raise gw.GatewayError(502, cause, cause)

    monkeypatch.setattr(gw, "post_json", post)
    with pytest.raises(gw.GatewayError):
        embed(model)
    expected = 0 if cause == "provider_unavailable" else 5e-6
    assert model.budget.status()["runs"]["test"]["usd"] == pytest.approx(expected)


def test_no_request_sent_settles_zero(model: gw.Gateway, monkeypatch: pytest.MonkeyPatch) -> None:
    provider(model, monkeypatch)

    def post(*args: Any, **kwargs: Any) -> dict[str, Any]:
        raise ValueError("request could not be constructed")

    monkeypatch.setattr(gw, "post_json", post)
    with pytest.raises(gw.GatewayError, match="request could not be sent"):
        embed(model)
    assert model.budget.status()["runs"]["test"]["usd"] == 0


def test_wrong_provider_model_is_not_used_but_is_paid(
    model: gw.Gateway, monkeypatch: pytest.MonkeyPatch
) -> None:
    provider(model, monkeypatch)

    def post(*args: Any, **kwargs: Any) -> dict[str, Any]:
        return {
            "model": "another-model",
            "data": [{"index": 0, "embedding": [1.0]}],
            "usage": {"total_tokens": 4},
        }

    monkeypatch.setattr(gw, "post_json", post)
    with pytest.raises(gw.GatewayError, match="invalid embeddings"):
        embed(model)
    assert model.budget.status()["runs"]["test"]["usd"] == pytest.approx(12e-6)


@pytest.mark.parametrize(
    "field", ["provider_embedding", "provider_embedding_calls", "embedding_route"]
)
def test_provider_bucket_cannot_be_claimed_by_caller(
    model: gw.Gateway, monkeypatch: pytest.MonkeyPatch, field: str
) -> None:
    provider(model, monkeypatch)
    with pytest.raises(gw.GatewayError) as error:
        embed(model, **{field: True})
    assert error.value.code == "unsupported_parameter"
    model.settings.chat_route = "api"
    model.settings.api_price_in_per_mtok = model.settings.api_price_out_per_mtok = 1
    model.chat({**chat(), **{field: True}})
    state = model.budget.status()["runs"]["test"]
    assert state["calls"] == 1 and state["provider_embedding_calls"] == 0


def test_local_default_preserves_wire_bytes(
    model: gw.Gateway, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured: list[bytes] = []

    def post(url: str, body: dict[str, Any]) -> dict[str, Any]:
        assert url == "http://127.0.0.1:11434/api/embed"
        captured.append(json.dumps(body).encode())
        return {"embeddings": [[1.0, 2.0]], "prompt_eval_count": 4}

    monkeypatch.setattr(gw, "post_json", post)
    response = model.embeddings({"model": "alpha-embed", "input": "  exact\ntext  "})
    assert captured == [
        json.dumps({"model": "nomic-embed-text", "input": ["  exact\ntext  "]}).encode()
    ]
    expected = {
        "object": "list",
        "data": [{"object": "embedding", "index": 0, "embedding": [1.0, 2.0]}],
        "model": "nomic-embed-text",
        "usage": {"prompt_tokens": 4, "total_tokens": 4},
    }
    assert json.dumps(response).encode() == json.dumps(expected).encode()


def test_coder_uses_current_vectors_for_queries_and_new_nodes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import ast
    import sys
    from collections.abc import Iterator
    from contextlib import contextmanager
    from types import ModuleType, SimpleNamespace

    from tests.unit.test_rdagent_loop_fixups_2 import coder_parts
    from workers.rdagent.research_memory import EmbeddingMemory

    class Backend:
        def _create_embedding_with_cache(self, input_content_list: list[str]) -> list[list[float]]:
            pytest.fail("upstream's old-model cache was used")

    class BackendModule(ModuleType):
        APIBackend: type[Backend] = Backend

    backend_module = BackendModule("rdagent.oai.backend.base")
    monkeypatch.setitem(sys.modules, "rdagent.oai.backend.base", backend_module)
    source = Path(gw.__file__).with_name("alpha_factor_coder.py")
    selected: list[ast.stmt] = [
        n
        for n in ast.parse(source.read_text()).body
        if isinstance(n, ast.FunctionDef) and n.name == "compatible_embeddings"
    ]
    namespace = {
        **coder_parts(),
        "EmbeddingMemory": EmbeddingMemory,
        "contextmanager": contextmanager,
        "Iterator": Iterator,
    }
    exec(compile(ast.Module(body=selected, type_ignores=[]), str(source), "exec"), namespace)
    calls: list[str] = []

    def current(text: str) -> tuple[str, list[float]]:
        calls.append(text)
        return "B", [0.0, 1.0]

    cache = EmbeddingMemory(tmp_path / "sidecar.json", tmp_path / "events.jsonl", "B", current)
    graph = SimpleNamespace(nodes={"old": SimpleNamespace(content="old", embedding=[1.0])})
    rag = SimpleNamespace(knowledgebase=SimpleNamespace(graph=graph), dump_knowledge_base_path=None)
    original = Backend._create_embedding_with_cache
    with namespace["compatible_embeddings"](rag, cache, tmp_path):
        assert graph.nodes["old"].embedding == [0.0, 1.0]
        assert Backend()._create_embedding_with_cache(["query"]) == [[0.0, 1.0]]
        graph.nodes["new"] = SimpleNamespace(
            content="new", embedding=Backend()._create_embedding_with_cache(["new"])[0]
        )
    assert Backend._create_embedding_with_cache is original
    assert calls == ["old", "query", "new"]
    saved = json.loads((tmp_path / "sidecar.json").read_text())
    assert all(
        value["model"] == "B" and value["dimension"] == 2 for value in saved["entries"].values()
    )


def test_invalid_provider_model_configuration_is_not_input_skip(
    model: gw.Gateway, monkeypatch: pytest.MonkeyPatch
) -> None:
    provider(model, monkeypatch)

    def post(*args: Any, **kwargs: Any) -> dict[str, Any]:
        raise gw.GatewayError(400, "model_not_found", "configured model does not exist")

    monkeypatch.setattr(gw, "post_json", post)
    with pytest.raises(gw.GatewayError) as error:
        embed(model)
    assert error.value.code == "model_not_found"


def test_explicit_provider_error_without_usage_refunds_even_timeout_code(
    model: gw.Gateway, monkeypatch: pytest.MonkeyPatch
) -> None:
    provider(model, monkeypatch)

    def post(*args: Any, **kwargs: Any) -> dict[str, Any]:
        raise gw.GatewayError(
            503,
            "provider_timeout",
            "provider rejected request",
            payload={"error": {"code": "provider_timeout"}},
        )

    monkeypatch.setattr(gw, "post_json", post)
    with pytest.raises(gw.GatewayError):
        embed(model)
    assert model.budget.status()["runs"]["test"]["usd"] == 0


def test_local_default_budget_file_keeps_main_fields(model: gw.Gateway) -> None:
    embed(model)
    state = json.loads(model.budget.path.read_text())
    expected = {"calls": 0, "usd": 0.0, "local_embedding_calls": 1}
    assert state["runs"] == {"test": expected}
    assert list(state["months"].values()) == [expected]


@pytest.mark.parametrize(
    "requested,reported",
    [("qwen/qwen3-embedding-8b", "Qwen/Qwen3-Embedding-8B"), ("vendor/code-4", "code-4")],
)
def test_provider_spelling_of_the_same_model_is_accepted(
    model: gw.Gateway, monkeypatch: pytest.MonkeyPatch, requested: str, reported: str
) -> None:
    provider(model, monkeypatch)
    model.settings.provider_embed_model = requested

    def post(*args: Any, **kwargs: Any) -> dict[str, Any]:
        return {
            "model": reported,
            "data": [{"index": 0, "embedding": [1.0]}],
            "usage": {"total_tokens": 4},
        }

    monkeypatch.setattr(gw, "post_json", post)
    assert embed(model)["model"] == requested
