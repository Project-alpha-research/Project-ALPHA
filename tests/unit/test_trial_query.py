"""Named questions bind values and never grant SQL or filesystem access."""

from pathlib import Path
from typing import Any

import pytest

from alpha_cli.spine.errors import SpineError
from alpha_cli.spine.trial_query import QUESTIONS, connection, query
from alpha_cli.spine.trial_reader import ledger_sources, read_ledgers
from tests.unit.test_trial_reader import example


@pytest.mark.parametrize(
    "question",
    [
        "by-family",
        "by-outcome",
        "by-asset",
        "by-month",
        "asset-history",
        "family-trials",
        "top-measure",
        "repeats",
    ],
)
def test_every_question(tmp_path: Path, question: Any) -> None:
    home, rd = example(tmp_path)
    snapshot = read_ledgers(ledger_sources(home, rd))
    by_question: dict[str, dict[str, Any]] = {
        "asset-history": {"asset": "SPY"},
        "family-trials": {"family": "rule:f1"},
        "top-measure": {"measure": "mean_ic"},
    }
    result = query(snapshot, question, **by_question.get(question, {}))
    assert result and len(result) <= 50
    assert set(QUESTIONS) == {
        "by-family",
        "by-outcome",
        "by-asset",
        "by-month",
        "asset-history",
        "family-trials",
        "top-measure",
        "repeats",
    }
    if question == "by-outcome":
        assert {r["outcome"]: r["rows"] for r in result} == {
            "supported": 2,
            "rejected": 2,
            "inconclusive": 1,
            "recorded": 1,
            "error": 1,
        }


def test_empty_and_external_access(tmp_path: Path) -> None:
    snapshot = read_ledgers(ledger_sources(tmp_path, None))
    assert query(snapshot, "by-family") == []
    with connection(snapshot) as con:
        import duckdb

        with pytest.raises(duckdb.Error, match="[Dd]isabled|[Pp]ermission|[Ee]xternal"):
            con.execute("SELECT * FROM read_csv('x')")


@pytest.mark.parametrize(
    ("question", "parameters", "code"),
    [
        ("SELECT 1", {}, "UNKNOWN_QUESTION"),
        ("asset-history", {}, "BAD_PARAMETER"),
        ("family-trials", {}, "BAD_PARAMETER"),
        ("top-measure", {}, "BAD_PARAMETER"),
        ("top-measure", {"measure": "oops"}, "BAD_PARAMETER"),
        ("by-family", {"asset": "SPY"}, "BAD_PARAMETER"),
        ("by-family", {"limit": 0}, "BAD_PARAMETER"),
        ("by-family", {"limit": 201}, "BAD_PARAMETER"),
    ],
)
def test_bad_parameters(tmp_path: Path, question: Any, parameters: Any, code: Any) -> None:
    with pytest.raises(SpineError) as error:
        query(read_ledgers(ledger_sources(tmp_path, None)), question, **parameters)
    assert error.value.payload["code"] == code


def test_bindings_order_limit_and_unknown_month(tmp_path: Path) -> None:
    from tests.unit.test_trial_reader import write_rows
    from tests.unit.test_trial_record import factor

    rd = tmp_path / "factors.jsonl"
    write_rows(rd, [factor(1, p=0.4, run_id="undated"), factor(1, trial_index=2, p=0.1)])
    snapshot = read_ledgers(ledger_sources(tmp_path, rd))
    assert query(snapshot, "top-measure", measure="p", limit=1)[0]["trial_id"] == "rdagent:2"
    assert query(snapshot, "by-month") == [
        {"month": "2026-11", "rows": 1},
        {"month": "unknown", "rows": 1},
    ]
    assert query(snapshot, "asset-history", asset="x' OR TRUE --") == []
