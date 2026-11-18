"""Prompt-cache facts and router sessions, using a socket-free provider."""

from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from tests.unit.test_rdagent_embedding_cap import chat, model, rows
from tests.unit.test_rdagent_factor_launch import launch
from workers.rdagent import gateway_usage
from workers.rdagent import model_gateway as gw

__all__ = ["model"]


def api(model: gw.Gateway, monkeypatch: pytest.MonkeyPatch, *, router: bool = False) -> None:
    monkeypatch.setenv("ALPHA_GATEWAY_API_BASE", "https://provider.invalid/v1")
    monkeypatch.setenv("ALPHA_GATEWAY_API_KEY", "fake-test-credential")
    model.settings.chat_route = "api"
    model.settings.api_model = "test-model"
    model.settings.api_price_in_per_mtok = 2
    model.settings.api_price_out_per_mtok = 3
    model.settings.api_openrouter = router
    model.chat_backend = gw.ApiChat(model.settings)


def response(*, facts: bool = True) -> dict[str, Any]:
    result: dict[str, Any] = {
        "choices": [{"message": {"content": "ok"}}],
        "usage": {"prompt_tokens": 100, "completion_tokens": 20},
    }
    if facts:
        result.update(provider="upstream-a", id="gen-123")
        result["usage"].update(
            prompt_tokens_details={"cached_tokens": 60, "cache_write_tokens": 10},
            completion_tokens_details={"reasoning_tokens": 12},
            cache_discount=0.0001,
            cost=0.007,
        )
    return result


@pytest.mark.parametrize("facts", [True, False])
def test_response_facts_are_recorded_or_null(
    model: gw.Gateway, monkeypatch: pytest.MonkeyPatch, facts: bool
) -> None:
    api(model, monkeypatch)
    monkeypatch.setattr(gw, "post_json", lambda *a, **kw: response(facts=facts))
    model.chat(chat())
    row = rows(model)[0]
    expected = {
        "provider": "upstream-a",
        "id": "gen-123",
        "cached_tokens": 60,
        "cache_write_tokens": 10,
        "cache_discount": 0.0001,
        "reasoning_tokens": 12,
        "charged_usd": 0.007,
    }
    for field, value in expected.items():
        assert row[field] == (value if facts else None)
    assert row["usage_known"] is True
    assert row["attempt_usage"][0]["provider"] == row["provider"]
    # Non-OpenRouter settlement remains the list-price estimate despite usage.cost.
    assert row["usd"] == pytest.approx(0.00026)
    assert row["estimated_usd"] == pytest.approx(0.00026)


@pytest.mark.parametrize("disabled", [False, True])
def test_api_body_only_adds_run_session(
    model: gw.Gateway, monkeypatch: pytest.MonkeyPatch, disabled: bool
) -> None:
    api(model, monkeypatch, router=True)
    model.settings.no_router_session = disabled
    request = {**chat(), "temperature": 0.5, "stream_options": {"include_usage": True}}
    original = copy.deepcopy(request)
    bodies: list[dict[str, Any]] = []

    def post(url: str, body: dict[str, Any], *args: Any, **kwargs: Any) -> dict[str, Any]:
        bodies.append(copy.deepcopy(body))
        return response()

    monkeypatch.setattr(gw, "post_json", post)
    model.chat(request)
    expected = {
        "model": "test-model",
        "messages": request["messages"],
        "temperature": 0.5,
        "stream": False,
        "provider": {"require_parameters": True},
        "usage": {"include": True},
    }
    if not disabled:
        expected["session_id"] = model.settings.run_id
    assert bodies == [expected]
    assert json.dumps(bodies[0]["provider"]).encode() == b'{"require_parameters": true}'
    assert request == original
    assert rows(model)[0]["router_session_sent"] is (not disabled)


@pytest.mark.parametrize("route", ["fake", "codex"])
def test_other_routes_receive_no_session(model: gw.Gateway, route: str) -> None:
    class Backend:
        def complete(self, request: dict[str, Any], *args: Any) -> gw.ChatResult:
            assert "session_id" not in request
            return gw.ChatResult("ok", "fixture")

    model.settings.chat_route = route
    model.chat_backend = Backend()
    model.chat(chat())
    assert rows(model)[0]["router_session_sent"] is False


@pytest.mark.parametrize("router", [True, False])
def test_timeout_unknown_and_budget_unchanged(
    model: gw.Gateway, monkeypatch: pytest.MonkeyPatch, router: bool
) -> None:
    api(model, monkeypatch, router=router)
    attempts = 0

    def post(*args: Any, **kwargs: Any) -> dict[str, Any]:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise gw.GatewayError(504, "provider_timeout", "deadline")
        return response()

    monkeypatch.setattr(gw, "post_json", post)
    model.chat(chat())
    row = rows(model)[0]
    assert row["usage_known"] is False
    abandoned, success = row["attempt_usage"]
    assert abandoned["usage_known"] is False
    for field in ("provider", "id", "prompt_tokens", "cached_tokens", "charged_usd"):
        assert abandoned[field] is None
    assert success["usage_known"] is True
    reserve = ((len("hello") + len("system")) / 4 * 2 + 4096 * 3) / 1e6
    expected = reserve + (0.007 if router else 0.00026)
    state = model.budget.status()["runs"]["test"]
    assert state["calls"] == 2
    assert state["usd"] == pytest.approx(expected)
    assert row["usd"] == pytest.approx(expected)


def logged_calls() -> list[dict[str, Any]]:
    return [
        {
            "endpoint": "/v1/chat/completions",
            "attempts": 1,
            "status": 200,
            "prompt_tokens": p,
            "cached_tokens": c,
            "reasoning_tokens": r,
            "completion_tokens": o,
            "provider": provider,
            "router_session_sent": True,
        }
        for p, c, r, o, provider in [
            (100, 60, 12, 20, "a"),
            (300, 40, 8, 30, "b"),
            (100, 0, 0, 10, "a"),
        ]
    ]


def test_receipt_hand_computed_and_labels_optional() -> None:
    calls = logged_calls()
    original = copy.deepcopy(calls)
    split = launch.call_split(calls)
    usage = split["chat_usage"]
    assert usage["prompt_tokens"] == 500
    assert usage["cached_tokens"] == 100
    assert usage["cache_hit_rate"] == 0.2
    assert usage["reasoning_tokens"] == 20
    assert usage["completion_tokens"] == 60
    assert usage["provider_calls"] == {"a": 2, "b": 1}
    assert usage["distinct_providers"] == 2
    assert usage["router_session_sent"] is True
    assert usage["summary"] == (
        "20% of prompt tokens were served from cache; calls were served by 2 provider(s)."
    )
    assert "by_step" not in usage
    labelled = [
        {**call, "step": step}
        for call, step in zip(calls, ["coding", "coding", "propose"], strict=True)
    ]
    steps = launch.call_split(calls, labelled)["chat_usage"]["by_step"]
    assert steps["coding"]["cache_hit_rate"] == 0.25
    assert steps["coding"]["reasoning_tokens"] == 20
    assert steps["propose"]["cache_hit_rate"] == 0
    assert calls == original


def test_legacy_rows_and_receipts_remain_readable() -> None:
    old = {"endpoint": "/v1/chat/completions", "attempts": 2, "usd": 0.1, "status": 200}
    original = copy.deepcopy(old)
    split = launch.call_split([old])
    assert split["counted_calls"] == 2
    assert split["model_chat"]["usd"] == 0.1
    assert split["chat_usage"]["cache_hit_rate"] is None
    assert split["chat_usage"]["router_session_sent"] is None
    assert old == original
    receipt = {
        "schema": "AlphaRdagentFactorRunReceiptV1",
        "gateway_status": {"this_run": {"calls": 60}},
    }
    assert "60 of 60" in launch.exit_reason(
        1, receipt["gateway_status"], argparse.Namespace(run_max_calls=60)
    )


def test_receipt_without_steps_still_has_chat_usage(model: gw.Gateway) -> None:
    model.chat(chat())
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
    job.write_call_labels()
    assert job.receipt["call_split"]["model_chat"]["requests"] == 1
    assert "by_step" not in job.receipt["call_split"]["chat_usage"]


def test_launcher_flag_is_forwarded(model: gw.Gateway, monkeypatch: pytest.MonkeyPatch) -> None:
    directory = model.settings.data_dir
    args = launch.parser().parse_args(
        [
            "run",
            "--data-dir",
            str(directory),
            "--run-dir",
            str(directory / "run"),
            "--gateway-data-dir",
            str(directory),
            "--trial-ledger",
            str(directory / "ledger"),
            "--run-id",
            "test",
            "--chat-route",
            "api",
            "--no-router-session",
        ]
    )
    job = launch.Launch(
        args, {"ALPHA_RDAGENT_SOURCE": directory, "ALPHA_FACTOR_PYTHON": directory / "a/b/c/python"}
    )
    job.run.mkdir()

    class Child:
        pid = 123

        def poll(self) -> None:
            return None

    def spawn(command: list[str], *a: Any, **kw: Any) -> Child:
        assert "--no-router-session" in command
        (directory / "model-gateway/session-123.json").write_text(
            json.dumps({"pid": 123, "base_url": "http://unused", "token": "fixture"})
        )
        return Child()

    monkeypatch.setattr(job, "spawn", spawn)
    assert job.gateway() == ("http://unused", "fixture")
    parsed = gw.parser().parse_args(
        ["serve", "--data-dir", str(directory), "--run-id", "test", "--no-router-session"]
    )
    assert parsed.no_router_session is True


def test_json_retry_retains_each_provider_and_generation(
    model: gw.Gateway, monkeypatch: pytest.MonkeyPatch
) -> None:
    api(model, monkeypatch, router=True)
    replies = [response(), response()]
    replies[1].update(provider="upstream-b", id="gen-456")
    replies[1]["choices"][0]["message"]["content"] = "{}"
    monkeypatch.setattr(gw, "post_json", lambda *a, **kw: replies.pop(0))
    model.chat({**chat(), "response_format": {"type": "json_object"}})
    row = rows(model)[0]
    assert row["provider"] is None and row["id"] is None
    assert [(a["provider"], a["id"]) for a in row["attempt_usage"]] == [
        ("upstream-a", "gen-123"),
        ("upstream-b", "gen-456"),
    ]
    assert row["cached_tokens"] == 120 and row["charged_usd"] == 0.014
    summary = launch.call_split([row])["chat_usage"]
    assert summary["provider_calls"] == {"upstream-a": 1, "upstream-b": 1}
    assert summary["prompt_tokens"] == 200 and summary["cache_hit_rate"] == 0.6
    assert model.budget.status()["runs"]["test"]["usd"] == pytest.approx(0.014)


def test_abandoned_only_attempt_keeps_nulls(
    model: gw.Gateway, monkeypatch: pytest.MonkeyPatch
) -> None:
    api(model, monkeypatch)
    model.settings.provider_retries = 0

    def post(*args: Any, **kwargs: Any) -> dict[str, Any]:
        raise gw.GatewayError(504, "provider_timeout", "deadline")

    monkeypatch.setattr(gw, "post_json", post)
    with pytest.raises(gw.GatewayError, match="deadline"):
        model.chat(chat())
    row = rows(model)[0]
    assert row["usage_known"] is False
    assert row["router_session_sent"] is True
    for field in (
        "provider",
        "id",
        "cached_tokens",
        "cache_write_tokens",
        "cache_discount",
        "reasoning_tokens",
        "charged_usd",
    ):
        assert row[field] is None
    usage = launch.call_split([row])["chat_usage"]
    assert usage["cache_hit_rate"] is None
    assert usage["unknown_provider_calls"] == 1
    assert "1 call(s) have unknown providers" in usage["summary"]


@pytest.mark.parametrize("disabled", [False, True])
def test_caller_cannot_supply_private_session(
    model: gw.Gateway, monkeypatch: pytest.MonkeyPatch, disabled: bool
) -> None:
    api(model, monkeypatch)
    model.settings.no_router_session = disabled

    def post(url: str, body: dict[str, Any], *args: Any, **kw: Any) -> dict[str, Any]:
        assert body.get("session_id") == (None if disabled else "test")
        return response()

    monkeypatch.setattr(gw, "post_json", post)
    model.chat({**chat(), "session_id": "private@example.invalid"})
    assert "private@example.invalid" not in model.log_path.read_text()
    assert "session_id" not in rows(model)[0]["honoured"]
    assert "session_id" in rows(model)[0]["enforced"]


@pytest.mark.parametrize("detail", [[], "bad", False, 0])
def test_malformed_details_fail_loud(
    model: gw.Gateway, monkeypatch: pytest.MonkeyPatch, detail: Any
) -> None:
    api(model, monkeypatch)
    model.settings.provider_retries = 0
    reply = response()
    reply["usage"]["prompt_tokens_details"] = detail
    monkeypatch.setattr(gw, "post_json", lambda *a, **kw: reply)
    with pytest.raises(gw.GatewayError) as error:
        model.chat(chat())
    assert error.value.code == "invalid_provider_response"


def test_receipt_labels_reach_step_summary(model: gw.Gateway) -> None:
    model.chat(chat())
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
    ts = rows(model)[0]["ts"]
    steps = [
        {"event": event, "ts": ts, "loop": 0, "step_index": 1, "step": "coding"}
        for event in ("start", "end")
    ]
    (job.run / "steps.jsonl").write_text("".join(json.dumps(s) + "\n" for s in steps))
    job.write_call_labels()
    assert "coding" in job.receipt["call_split"]["chat_usage"]["by_step"]
    labelled = json.loads((job.run / "calls-labelled.jsonl").read_text())
    assert labelled["step"] == "coding"


def test_incomplete_usage_never_becomes_zero_cache_rate() -> None:
    calls = logged_calls()
    calls[1]["cached_tokens"] = None
    usage = launch.call_split(calls)["chat_usage"]
    assert usage["cached_tokens"] == 60
    assert usage["cache_hit_rate"] is None
    assert launch.call_split([])["chat_usage"]["cache_hit_rate"] is None


def test_failed_call_without_usage_is_counted_not_guessed() -> None:
    calls = logged_calls()
    calls.append({"endpoint": "/v1/chat/completions", "route": "api", "status": 502})
    usage = launch.call_split(calls)["chat_usage"]
    assert usage["usage_unknown_attempts"] == 1
    assert usage["prompt_tokens"] == 500
    assert usage["cache_hit_rate"] == 0.2


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


def test_receipt_reports_unknown_discount_and_estimate_basis() -> None:
    result = gateway_usage.receipt_usage(
        [
            {
                "endpoint": "/v1/chat/completions",
                "usd": 0.1,
                "cache_discount": None,
                "charged_usd": 0.04,
            }
        ]
    )
    assert result["cache_discount"] == "not reported by the provider"
    assert result["cost_estimate_basis"] == "upper-bound estimate at configured prices"
    assert result["charged_usd"] == 0.04


def test_receipt_cost_estimate_is_separate_from_provider_charge() -> None:
    usage = gateway_usage.receipt_usage(
        [
            {
                "endpoint": "/v1/chat/completions",
                "usd": 0.04,
                "estimated_usd": 0.1,
                "charged_usd": 0.04,
            }
        ]
    )
    assert usage["cost_estimate_usd"] == 0.1 and usage["charged_usd"] == 0.04


def test_timeout_reservation_is_not_reported_as_confirmed_usage() -> None:
    row = gateway_usage.record_defaults()
    gateway_usage.record_attempt(row, error="provider_timeout")
    assert row["usage_known"] is False
    assert (
        row["attempt_usage"][0]["cost_basis"] == "reserved estimate, not confirmed by the provider"
    )


def test_timeout_attempt_booked_amount_is_labelled(model: gw.Gateway) -> None:
    def fail(*args: Any) -> Any:
        raise gw.GatewayError(504, "provider_timeout", "timed out")

    model.chat_backend = SimpleNamespace(complete=fail)
    with pytest.raises(gw.GatewayError):
        model.chat(chat())
    logged = rows(model)[-1]
    assert logged["usage_known"] is False
    assert logged["cost_basis"] == "reserved estimate, not confirmed by the provider"
    assert logged["attempt_usage"][0]["booked_usd"] == 0


def test_receipt_separates_failed_wait_from_retried_calls(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from tests.unit.test_rdagent_factor_launch import args

    job = launch.Launch(
        args(tmp_path),
        {"ALPHA_RDAGENT_SOURCE": tmp_path, "ALPHA_FACTOR_PYTHON": tmp_path / "a/b/c/python"},
    )
    job.run.mkdir()
    (job.run / "history-context.json").write_text(
        json.dumps({"history_rounds_full": 4, "history_rounds_summarised": 17})
    )
    (job.run / "rounds.jsonl").write_text(
        json.dumps(
            {
                "iteration": 0,
                "status": "coding_failed_provider_timeout",
                "provider_wait_seconds": 360.5,
            }
        )
        + "\n"
    )
    job.receipt["call_split"] = launch.call_split(
        [
            {
                "endpoint": "/v1/chat/completions",
                "provider_errors": ["provider_timeout"],
                "error_code": error,
                "latency_ms": milliseconds,
                "attempts": 2,
            }
            for error, milliseconds in [("provider_timeout", 360500), (None, 181000)]
        ]
    )
    monkeypatch.setattr(job, "gateway_status", lambda: {})
    monkeypatch.setattr(job, "write_call_labels", lambda: {})
    job.finish(0, "completed")
    receipt = json.loads((job.run / "receipt.json").read_text())
    assert receipt["provider_failed_wait_seconds"] == 360.5
    assert receipt["provider_call_seconds_with_retries"] == 541.5
    assert "provider_wait_seconds" not in receipt
    assert receipt["history_rounds_full"] == 4
    assert receipt["history_rounds_summarised"] == 17


def test_proposal_receipt_counts_full_prompt_characters(model: gw.Gateway) -> None:
    model.chat(chat())
    row = rows(model)[0]
    assert row["total_prompt_chars"] == len("systemhello")
    labelled = [{**row, "step": "direct_exp_gen", "loop": 2}]
    assert launch.call_split([row], labelled)["proposal_prompt_chars"] == [
        {"loop": 2, "step": "direct_exp_gen", "chars": len("systemhello")}
    ]
