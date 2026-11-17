"""Construct-based proposals, honest feedback and request accounting; no model calls."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import Mock

import pytest

from tests.unit.test_rdagent_embedding_cap import model
from tests.unit.test_rdagent_loop_fixups_3 import (
    ProposingLoop,
    closed_volatility_ledger,
    judge_namespace,
    proposal,
    universe_run,
)
from workers.rdagent import factor_loop_launch as launch
from workers.rdagent import gateway_embeddings, gateway_usage

__all__ = ["model"]


@pytest.mark.parametrize(
    "name,description,variables,expected",
    [
        (
            "gradient_boosted_mix",
            "mix of inputs",
            {"momentum_30d": "x", "volatility_30d": "x", "volume_30d": "x", "high_prox_30d": "x"},
            "momentum and trend; price near its high / range position; "
            "volatility and beta; volume level and trend",
        ),
        (
            "price_delay_120d",
            "OLS regression beta slope residual momentum volatility",
            {},
            "other: price_delay",
        ),
        (
            "btc_lag_spillover_5_120d",
            "regression against market beta and volume",
            {},
            "other: btc_lag_spillover",
        ),
        (
            "lightgbm_mix",
            "model using features",
            {"long_term_reversal": "momentum regression", "vwap_distance": "volume weighted"},
            "VWAP distance; long-term reversal",
        ),
        ("volume weighted average price distance", "volume trend", {}, "VWAP distance"),
    ],
)
def test_real_proposals_classify_construct_names(
    name: str, description: str, variables: dict[str, str], expected: str
) -> None:
    assert (
        judge_namespace()["idea_family"](name, description, "volume * volatility", variables)
        == expected
    )


@pytest.mark.parametrize("name", ["long-term reversal", "Long Term Reversal", "long_term_reversal"])
def test_name_normalisation(name: str) -> None:
    assert judge_namespace()["idea_family"](name) == "long-term reversal"


def test_estimator_words_are_not_family_keywords() -> None:
    ns = judge_namespace()
    generic = {
        "beta",
        "slope",
        "regression",
        "ols",
        "ridge",
        "huber",
        "lasso",
        "lightgbm",
        "gbm",
        "model",
        "residual",
        "rank",
        "zscore",
    }
    assert ns["GENERIC_ESTIMATOR_WORDS"] == generic
    assert not generic & {word for _, words in ns["FAMILY_KEYWORDS"] for word in words}
    assert ns["idea_family"]("market_beta_30d") == "volatility and beta"
    assert ns["input_families"]("volume weighted average price distance", "long-term reversal") == {
        "VWAP distance",
        "long-term reversal",
    }


def test_refusal_records_round_names_and_all_closed_and_labels_reasks(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    closed_volatility_ledger(tmp_path, monkeypatch)
    ns = judge_namespace()
    ns["closed_families"] = lambda: {"volatility and beta", "volume level and trend"}
    loop: Any = ProposingLoop(ns, [proposal("price_delay_120d", "OLS volatility")])
    loop.loop_idx = 4
    coder = SimpleNamespace(develop=Mock(return_value="coded"))
    assert ns["FamilyGuard"](coder, loop).develop(proposal("volatility_30d", "")) == "coded"
    row = json.loads((tmp_path / "rounds.jsonl").read_text())
    assert row["iteration"] == 4 and row["attempt"] == 1
    assert row["factor_names"] == ["volatility_30d"]
    assert row["refused_families"] == ["volatility and beta"]
    assert row["all_closed_families"] == ["volatility and beta", "volume level and trend"]
    assert "closed_families" not in row
    assert "A mechanism that belongs to none of the closed families is allowed." in row["message"]
    steps = [json.loads(line) for line in (tmp_path / "steps.jsonl").read_text().splitlines()]
    calls = [{"ts": steps[0]["ts"], "endpoint": "/v1/chat/completions", "attempts": 1, "usd": 0.2}]
    labelled = launch.label_calls(calls, steps)
    assert labelled[0]["step"] == "proposal_reask"
    split = launch.call_split(calls, labelled)
    assert split["reask_calls"] == 1 and split["reask_usd"] == 0.2
    assert "proposal_reask" in split["chat_usage"]["by_step"]


def test_feedback_prompt_has_closed_and_open_family_context(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    universe_run(tmp_path, monkeypatch)
    closed_volatility_ledger(tmp_path, monkeypatch)
    ns = judge_namespace()
    backend = Mock(return_value="{}")
    ns["APIBackend"] = lambda: SimpleNamespace(build_messages_and_create_chat_completion=backend)
    ns["T"] = lambda _: SimpleNamespace(r=lambda **kw: json.dumps(kw))
    exp = SimpleNamespace(
        hypothesis=SimpleNamespace(hypothesis="idea"),
        sub_tasks=[],
        stdout="",
        alpha_evaluation={"iteration": 0, "decision": False, "factors": []},
    )
    feedback = ns["AlphaFactorFeedback"]()
    feedback.scen = SimpleNamespace(get_scenario_all_desc=lambda: "scenario")
    feedback.generate_feedback(exp, None)
    prompt = backend.call_args.kwargs["system_prompt"]
    assert "Closed families: volatility and beta" in prompt
    assert "open families:" in prompt and "A mechanism that belongs to none" in prompt


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


def test_model_text_missing_and_small_figures() -> None:
    ns = judge_namespace()
    assert ns["_rounded"](None) == "not available"
    assert ns["_rounded"](0.00001234567) == "1.235e-05"
    note = ns["replay_note"](
        "weekly",
        {
            "gross": {"annualized_return": 0.123456},
            "net": {"annualized_return": 0.1},
            "annual_cost": 0.0000123456,
            "mean_turnover": 0.00000123456,
        },
    )
    assert "12.35%" in note and "0.001235%" in note and "0.0001235%" in note


def test_embedding_missing_model_is_logged_and_counted(
    model: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    from tests.unit.test_rdagent_embedding_cap import rows
    from tests.unit.test_rdagent_provider_embeddings import provider
    from workers.rdagent import model_gateway as gw

    provider(model, monkeypatch)
    monkeypatch.setattr(
        gw, "post_json", lambda *a, **kw: {"data": [{"index": 0, "embedding": [1.0]}]}
    )
    model.embeddings({"model": "alpha-embed", "input": "abc"})
    row = rows(model)[-1]
    assert row["response_model"] is None
    assert row["model_check"] == "model_not_reported"
    assert row["reserved_usd"] == pytest.approx(3e-6)
    assert launch.call_split(rows(model))["embedding_model_not_reported"] == 1


def test_provider_batches_order_and_single_settlement(
    model: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    from tests.unit.test_rdagent_embedding_cap import rows
    from tests.unit.test_rdagent_provider_embeddings import provider
    from workers.rdagent import model_gateway as gw

    provider(model, monkeypatch)
    sent: list[list[str]] = []
    settlements = Mock(wraps=gateway_embeddings.settle_embedding)
    monkeypatch.setattr(gateway_embeddings, "settle_embedding", settlements)

    def post(url: str, body: dict[str, Any], *args: Any, **kwargs: Any) -> dict[str, Any]:
        inputs = body["input"]
        sent.append(inputs)
        assert len(inputs) <= 32
        return {
            "model": "model-a",
            "data": [
                {"index": i, "embedding": [float(t)]} for i, t in reversed(list(enumerate(inputs)))
            ],
            "usage": {"total_tokens": len(inputs)},
        }

    monkeypatch.setattr(gw, "post_json", post)
    result = model.embeddings({"model": "alpha-embed", "input": [str(i) for i in range(65)]})
    assert [len(batch) for batch in sent] == [32, 32, 1]
    assert [item["embedding"][0] for item in result["data"]] == list(range(65))
    assert settlements.call_count == 3
    state = model.budget.status()["runs"]["test"]
    assert state["provider_embedding_calls"] == 3 and state["calls"] == 0
    assert state["usd"] == pytest.approx(65 * 3e-6)
    split = launch.call_split(rows(model))
    assert split["provider_embedding_requests"] == 3
    assert split["provider_embedding_inputs"] == 65


def test_refused_batch_retries_singly_and_keeps_good_inputs(
    model: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    from tests.unit.test_rdagent_embedding_cap import rows
    from tests.unit.test_rdagent_provider_embeddings import provider
    from workers.rdagent import model_gateway as gw

    provider(model, monkeypatch)
    sent: list[list[str]] = []

    def post(url: str, body: dict[str, Any], *args: Any, **kwargs: Any) -> dict[str, Any]:
        inputs = body["input"]
        sent.append(inputs)
        if len(inputs) > 1 or inputs == ["bad"]:
            raise gw.GatewayError(
                400, "invalid_input", "bad input", payload={"error": {"code": "invalid_input"}}
            )
        return {
            "model": "model-a",
            "data": [{"index": 0, "embedding": [float(inputs[0])]}],
            "usage": {"total_tokens": 1},
        }

    monkeypatch.setattr(gw, "post_json", post)
    result = model.embeddings({"model": "alpha-embed", "input": ["1", "bad", "3"]})
    assert sent == [["1", "bad", "3"], ["1"], ["bad"], ["3"]]
    assert [(item["index"], item["embedding"]) for item in result["data"]] == [
        (0, [1.0]),
        (2, [3.0]),
    ]
    assert result["input_errors"][0]["index"] == 1
    assert result["input_errors"][0]["code"] == "embedding_input_refused"
    split = launch.call_split(rows(model))
    assert split["embedding_single_retries"] == 3
    assert split["provider_embedding_requests"] == 4
    assert model.budget.status()["runs"]["test"]["usd"] == pytest.approx(6e-6)


def test_provider_batch_requests_stop_at_embedding_cap(
    model: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    from tests.unit.test_rdagent_provider_embeddings import provider
    from workers.rdagent import model_gateway as gw

    provider(model, monkeypatch)
    model.budget.write(
        {
            "schema_version": 1,
            "runs": {"test": {"calls": 0, "usd": 0, "local_embedding_calls": 1999}},
            "months": {},
        }
    )
    sent = Mock(
        side_effect=lambda url, body, *a, **kw: {
            "model": "model-a",
            "data": [{"index": i, "embedding": [1.0]} for i in range(len(body["input"]))],
        }
    )
    monkeypatch.setattr(gw, "post_json", sent)
    with pytest.raises(gw.GatewayError, match="EMBEDDING_CALLS_PER_RUN"):
        model.embeddings({"model": "alpha-embed", "input": ["x"] * 33})
    assert sent.call_count == 1


def test_receipt_round_counts_and_old_refusal_key(tmp_path: Path) -> None:
    records = [
        {"iteration": 0, "status": "refused_closed_family", "closed_families": ["volatility"]},
        {"iteration": 0, "alpha_decision": False, "tasks": [{"name": "price_delay"}]},
        {
            "iteration": 1,
            "status": "no_admissible_idea",
            "reason": "refused_closed_family",
            "refused_families": ["volatility"],
        },
    ]
    (tmp_path / "rounds.jsonl").write_text("".join(json.dumps(r) + "\n" for r in records))
    (tmp_path / "evaluations.jsonl").write_text(
        json.dumps({"iteration": 0, "factors": [{"name": "price_delay"}]}) + "\n"
    )
    result = launch.round_counts(tmp_path)
    assert result == {
        "rounds_with_trial": 1,
        "rounds_no_admissible_idea": 1,
        "proposals_refused": 2,
    }


def test_paid_memory_reembeds_in_one_batch_and_keeps_good_nodes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from workers.rdagent import research_memory as memory

    monkeypatch.setenv("ALPHA_EMBEDDING_ROUTE", "provider")
    graph = SimpleNamespace(
        nodes={str(i): SimpleNamespace(content=str(i), embedding=[9.0]) for i in range(3)}
    )
    calls: list[list[str]] = []

    def embed_many(texts: list[str]) -> tuple[str, list[Any]]:
        calls.append(texts)
        return "model-a", [
            [1.0],
            memory.MemoryEmbeddingError("embedding_input_refused", "bad input"),
            [3.0],
        ]

    monkeypatch.setattr(memory, "gateway_embedding_batch", embed_many, raising=False)
    monkeypatch.setattr(
        memory, "gateway_embedding", Mock(side_effect=AssertionError("singleton transport used"))
    )
    cache = memory.EmbeddingMemory(
        tmp_path / "sidecar", tmp_path / "events", "model-a", memory.gateway_embedding
    )
    skipped: list[str] = []
    removed = cache.prepare(graph, lambda node, error: skipped.append(node.content))
    assert calls == [["0", "1", "2"]]
    assert skipped == ["1"] and set(removed) == {"1"}
    assert graph.nodes["0"].embedding == [1.0] and graph.nodes["2"].embedding == [3.0]
    cache.prepare(graph, lambda node, error: pytest.fail(str(error)))
    assert len(calls) == 1


def test_single_construct_has_one_family_and_named_abbreviations() -> None:
    family = judge_namespace()["idea_family"]
    assert family("vol_adjusted_momentum_28d") == "momentum and trend"
    assert family("vol_scaled_high_prox_252d") == "price near its high / range position"
    assert (
        family("ridge_mix", variables={"vol60": "unread", "mdd120": "unread", "ac60": "unread"})
        == "drawdown; momentum and trend; volatility and beta"
    )


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


def test_bad_last_input_in_partial_batch_keeps_earlier_vectors(
    model: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    from tests.unit.test_rdagent_provider_embeddings import provider
    from workers.rdagent import model_gateway as gw

    provider(model, monkeypatch)

    def post(url: str, body: dict[str, Any], *args: Any, **kwargs: Any) -> dict[str, Any]:
        if body["input"] == ["bad"]:
            raise gw.GatewayError(400, "invalid_input", "bad input")
        return {
            "model": "model-a",
            "data": [{"index": i, "embedding": [1.0]} for i in range(len(body["input"]))],
        }

    monkeypatch.setattr(gw, "post_json", post)
    result = model.embeddings({"model": "alpha-embed", "input": ["good"] * 32 + ["bad"]})
    assert len(result["data"]) == 32 and result["input_errors"][0]["index"] == 32


def test_only_refused_task_names_are_recorded(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    closed_volatility_ledger(tmp_path, monkeypatch)
    ns = judge_namespace()
    exp = proposal("volatility_30d", "")
    exp.sub_tasks += proposal("price_delay_120d", "").sub_tasks
    with pytest.raises(ValueError, match="No admissible idea"):
        ns["FamilyGuard"](SimpleNamespace(develop=Mock())).develop(exp)
    row = json.loads((tmp_path / "rounds.jsonl").read_text())
    assert row["factor_names"] == ["volatility_30d"]


def test_mismatched_embedding_model_is_logged_even_when_refused(
    model: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    from tests.unit.test_rdagent_embedding_cap import rows
    from tests.unit.test_rdagent_provider_embeddings import provider
    from workers.rdagent import model_gateway as gw

    provider(model, monkeypatch)
    monkeypatch.setattr(
        gw,
        "post_json",
        lambda *a, **kw: {
            "model": "wrong",
            "data": [{"index": 0, "embedding": [1.0]}],
            "usage": {"total_tokens": 2},
        },
    )
    with pytest.raises(gw.GatewayError, match="invalid embeddings"):
        model.embeddings({"model": "alpha-embed", "input": "abc"})
    row = rows(model)[-1]
    assert row["response_model"] == "wrong" and row["model_check"] == "model_mismatch"
    assert row["reserved_usd"] == pytest.approx(3e-6) and row["usd"] == pytest.approx(6e-6)


def test_single_trial_and_writeoff_use_singular_text() -> None:
    ns = judge_namespace()
    row = {
        "schema": "AlphaRdagentFactorTrialV2",
        "name": "price_delay_120d",
        "status": "SCREEN_FAIL",
        "screen": {},
        "q": 1.0,
        "run_id": "test",
        "writeoff_count": 1,
    }
    assert ": 1 try;" in ns["family_summary"]([row], 3)
    assert ns["ledger_summary"](row).endswith("; 1 write-off")


def test_single_paid_memory_input_refusal_uses_skip_policy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from workers.rdagent import research_memory as memory

    monkeypatch.setenv("ALPHA_EMBEDDING_ROUTE", "provider")
    error = memory.MemoryEmbeddingError("embedding_input_refused", "bad input")
    single = Mock(side_effect=error)
    batch = Mock(side_effect=AssertionError("one input needs the existing skip policy"))
    monkeypatch.setattr(memory, "gateway_embedding", single)
    monkeypatch.setattr(memory, "gateway_embedding_batch", batch)
    graph = SimpleNamespace(nodes={"bad": SimpleNamespace(content="bad", embedding=[9.0])})
    cache = memory.EmbeddingMemory(tmp_path / "sidecar", tmp_path / "events", "model-a", single)
    skipped: list[str] = []
    removed = cache.prepare(graph, lambda node, exc: skipped.append(str(exc)))
    assert skipped == ["bad input"] and set(removed) == {"bad"} and not graph.nodes
    batch.assert_not_called()


# The real proposals of runs/2026-11-17-rdagent-wide-universe-2, as RD-Agent listed them: the
# variable names are the proposer's own (math symbols, hyperparameters and features alike).
WIDE_RUN_CLOSED = {
    "composite: unknown inputs",
    "illiquidity",
    "momentum and trend",
    "price near its high / range position",
    "range and compression",
    "return-volume relation",
    "short-term reversal and gaps",
    "skewness and lottery returns",
    "volatility and beta",
    "volume level and trend",
}
WIDE_RUN_PROPOSALS: list[tuple[str, str, list[str], bool]] = [
    (
        "gbm_spread_7d",
        "[Machine Learning based Factor] Strictly causal spread-aware gradient-boosted "
        "cross-sectional factor for the 7-day horizon.",
        ["C_{i,s", "H_{i,s", "V_{i,s", "r_{i,s", "m20_{i,t", "m60_{i,t", "vol60_{i,t"]
        + ["vt60_{i,t", "ldv60_{i,t", "hp120_{i,t", "RV60_{i,t", "jv60_{i,t", "svi20_{i,t"]
        + ["R_{i,t", "rank_mom20_{i,t", "m(t)", "D_{m(t)}", "h", "20", "max_depth"],
        True,
    ),
    (
        "price_delay_120d",
        "[Information-Diffusion / Price-Delay Factor] Slow price-delay measure for each coin, "
        "computed as one minus the ratio of the R-squared from a contemporaneous-market "
        "regression to the R-squared from a full distributed-lag regression.",
        ["C_{i,s}", "r_{i,s}", "A_s", "N_s", "m_s", "t", "W_t", "120", "R^2_{full,i,t}"],
        False,
    ),
    (
        "btc_lag_spillover_5_120d",
        "[Lead-Lag Spillover / BTC Factor] For each lag, estimate the OLS slope beta_{i,l,t} of "
        "coin i's daily log return on BTC's l-day-lagged daily log return.",
        ["C_{i,s}", "C_{BTC,s}", "r_{i,s}", "r_{BTC,s}", "\\beta_{i,l,t}", "\\bar{r}_{i,t}"],
        False,
    ),
    (
        "ml_gbdt_topthird_28d",
        "[Machine Learning based Factor] Strictly causal LightGBM binary classifier for the "
        "28-day horizon over long-term reversal ltr and VWAP distance vwap.",
        ["C_{i,s}", "O_{i,s}", "V_{i,s}", "h", "L", "ltr_{i,t}", "vwap_{i,t}", "m(t)"]
        + ["D_{m(t)}", "num_leaves", "learning_rate", "p_{i,t}", "rank_t", "f_{i,t}"],
        False,
    ),
    (
        "max_drawdown_252d",
        "[Distress / Drawdown Factor] Maximum peak-to-trough close drawdown over 252 days.",
        ["C_{i,s}", "t", "252", "a", "b", "f_{i,t}"],
        False,
    ),
]


@pytest.mark.parametrize("name,description,variables,refused", WIDE_RUN_PROPOSALS)
def test_wide_run_proposals_with_their_real_variable_lists(
    name: str, description: str, variables: list[str], refused: bool
) -> None:
    family = judge_namespace()["idea_family"](
        name, description, "", dict.fromkeys(variables, "proposer text")
    )
    assert bool(set(family.split("; ")) & WIDE_RUN_CLOSED) is refused, family
    assert "other: c_" not in family and "other: m" not in family


def test_math_symbols_and_numbers_never_become_families() -> None:
    ns = judge_namespace()
    symbols = dict.fromkeys(["m(t)", "m_s", "ret_{i,t}", "C_{i,s}", "120", "max_depth"], "x")
    assert ns["idea_family"]("ml_mix", "machine learning", "", symbols) == (
        "composite: unknown inputs"
    )
    assert ns["idea_family"]("m_s") == "other: m_s"
    for name, family in (("m20", "momentum"), ("ret_60d", "momentum"), ("hp126", "high")):
        assert family in ns["idea_family"](name)


def test_prose_only_composite_is_unknown_inputs_not_an_open_other() -> None:
    family = judge_namespace()["idea_family"]
    assert family("swing_alpha_v1", "LightGBM over momentum and volatility") == (
        "composite: unknown inputs"
    )
    assert family("factor_a", "A blend of momentum and volatility ranks") == (
        "composite: unknown inputs"
    )


def test_regression_is_one_construct_unless_it_lists_two_known_features() -> None:
    family = judge_namespace()["idea_family"]
    inputs = {"m20": "momentum", "vol60": "volatility"}
    assert family("xs_reg", "cross-sectional regression", "", inputs) == (
        "momentum and trend; volatility and beta"
    )
    assert family("lag_slope_60d", "OLS regression on lagged BTC", "", {"m20": "x"}) == (
        "other: lag_slope"
    )


def test_composite_history_adds_no_symbol_families() -> None:
    ns = judge_namespace()
    rows = [
        {
            "schema": "AlphaRdagentFactorTrialV2",
            "name": f"ml_mix_{i}",
            "status": "SCREEN_FAIL",
            "description": "machine learning",
            "variables": {"C_{i,s}": "close", "jv60": "jump", "m(t)": "month"},
            "screen": {},
            "q": 1.0,
            "run_id": "test",
        }
        for i in range(3)
    ]
    summary = ns["family_summary"](rows, 3)
    assert "other:" not in summary
    assert "no candidate: composite: unknown inputs." in summary


def test_refusal_message_has_no_doubled_full_stop(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    closed_volatility_ledger(tmp_path, monkeypatch)
    ns = judge_namespace()
    with pytest.raises(ValueError, match="No admissible idea"):
        ns["FamilyGuard"](SimpleNamespace(develop=Mock())).develop(proposal("volatility_30d", ""))
    message = json.loads((tmp_path / "rounds.jsonl").read_text())["message"]
    assert ".." not in message and "allowed. No admissible idea" in message


def test_failed_paid_memory_batch_goes_through_skip_policy_without_resending(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from workers.rdagent import research_memory as memory

    monkeypatch.setenv("ALPHA_EMBEDDING_ROUTE", "provider")
    stop = memory.MemoryEmbeddingError("budget_exhausted", "budget exhausted: run_max_usd")
    batch = Mock(side_effect=stop)
    single = Mock(side_effect=AssertionError("a failed batch is not re-sent per input"))
    monkeypatch.setattr(memory, "gateway_embedding_batch", batch)
    monkeypatch.setattr(memory, "gateway_embedding", single)
    graph = SimpleNamespace(
        nodes={str(i): SimpleNamespace(content=str(i), embedding=None) for i in range(3)}
    )
    cache = memory.EmbeddingMemory(tmp_path / "sidecar", tmp_path / "events", "model-a", single)
    seen: list[BaseException] = []

    def skip(node: Any, error: Exception) -> None:
        seen.append(error)  # the coder's skip raises BudgetExhausted for this code
        raise SystemExit(str(error))

    with pytest.raises(SystemExit, match="budget exhausted"):
        cache.prepare(graph, skip)
    assert seen == [stop] and batch.call_count == 1


def test_local_route_call_rows_and_requests_are_unchanged(model: Any) -> None:
    from tests.unit.test_rdagent_embedding_cap import rows

    result = model.embeddings({"model": "alpha-embed", "input": ["a"]})
    assert len(result["data"]) == 1 and len(rows(model)) == 1
    added = {"response_model", "reserved_usd", "input_count", "single_retry", "model_check"}
    assert not added & set(rows(model)[0])
