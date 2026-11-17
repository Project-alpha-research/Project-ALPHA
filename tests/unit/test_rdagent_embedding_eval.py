"""Hand-computed retrieval scores; no model calls."""

from __future__ import annotations

import pytest

from workers.rdagent import embedding_eval as ev


def test_hand_computed_metrics_include_refused_relevant_entries() -> None:
    entries = [
        {"id": str(i), "text": str(i), "idea_family": "f", "outcome": "failed"} for i in range(6)
    ]
    queries = [{"text": "q", "relevant_ids": ["1", "4", "5"]}]

    def embed(text: str) -> ev.EmbeddedInput:
        if text == "5":
            raise ev.InputRefused("too long")
        return ev.EmbeddedInput(
            [1.0, 0.0] if text == "q" else [1.0, float(text)], split_inputs=int(text == "3")
        )

    result = ev.evaluate(entries, queries, embed)
    assert result["recall_at_3"] == pytest.approx(1 / 3)
    assert result["recall_at_5"] == pytest.approx(2 / 3)
    assert result["mean_reciprocal_rank"] == 0.5
    assert result["inputs_refused"] == result["inputs_split"] == 1


def test_refused_query_is_zero_not_dropped() -> None:
    def embed(text: str) -> list[float]:
        if text == "q":
            raise ev.InputRefused("too long")
        return [1.0]

    result = ev.evaluate([{"id": "a", "text": "a"}], [{"text": "q", "relevant_ids": ["a"]}], embed)
    assert result["recall_at_3"] == result["mean_reciprocal_rank"] == 0


def test_proxy_labels_family_and_symbol_set_exclude_self() -> None:
    memory = [{"id": str(i), "text": str(i)} for i in range(4)]
    ledger = [
        {"id": "0", "idea_family": "trend", "symbols": ["A", "B"], "outcome": "failed"},
        {"id": "1", "idea_family": "trend", "symbols": ["B", "A"], "outcome": "passed"},
        {"id": "2", "idea_family": "trend", "symbols": ["A"], "outcome": "failed"},
        {"id": "3", "idea_family": "value", "symbols": ["A", "B"], "outcome": "failed"},
    ]
    labelled = ev.build_labelled_set(ledger, memory)
    assert labelled["queries"] == [
        {"text": "0", "relevant_ids": ["1"], "exclude_ids": ["0"]},
        {"text": "1", "relevant_ids": ["0"], "exclude_ids": ["1"]},
    ]
    assert "proxy" in labelled["relevance_rule"] and "symbol" in labelled["relevance_rule"]


@pytest.mark.parametrize("vector", [[0.0], [float("nan")], [1.0, 2.0]])
def test_invalid_or_mismatched_vectors_fail_loud(vector: list[float]) -> None:
    def embed(text: str) -> list[float]:
        return [1.0] if text == "a" else vector

    with pytest.raises(ValueError):
        ev.evaluate([{"id": "a", "text": "a"}], [{"text": "q", "relevant_ids": ["a"]}], embed)


def test_unknown_relevance_is_an_error() -> None:
    with pytest.raises(ValueError, match="relevant"):
        ev.evaluate(
            [{"id": "a", "text": "a"}],
            [{"text": "q", "relevant_ids": ["missing"]}],
            lambda text: [1.0],
        )


def test_budget_error_is_not_a_refusal() -> None:
    def embed(text: str) -> list[float]:
        raise RuntimeError("budget exhausted")

    with pytest.raises(RuntimeError, match="budget exhausted"):
        ev.evaluate([{"id": "a", "text": "a"}], [{"text": "q", "relevant_ids": ["a"]}], embed)


def test_model_identity_cannot_change_during_comparison() -> None:
    def embed(text: str) -> ev.EmbeddedInput:
        return ev.EmbeddedInput([1.0], model="A" if text == "a" else "B")

    with pytest.raises(ValueError, match="model"):
        ev.evaluate([{"id": "a", "text": "a"}], [{"text": "q", "relevant_ids": ["a"]}], embed)
