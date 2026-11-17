"""Frozen-data, invalid-trial and ledger regressions for the third loop fix-up."""

from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import numpy as np
import polars as pl
import pytest
from typer.testing import CliRunner

from alpha_cli import _rdagent_identity as identity
from alpha_cli import _rdagent_judge as judge
from alpha_cli import _rdagent_membership as membership
from alpha_cli import rdagent_factor_eval as ev
from alpha_cli._rdagent_clocks import clock_feedback
from alpha_cli.ledger_cmds import _evidence, ledger_app
from alpha_cli.spine.trial_reader import LedgerSource, read_ledgers, trials_for_deflation
from alpha_cli.spine.trial_record import map_row
from alpha_core import DataError
from tests.unit.test_rdagent_factor_eval import fixture
from tests.unit.test_rdagent_gapped_universe import walk_panel
from tests.unit.test_rdagent_identity_breaks import freeze_panel, jump_panel
from tests.unit.test_trial_record import factor


def rescale(day: str = "2021-01-12", ratio: float = 1000) -> dict[str, Any]:
    return {"instrument": "C0", "new_from": day, "reason": "redenominated", "ratio": ratio}


def test_redenomination_freeze_is_continuous_and_receipted(tmp_path: Path) -> None:
    receipt, panel = freeze_panel(tmp_path, jump_panel(10, 1000), [rescale()])
    coin = panel.filter(pl.col("instrument") == "C0")
    assert coin["close"].to_list() == [10, 10]
    assert coin["volume"].to_list() == [1, 1000]
    assert coin["quote_volume"].to_list() == [10, 10]
    assert panel["instrument"].n_unique() == 3
    assert receipt["identity_rescales"] == [rescale()]
    assert receipt["identity_breaks"] == []


@pytest.mark.parametrize("ratio", [None, 0, -1, True, "1000", float("inf"), float("nan")])
def test_redenomination_requires_positive_finite_ratio(ratio: Any) -> None:
    entry = rescale()
    if ratio is None:
        entry.pop("ratio")
    else:
        entry["ratio"] = ratio
    with pytest.raises(DataError, match="redenominated.*ratio") as raised:
        identity.validate_breaks([entry], ["C0"])
    # The direction must be unambiguous: new units per old, so later prices are divided by it.
    assert "C0" in str(raised.value)
    assert "new price units per old unit" in str(raised.value)
    assert "divided by" in str(raised.value)


def test_rescale_holds_position_and_future_poison_changes_no_past() -> None:
    bars = walk_panel()
    boundary = date(2021, 2, 10)
    selected = (pl.col("instrument") == "C0") & (pl.col("date") >= boundary)
    raw = bars.with_columns(
        [
            pl.when(selected).then(pl.col(c) * 1000).otherwise(pl.col(c)).alias(c)
            for c in judge.PRICE_COLUMNS
        ]
    )
    adjusted, _ = identity.relabel(raw, [rescale(boundary.isoformat())])
    assert adjusted.filter(pl.col("date") < boundary).equals(bars.filter(pl.col("date") < boundary))
    assert adjusted["instrument"].n_unique() == bars["instrument"].n_unique()
    account = membership.Account(["C0"], fee_bps=0, slippage_bps=0)
    coin = adjusted.filter(pl.col("instrument") == "C0")
    account.trade(0, 1, coin["close"][0], coin["date"][0], "open")
    for day, close in coin.select("date", "close").iter_rows():
        account.observe(day, np.array([close]))
    assert account.quantities[0] == 1 and account.haircuts == 0
    days = [date(2021, 1, 1) + timedelta(days=i) for i in range(70)]
    signals = np.tile(np.arange(9.0), (70, 1))
    signals[:, 0] = 20.0  # Poison a held name, so the future change has power.
    outputs: list[dict[str, Any]] = []
    for panel in (raw, adjusted):
        series: dict[str, Any] = {}
        judge.replay(panel, signals, days, 1, gap_policy=True, series=series)
        outputs.append(series)
    for key in ("events", "positions"):
        assert [r for r in outputs[0][key] if r["date"] < boundary] == [
            r for r in outputs[1][key] if r["date"] < boundary
        ]
    assert [p for p in outputs[0]["periods"] if p.exit_ts.date() < boundary] == [
        p for p in outputs[1]["periods"] if p.exit_ts.date() < boundary
    ]
    assert outputs[0]["positions"] != outputs[1]["positions"]


@pytest.mark.parametrize("status", ["LOOKAHEAD", "UNSTABLE"])
def test_invalid_trials_keep_counts_reason_and_have_no_lead(tmp_path: Path, status: str) -> None:
    run = tmp_path / "run"
    path = fixture(run)
    request = json.loads(path.read_text())
    request["factors"][0].update(
        status=status,
        lookahead={
            "status": status,
            "first_mismatch": {
                "cut": "2021-03-31",
                "date": "2021-03-01",
                "instrument": "C0USDT",
                "absolute_difference": 0.25,
                "reason": "value changed",
            },
        },
    )
    path.write_text(json.dumps(request))
    ledger = tmp_path / "ledger"
    result = ev.evaluate(run, path, run / "result.json", ledger)
    assert result["lead_factor"] is None
    assert result["family_size"] == 3 and result["total_trials"] == 1
    snapshot = read_ledgers([LedgerSource("rdagent", str(ledger))])
    assert not snapshot.unknown
    record = snapshot.records[0]
    assert record.outcome == "invalid"
    assert record.reason and "2021-03-01" in record.reason and "0.25" in record.reason
    assert "C0USDT" in result["feedback_text"]
    if status == "UNSTABLE":
        assert "different answers on the same data" in result["feedback_text"]
    assert trials_for_deflation(snapshot, "rdagent-factors")["all_trials"] == 3
    assert ev._read_ledger(ledger)[0]["status"] == status
    output = CliRunner().invoke(ledger_app, ["list", "--rdagent-ledger", str(ledger)])
    assert output.exit_code == 0 and "0.25" in output.output


def test_evidence_resolves_recorded_run_identity(tmp_path: Path) -> None:
    root = tmp_path / "runs"
    ledger = root / "ledger/trials.jsonl"
    ledger.parent.mkdir(parents=True)
    run = root / "human-folder"
    run.mkdir()
    (run / "run-identity.json").write_text(json.dumps({"run_id": "recorded-id"}))
    (run / "series.json").write_text("evidence")
    row = factor(run_id="recorded-id", evidence={"series_manifest": "series.json"})
    assert _evidence(map_row("rdagent", ledger, 1, row), tmp_path)["evidence_found"]


@pytest.mark.parametrize(
    "other", ["not json", "[]", json.dumps({"other": 1}), json.dumps({"run_id": 7})]
)
def test_evidence_lookup_ignores_unrelated_unreadable_run_identities(
    tmp_path: Path, other: str
) -> None:
    """An odd identity file in some other run folder must not break every evidence lookup."""
    root = tmp_path / "runs"
    ledger = root / "ledger/trials.jsonl"
    ledger.parent.mkdir(parents=True)
    run = root / "human-folder"
    run.mkdir()
    (run / "run-identity.json").write_text(json.dumps({"run_id": "recorded-id"}))
    (run / "series.json").write_text("evidence")
    unrelated = root / "an-unrelated-run"
    unrelated.mkdir()
    (unrelated / "run-identity.json").write_text(other)
    row = factor(run_id="recorded-id", evidence={"series_manifest": "series.json"})
    assert _evidence(map_row("rdagent", ledger, 1, row), tmp_path)["evidence_found"]


@pytest.mark.parametrize("includes", [True, False, None])
def test_structured_universe_label(tmp_path: Path, includes: bool | None) -> None:
    row = factor()
    if includes is not None:
        row["universe_includes_delisted"] = includes
    record = map_row("rdagent", tmp_path / "ledger", 1, row)
    assert ("includes-delisted" in record.labels) == (includes is True)
    assert ("survivor-universe" in record.labels) == (includes is not True)


def test_absent_optional_source_is_quiet(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ALPHA_DATA_DIR", str(tmp_path / "data"))
    ledger = tmp_path / "ledger"
    ledger.write_text(json.dumps(factor()) + "\n")
    output = CliRunner().invoke(ledger_app, ["summary", "--rdagent-ledger", str(ledger)])
    assert output.exit_code == 0
    assert "ledger file not found" not in output.output
    assert f"rdagent: read {ledger}" in output.output


def test_failed_screen_does_not_print_unused_spread() -> None:
    row = factor(version=2, status="SCREEN_FAIL", replay={}, screen={})
    row["spread"] = {"status": "FAIL"}  # no figures should even be read
    assert "top third" not in clock_feedback(row)


def test_replay_output_names_missing_rank_observations() -> None:
    days = [date(2021, 1, 1) + timedelta(days=i) for i in range(50)]
    scores = np.tile(np.arange(9.0), (50, 1))
    scores[:, 0] = np.nan
    metrics, _ = judge.replay(walk_panel(), scores, days, 1, clock="weekly", gap_policy=True)
    assert "missing_coin_days" not in metrics
    assert metrics["unrankable_instrument_rebalances"] == metrics["rebalances"]


def test_evaluator_records_actual_universe_and_writeoff_names(tmp_path: Path) -> None:
    run = tmp_path / "run"
    path = fixture(run)
    _, bars, _, _ = ev._inputs(run, path)
    bars = bars.filter(
        ~((pl.col("instrument") == "C13USDT") & (pl.col("date") >= date(2022, 1, 1)))
    )
    bars.write_parquet(run / "panel/panel.parquet")
    values = pl.read_parquet(run / "factors.parquet")
    held_before_end = (pl.col("instrument") == "C13USDT") & pl.col("date").is_between(
        date(2021, 12, 20), date(2021, 12, 31)
    )
    values.with_columns(
        pl.when(held_before_end).then(1.0).otherwise(pl.col("factor")).alias("factor")
    ).write_parquet(run / "factors.parquet")
    from alpha_cli import _rdagent_universe as universes

    spec = {**universes.DEFAULT, "survivorship": "15 instruments, 1 later delisted"}
    (run / "panel/universe.json").write_bytes(judge.canonical(spec))
    receipt = {
        **membership.panel_summary(bars),
        "panel_sha256": judge.sha((run / "panel/panel.parquet").read_bytes()),
        "universe_sha256": judge.sha(judge.canonical(spec)),
    }
    (run / "panel/panel-receipt.json").write_text(json.dumps(receipt))
    result = ev.evaluate(run, path, run / "result.json", tmp_path / "ledger")
    row = result["factors"][0]
    assert row["universe_includes_delisted"] is True
    assert "15 instruments, 1 later delisted" in result["feedback_text"]
    assert row["writeoff_count"] > 0
    assert "C13USDT" in row["writeoff_message"]
    assert "assuming a 30% loss" in row["writeoff_message"]
    assert row["writeoff_message"] in result["feedback_text"]


def test_writeoff_names_are_bounded_and_legacy_replay_name_stays_readable() -> None:
    from alpha_cli._rdagent_stability import replay_output, writeoff_summary

    old = {"missing_coin_days": 7}
    assert replay_output(old) == {"unrankable_instrument_rebalances": 7}
    assert old == {"missing_coin_days": 7}
    row = {
        "name": "test",
        "clocks": {
            "weekly": {
                "replay": {
                    "haircuts_applied": 9,
                    "writeoff_instruments": [f"C{i}" for i in range(7)],
                }
            }
        },
    }
    count, message = writeoff_summary(row, membership.DELISTING_HAIRCUT)
    assert count == 9
    assert "C0, C1, C2, C3, C4 and 2 more" in message
    assert "C5" not in message and "C6" not in message


def test_missing_evidence_still_refuses_path_traversal(tmp_path: Path) -> None:
    from alpha_cli.spine.errors import SpineError

    root = tmp_path / "runs"
    ledger = root / "ledger/trials.jsonl"
    ledger.parent.mkdir(parents=True)
    row = factor(run_id="missing-run", evidence={"series_manifest": "../../outside.json"})
    with pytest.raises(SpineError, match="escapes"):
        _evidence(map_row("rdagent", ledger, 1, row), tmp_path)


def test_universe_text_counts_pairs_not_split_series() -> None:
    """A reused ticker adds a price series, not a pair: 141 pairs stay 141 in the text."""
    from alpha_cli import _rdagent_universe as universes

    spec = {"survivorship": "3 pairs chosen by listing date, 1 later delisted"}
    split = universes.disclosure(spec, {"instruments": {"A": {}, "A~2": {}, "B": {}, "C": {}}})
    plain = universes.disclosure(spec, {"instruments": {"A": {}, "B": {}, "C": {}}})
    assert split["universe_text"].startswith(
        "3 instruments (4 price series after 1 ticker split), 1 later delisted"
    )
    assert plain["universe_text"].startswith("3 instruments, 1 later delisted")
    assert split["universe_includes_delisted"] is plain["universe_includes_delisted"] is True
