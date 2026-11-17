"""Legacy universe labels, rename continuity and precise model-facing figures."""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any

import polars as pl
import pytest

from alpha_cli import _rdagent_identity as identity
from alpha_cli import _rdagent_universe as universes
from alpha_cli._rdagent_clocks import clock_feedback
from alpha_cli.spine.trial_record import map_row
from alpha_core import DataError
from tests.unit.test_rdagent_identity_breaks import freeze_panel, jump_panel
from tests.unit.test_trial_record import factor


def renamed(**changes: Any) -> dict[str, Any]:
    return {
        "instrument": "C0",
        "new_from": "2021-01-12",
        "reason": "renamed",
        "continues_as": "NEW",
        **changes,
    }


def rename_panel() -> pl.DataFrame:
    panel = jump_panel(10, 1000)
    return panel.with_columns(
        pl.when((pl.col("instrument") == "C0") & (pl.col("date") >= date(2021, 1, 12)))
        .then(pl.lit("NEW"))
        .otherwise(pl.col("instrument"))
        .alias("instrument")
    )


@pytest.mark.parametrize(
    "text,label",
    [
        ("141 instruments, 66 later delisted", "includes-delisted"),
        ("141 instruments, 66 instruments later delisted", "includes-delisted"),
        ("15 coins chosen from today's survivors; delisted coins absent", "survivor-universe"),
        ("survivors only", "survivor-universe"),
        # the real rule-trial rows' wording (a text list in AlphaRuleTrialV1)
        ("survivorship: BTC and ETH are survivors chosen today", "survivor-universe"),
        ("0 later delisted", "universe-not-recorded"),
        ("unknown selection", "universe-not-recorded"),
    ],
)
def test_old_row_universe_derived_without_mutation(tmp_path: Path, text: str, label: str) -> None:
    row = factor(survivorship=text)
    before = row.copy()
    record = map_row("rdagent", tmp_path / "ledger", 1, row)
    assert set(record.labels) & {
        "includes-delisted",
        "survivor-universe",
        "universe-not-recorded",
    } == {label}
    assert row == before


def test_rename_freeze_continuous_series_and_join_receipt(tmp_path: Path) -> None:
    receipt, panel = freeze_panel(tmp_path, rename_panel(), [renamed(ratio=1000)])
    coin = panel.filter(pl.col("instrument") == "C0")
    assert coin["close"].to_list() == [10.0, 10.0]
    assert coin["volume"].to_list() == [1.0, 1000.0]
    assert coin["quote_volume"].to_list() == [10.0, 10.0]
    assert "NEW" not in panel["instrument"].to_list()
    assert receipt["identity_joins"] == [renamed(ratio=1000)]
    assert receipt["instruments"]["C0"]["missing_days"] == 10


def test_rename_default_ratio_and_future_poison() -> None:
    bars = rename_panel()
    boundary = date(2021, 1, 12)
    adjusted, applied = identity.relabel(bars, [renamed()])
    assert applied == [renamed(ratio=1)]
    poison = bars.with_columns(
        pl.when(pl.col("date") >= boundary)
        .then(pl.col("close") * 17)
        .otherwise(pl.col("close"))
        .alias("close")
    )
    changed, _ = identity.relabel(poison, [renamed()])
    past = pl.col("date") < boundary
    assert adjusted.filter(past).equals(bars.filter(past))
    assert changed.filter(past).equals(adjusted.filter(past))
    assert not changed.equals(adjusted)
    assert adjusted.filter(pl.col("instrument") == "C0")["close"].to_list() == [10.0, 10000.0]


def test_rename_overlap_refused() -> None:
    bars = rename_panel()
    overlap = bars.filter(pl.col("instrument") == "NEW").with_columns(
        pl.lit("C0").alias("instrument")
    )
    with pytest.raises(DataError, match="overlap.*C0.*NEW"):
        identity.relabel(pl.concat([bars, overlap]), [renamed()])


def test_rename_missing_successor_names_instrument(tmp_path: Path) -> None:
    with pytest.raises(DataError, match="NEW.*(?:missing|absent)"):
        freeze_panel(tmp_path, jump_panel(10, 1), [renamed()])


def test_rename_successor_must_belong_to_universe() -> None:
    with pytest.raises(DataError, match="NEW.*universe"):
        universes.validate(
            {**universes.DEFAULT, "instruments": ["C0"], "identity_breaks": [renamed()]}
        )


@pytest.mark.parametrize("ratio", [0, -1, True, "1", float("inf"), float("nan")])
def test_rename_invalid_ratio_refused(ratio: Any) -> None:
    with pytest.raises(DataError, match="ratio"):
        identity.validate_breaks([renamed(ratio=ratio)], "all-in-store")


def test_identity_singular_and_model_figures() -> None:
    assert (
        identity.disclosure([{"instrument": "C0"}])
        == "1 ticker was split at declared identity breaks."
    )
    row = factor(version=2, status="SCREEN_FAIL", screen={"mean_ic": 0.0000123456}, replay={})
    text = clock_feedback(row)
    assert "None" not in text and "not available" in text
    assert "1.235e-05" in text


def test_writeoff_sentence_names_only_replayed_clocks() -> None:
    from alpha_cli._rdagent_stability import writeoff_summary

    row = {
        "name": "idea",
        "clocks": {
            "daily": {"replay": {}},
            "weekly": {"replay": {"haircuts_applied": 1, "writeoff_instruments": ["C0"]}},
            "monthly": {"replay": {}},
        },
    }
    count, message = writeoff_summary(row, 0.3)
    assert count == 1
    assert "weekly" in message and "daily" not in message and "monthly" not in message
    assert "1 held position was written off" in message


def test_writeoff_sentence_skips_errored_and_unreplayed_clocks() -> None:
    from alpha_cli._rdagent_stability import writeoff_summary

    trial = {"replay": {"haircuts_applied": 2, "writeoff_instruments": ["C0", "C1"]}}
    row: dict[str, Any] = {
        "name": "idea",
        "clocks": {"daily": {"replay": {"error": "ValueError: x"}}, "weekly": trial},
    }
    count, message = writeoff_summary(row, 0.3)
    assert count == 2 and "replayed weekly holding clock;" in message and "daily" not in message
    row["clocks"]["monthly"] = trial
    assert "replayed weekly and monthly holding clocks;" in writeoff_summary(row, 0.3)[1]
    none = {"name": "idea", "clocks": {"daily": {"replay": {}}}}
    assert writeoff_summary(none, 0.3) == (
        0,
        "idea: no holding clock was replayed, so nothing was written off.",
    )


def test_rename_refuses_old_bars_on_or_after_new_from() -> None:
    bars = rename_panel()
    late = renamed(new_from="2021-01-01")  # the old series still has its bar on the 1st
    with pytest.raises(DataError, match="overlap.*C0.*on or after new_from 2021-01-01.*NEW"):
        identity.relabel(bars, [late])
