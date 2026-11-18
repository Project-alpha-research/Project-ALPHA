"""Prompt text and panel and ledger read counts for the ALPHA factor worker."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, Mock

import pandas as pd
import pytest

from tests.unit._rdagent_support import judge_namespace

UNIVERSE = "1 instruments, 0 later delisted declared; survivors-only selection"
SETTING = (
    "Binance USDT spot coins, daily bars: 1 instruments, 0 later delisted declared; survivors-only "
    "selection. History only: 2017-08-17..2020-12-31; exploration decisions: 2021-01-01.."
    "2023-12-24; panel ends 2023-12-31. 2024-01-01 onward is reserved and never available to "
    "this loop. "
    "Prefix-invariance checks at quarter ends and 2023-12-24 detect some look-ahead, not all. "
    "Daily, weekly (7-day) and monthly (28-day) holding/rebalance clocks are fixed in advance; "
    "only a weekly or monthly pass can become a candidate. exploratory, not admitted, "
    "not yet confirmed."
)
FUNDING = (
    " Futures funding inputs: $funding_sum, $funding_last, $funding_count. Missing funding stays "
    "NaN, never zero or forward-filled; only settlements known before the day's midnight UTC close "
    "are included. Funding factors rank only names with a funding row that day; outcomes remain "
    "spot returns."
)
PERMISSIONS = (
    "Closed families: volatility and beta. open families: VWAP distance; drawdown; futures "
    "funding; illiquidity; intraday return and gaps; past return (momentum or reversal); price "
    "near its high / range position; range and compression; return-volume relation; skewness and "
    "lottery returns; "
    "volume level and trend. A mechanism that belongs to none of the closed families is allowed. "
    "Session drift families are not offered because this 24/7 crypto venue's daily bars run from "
    "midnight to midnight, without an overnight trading break."
)
LEDGER_CONTEXT = (
    "Earlier context\nALPHA idea families (all runs; tries, best result, how they failed)\n"
    "- volatility and beta: 1 try; best volatility_28d (SCREEN_FAIL); 1 SCREEN_FAIL; "
    "failed tries in this idea family (volatility and beta): 1 of the limit 1\n"
    "These families have 1 or more failed tries and no candidate: volatility and beta. "
    "Do not propose another near-variant of them (a new window, skip or scaling of the same idea), "
    "including composites using ANY of these families; move to a different family with a different "
    "economic mechanism.\n"
    + PERMISSIONS
    + "\nALPHA trial ledger (all runs; exploratory, not admitted; 1 instruments, 0 later delisted "
    "declared; survivors-only selection)\n"
    "volatility_28d: SCREEN_FAIL; mean rank IC 0.01; q 0.9; run synthetic; failed tries in this "
    "idea family (volatility and beta): 1 of the limit 1"
)


@pytest.fixture
def run(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    (tmp_path / "panel").mkdir()
    (tmp_path / "panel/panel-receipt.json").write_text('{"instruments": {"BTCUSDT": {}}}')
    monkeypatch.setenv("ALPHA_FACTOR_RUN_DIR", str(tmp_path))
    monkeypatch.setenv("ALPHA_FACTOR_TRIAL_LEDGER", str(tmp_path / "trials.jsonl"))
    monkeypatch.setenv("ALPHA_FACTOR_FAMILY_SWITCH_AFTER", "1")
    return tmp_path


@pytest.mark.parametrize("funded,receipt", [(False, True), (True, False), (True, True)])
def test_rendered_setting_reads_panel_at_most_once(
    run: Path, monkeypatch: pytest.MonkeyPatch, funded: bool, receipt: bool
) -> None:
    panel = run / "factor_data/full/daily_pv.h5"
    panel.parent.mkdir(parents=True)
    panel.touch()
    if receipt:
        record = {"funding_sha256": "a" * 64} if funded else {}
        (panel.parents[1] / "prepare-receipt.json").write_text(json.dumps(record))
    names = ["$close"] + (["$funding_sum", "$funding_last", "$funding_count"] if funded else [])
    read_frame = Mock(return_value=pd.DataFrame(columns=names))
    store = MagicMock()
    storer = store.return_value.__enter__.return_value.get_storer.return_value
    storer.read_index.return_value = pd.Index(names)
    monkeypatch.setattr(pd, "read_hdf", read_frame)
    monkeypatch.setattr(pd, "HDFStore", store)

    scenario = judge_namespace()["AlphaFactorScenario"]()
    for _ in range(8):
        assert scenario.experiment_setting == SETTING + (FUNDING if funded else "")
    read_frame.assert_not_called()
    if funded and receipt:
        store.assert_not_called()
    else:
        store.assert_called_once_with(panel, mode="r")
        storer.read_index.assert_called_once_with("axis0")


def trial(name: str, digest: str) -> str:
    return (
        json.dumps(
            {
                "schema": "AlphaRdagentFactorTrialV1",
                "name": name,
                "status": "SCREEN_FAIL",
                "screen": {"mean_ic": 0.01},
                "q": 0.9,
                "run_id": "synthetic",
                "code_sha256": digest * 64,
            }
        )
        + "\n"
    )


def test_round_shares_one_ledger_parse_and_refreshes_next_round(
    run: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ledger = run / "trials.jsonl"
    first, second = trial("volatility_28d", "a"), trial("drawdown_28d", "b")
    ledger.write_text(first + '{"schema":')
    ns = judge_namespace()
    proposer = ns["AlphaFactorHypothesisGen"]()
    loads = json.loads
    payloads = {first.strip().encode(), second.strip().encode()}
    parsed: list[bytes] = []
    read_bytes = Path.read_bytes
    reads: list[Path] = []

    def count_loads(payload: str | bytes | bytearray, **kwargs: Any) -> Any:
        if isinstance(payload, bytes) and payload in payloads:
            parsed.append(payload)
        return loads(payload, **kwargs)

    def count_reads(path: Path) -> bytes:
        if path == ledger:
            reads.append(path)
        return read_bytes(path)

    def gen(self: Any, trace: Any, plan: Any) -> dict[str, Any]:
        self.prepare_context(trace)
        context = {"hypothesis_and_feedback": "Earlier context"}
        ns["append_ledger_context"](context, str(ledger), UNIVERSE, 0)
        return context

    monkeypatch.setattr(json, "loads", count_loads)
    monkeypatch.setattr(Path, "read_bytes", count_reads)
    monkeypatch.setattr(ns["QlibFactorHypothesisGen"], "gen", gen, raising=False)

    assert proposer.gen(None, None)["hypothesis_and_feedback"] == LEDGER_CONTEXT
    closed = ns["closed_families"]()
    assert closed == {"volatility and beta"}
    assert ns["known_families"]() == closed
    assert ns["family_permissions"](closed, include_counts=True) == (
        PERMISSIONS + "\nfailed tries in this idea family (volatility and beta): 1 of the limit 1"
    )
    ns["FAMILY_REFUSALS"].append("refused volatility")
    assert proposer.gen(None, None)["hypothesis_and_feedback"] == LEDGER_CONTEXT
    ns["FAMILY_REFUSALS"].clear()
    assert reads == [ledger]
    assert len(parsed) == 1

    # A subsequent proposal round reparses even when nothing was written.
    assert proposer.gen(None, None)["hypothesis_and_feedback"] == LEDGER_CONTEXT
    assert reads == [ledger] * 2
    assert len(parsed) == 2

    ledger.write_text(first)
    with ledger.open("a") as stream:
        stream.write(second)
    assert "drawdown_28d: SCREEN_FAIL" in proposer.gen(None, None)["hypothesis_and_feedback"]
    assert ns["closed_families"]() == {"volatility and beta", "drawdown"}
    assert reads == [ledger] * 3
    assert len(parsed) == 4


@pytest.mark.parametrize("changed", ["size", "mtime"])
def test_ledger_refreshes_within_round_when_file_changes(run: Path, changed: str) -> None:
    ledger = run / "trials.jsonl"
    first, second = trial("volatility_28d", "a"), trial("volatility_29d", "b")
    ledger.write_text(first)
    ns = judge_namespace()
    assert ns["known_families"]() == {"volatility and beta"}
    before = ledger.stat()
    if changed == "size":
        with ledger.open("a") as stream:
            stream.write(second)
        os.utime(ledger, ns=(before.st_atime_ns, before.st_mtime_ns))
    else:
        ledger.write_text(second)
        os.utime(ledger, ns=(before.st_atime_ns, before.st_mtime_ns + 1_000_000_000))

    context = {"hypothesis_and_feedback": ""}
    ns["append_ledger_context"](context, str(ledger), UNIVERSE, 0)
    assert "volatility_29d: SCREEN_FAIL" in context["hypothesis_and_feedback"]
