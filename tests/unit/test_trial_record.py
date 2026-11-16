"""Mapping contracts over historical ledger shapes; no writers involved."""

from dataclasses import FrozenInstanceError
from pathlib import Path
from typing import Any

import pytest

from alpha_cli.spine.trial_record import OUTCOMES, map_row


def spine(**updates: Any) -> dict[str, Any]:
    return (
        dict(
            schema="AlphaTrialV1",
            trial_index=1,
            rule="ma_cross",
            name="Trend",
            labels=[],
            verdict="B",
            recorded_at="2026-11-16T12:00:00+00:00",
            run_id="abc",
            symbol="SPY",
            spec_sha256="a" * 64,
            periods_per_year=252,
            first_ts="2020-01-01",
            last_ts="2023-12-31",
            oos_sharpe=0.7,
            benchmark_sharpe=0.4,
            dsr=0.8,
        )
        | updates
    )


def factor(version: Any = 3, **updates: Any) -> dict[str, Any]:
    return (
        dict(
            schema=f"AlphaRdagentFactorTrialV{version}",
            trial_index=1,
            name="factor",
            plain_name="Factor",
            code_sha256="b" * 64,
            run_id="2026-11-15-factor",
            family_size=4,
            status="CANDIDATE",
            p=0.01,
            q=0.03,
            windows={
                "history": ["2017-01-01", "2020-12-31"],
                "exploration": ["2021-01-01", "2023-12-24"],
                "panel_end": "2023-12-31",
                "reserved_start": "2024-01-01",
            },
            screen={"mean_ic": 0.1},
            replay={},
            instruments=["BTCUSDT"],
            clocks={c: {"screen": {"mean_ic": 0.2}} for c in ("daily", "weekly", "monthly")},
            lead_clock="weekly",
            label="exploratory, not admitted",
            authority={"admitted": False},
            exposure={"previously_exposed": True},
            survivorship=["survivors"],
            evidence={"series_manifest": "series/manifest.json", "sha256": "c" * 64},
        )
        | updates
    )


def rule(**updates: Any) -> dict[str, Any]:
    return (
        factor(
            schema="AlphaRuleTrialV1",
            status="INSUFFICIENT",
            family_id="f1",
            family_size=2,
            windows={
                "history_start": "2017-01-01",
                "exploration_end": "2023-12-31",
                "scored_start": "2021-01-01",
                "scored_end": "2023-12-24",
                "reserved_start": "2024-01-01",
            },
            replay={"annualised_excess": 0.12},
            evidence={"trial": "trials/a/trial.json", "sha256": "d" * 64},
        )
        | updates
    )


def mapped(row: Any) -> Any:
    return map_row(
        "spine" if row["schema"] == "AlphaTrialV1" else "rdagent", Path("/ledger"), 2, row
    )


@pytest.mark.parametrize(
    ("verdict", "outcome"),
    [
        ("A", "supported"),
        ("B", "supported"),
        ("C", "inconclusive"),
        ("D", "rejected"),
        ("F", "rejected"),
        (None, "recorded"),
    ],
)
def test_spine_outcomes(verdict: Any, outcome: Any) -> None:
    assert mapped(spine(verdict=verdict)).outcome == outcome
    assert mapped(spine(verdict=verdict, labels=["error"])).outcome == "error"


@pytest.mark.parametrize(
    ("status", "outcome"),
    [
        ("CANDIDATE", "supported"),
        ("SCREEN_FAIL", "rejected"),
        ("REPLAY_FAIL", "rejected"),
        ("FAST_ONLY", "rejected"),
        ("DEGENERATE", "invalid"),
        ("LOOKAHEAD", "invalid"),
        ("FAILED", "error"),
        ("ERROR", "error"),
        ("IMPORTED", "recorded"),
        ("REPEAT", "recorded"),
    ],
)
@pytest.mark.parametrize("version", [1, 2, 3])
def test_factor_outcomes(version: Any, status: Any, outcome: Any) -> None:
    record = mapped(factor(version, status=status))
    assert record.outcome == outcome
    assert record.counts_for_deflation == (status != "REPEAT")


@pytest.mark.parametrize(
    ("status", "outcome"),
    [
        ("SUPPORT", "supported"),
        ("CONTRADICTION", "rejected"),
        ("INSUFFICIENT", "inconclusive"),
        ("INVALID", "invalid"),
    ],
)
def test_rule_outcomes(status: Any, outcome: Any) -> None:
    assert mapped(rule(status=status)).outcome == outcome


def test_common_fields() -> None:
    record = mapped(spine())
    assert record.trial_id == "spine:1" and record.family_id == "spine:ma_cross"
    assert record.assets == ("SPY",) and record.bar_size == "1D"
    assert record.windows == {"data_start": "2020-01-01", "data_end": "2023-12-31"}
    assert record.measures == {"oos_sharpe": 0.7, "benchmark_sharpe": 0.4, "dsr": 0.8}
    assert record.evidence_path == "runs/abc/manifest.json" and record.evidence_sha256 is None
    assert record.source_file == "/ledger" and record.source_line == 2
    assert record.created_at_basis == "recorded" and record.spec_hash == "a" * 64
    with pytest.raises(FrozenInstanceError):
        record.name = "changed"
    assert set(OUTCOMES) == {
        "supported",
        "rejected",
        "inconclusive",
        "invalid",
        "error",
        "recorded",
    }
    assert mapped(spine(kind="rule_test")) == record
    assert mapped(spine(symbol=None, periods_per_year=12)).assets == ()
    assert mapped(spine(periods_per_year=365)).bar_size == "1D"
    assert mapped(spine(periods_per_year=12)).bar_size is None


@pytest.mark.parametrize(
    ("kind", "family", "subkind", "path"),
    [
        ("tool:acf", "spine-tool:acf", "acf", "tools/result.json"),
        ("setup_find", "spine-setup:Trend", None, "setups/find1/manifest.json"),
        ("future", "spine-other", "future", "runs/abc/manifest.json"),
    ],
)
def test_other_spine_kinds(kind: Any, family: Any, subkind: Any, path: Any) -> None:
    record = mapped(spine(kind=kind, tool_output="tools/result.json", find_id="find1"))
    assert (record.family_id, record.subkind, record.evidence_path) == (family, subkind, path)
    assert record.outcome == "recorded" and not record.counts_for_deflation


def test_rdagent_fields_and_legacy() -> None:
    record = mapped(factor())
    assert record.measures == {"p": 0.01, "q": 0.03, "mean_ic": 0.2}
    assert record.windows == {
        "data_start": "2017-01-01",
        "data_end": "2023-12-31",
        "scored_start": "2021-01-01",
        "scored_end": "2023-12-24",
        "reserved_start": "2024-01-01",
    }
    assert record.created_at == "2026-11-15" and record.created_at_basis == "run-id date"
    assert record.labels == (
        "exploratory",
        "not-admitted",
        "previously-exposed",
        "survivor-universe",
    )
    assert mapped(factor(status="REPEAT")).labels[-1] == "repeat"
    assert mapped(factor(status="IMPORTED")).labels[-1] == "imported"
    old = factor(1)
    for key in ("instruments", "exposure", "evidence", "clocks", "lead_clock"):
        del old[key]
    assert mapped(old).assets == () and mapped(old).measures["mean_ic"] == 0.1
    assert mapped(factor(2)).measures["mean_ic"] == 0.1
    assert mapped(factor(run_id="2026-02-30-bad")).created_at_basis == "not recorded"
    r = mapped(rule())
    assert r.kind == "rule_family" and r.family_id == "rule:f1"
    assert r.measures == {"p": 0.01, "q": 0.03, "annualised_excess": 0.12}
    assert r.evidence_path == "trials/a/trial.json"


@pytest.mark.parametrize(
    "row",
    [
        spine(verdict="Z"),
        factor(status="NO"),
        rule(status="NO"),
        {"schema": "Future"},
        {"schema": "AlphaTrialV1"},
    ],
)
def test_unmappable(row: Any) -> None:
    with pytest.raises((ValueError, KeyError, TypeError)):
        mapped(row)
