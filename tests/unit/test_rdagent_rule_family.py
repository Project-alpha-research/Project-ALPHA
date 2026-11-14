"""Synthetic snapshots and an independent next-open, pre-fill equity oracle."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any, BinaryIO

import numpy as np
import polars as pl
import pytest

from alpha_cli import _runner
from alpha_cli import rdagent_factor_eval as ev
from alpha_cli import rdagent_rule_family as rf
from alpha_core import ActionType, CorporateAction, DataError
from alpha_data.snapshot import create_snapshot
from alpha_data.store import ParquetStore


def fixture(root: Path, *, short: bool = False) -> tuple[Path, Path, dict[str, Any]]:
    data = root / "data"
    store = ParquetStore(data / "store")
    days = [datetime(2023, 1, 1, tzinfo=UTC) + timedelta(days=i) for i in range(370)]
    x = np.arange(len(days))
    closes = np.round(100 + 12 * np.sin(x / 9) + x / 30, 2)
    closes[363] = 70.0  # Force a final-session exit to pin the terminal post-fill resample.
    opens = np.round(closes + 0.7 * np.cos(x / 3), 2)
    frame = pl.DataFrame(
        {
            "ts": days,
            "open": opens,
            "close": closes,
            "high": np.maximum(opens, closes) + 2,
            "low": np.minimum(opens, closes) - 2,
            "volume": np.full(len(days), 100000.0),
        }
    )
    symbols = ["SPY", "BTC/USDT"] + (["SHORT"] if short else [])
    for symbol in symbols:
        store.write_bars(symbol, frame.head(20) if symbol == "SHORT" else frame)
    store.write_actions(
        "SPY",
        [
            CorporateAction(
                symbol="SPY",
                action_type=ActionType.DIVIDEND,
                ex_date=days[i].date(),
                pay_date=days[i + 2].date(),
                amount=1.25,
            )
            for i in (270, 366)
        ],
    )
    create_snapshot(
        store,
        data / "snapshots",
        "synthetic",
        symbols,
        source="synthetic",
        adapter_version="1",
        parser_version="1",
        created_at=datetime(2023, 1, 1, tzinfo=UTC),
    )
    spec = {
        "schema": "AlphaTrendFamilySpecV1",
        "family_id": "synthetic-trend",
        "written_before_any_result": True,
        "lookbacks_N": [20, 60],
        "instruments": {
            s: {
                "source": "data/snapshots/synthetic (test)",
                "cost": {"fee_bps": 1.0, "slippage_bps": 4.0},
                "periods_per_year": 365 if "/" in s else 252,
                "account": "MARGIN, leverage 1" if "/" in s else "CASH",
            }
            for s in symbols
        },
        "sizing": {"starting_cash": 100000000},
        "rule": {
            "rule_spec_template": {
                "version": 1,
                "name": "own-trend-N",
                "history": 251,
                "long_when": [
                    {
                        "left": {"source": "close"},
                        "op": ">",
                        "right": {"source": "close", "lag": "N"},
                    }
                ],
                "short_when": [],
            }
        },
        "disclosures": ["survivorship: synthetic only"],
    }
    path = root / "spec.json"
    path.write_bytes(ev.canonical(spec))
    return path, data, spec


def run(root: Path, *, short: bool = False) -> tuple[dict[str, Any], Path]:
    spec, data, _ = fixture(root, short=short)
    out = root / "run"
    result = rf.run_family(spec, ev.sha(spec.read_bytes()), data, out, root / "ledger.jsonl")
    return result, out


def oracle(
    frame: pl.DataFrame, symbol: str, lookback: int, units: float
) -> tuple[np.ndarray, np.ndarray]:
    """No engine/production calculation: close targets, next-open fills, pre-fill marks."""
    precision = 5 if "/" in symbol else 2
    opening = frame["open"].to_numpy()
    close = frame["close"].to_numpy()
    bid, ask = np.round(opening * 0.9996, precision), np.round(opening * 1.0004, precision)
    curves = []
    for hold in (False, True):
        cash, position, dividend = 100000000.0, 0.0, 0.0
        curve = []
        for i in range(251, 365):
            if symbol == "SPY" and i == 270:
                dividend = position * 1.25
            if symbol == "SPY" and i == 272:
                cash += dividend
            curve.append(cash + position * bid[i])
            target = units if hold or close[i - 1] > close[i - 1 - lookback] else 0.0
            quantity = target - position
            price = ask[i] if quantity > 0 else bid[i]
            cash -= quantity * price + abs(quantity) * price * 0.0001
            position = target
            if i == 364:
                curve[-1] = cash + position * bid[i]
        curves.append(np.asarray(curve))
    return curves[0], curves[1]


def test_engine_oracle_cutoff_hold_and_same_sizing(tmp_path: Path) -> None:
    family, out = run(tmp_path)
    assert len(family["trials"]) == 4
    for trial in family["trials"]:
        assert trial["outcome"] != "INVALID", trial
        symbol, n = trial["instrument"], trial["lookback_N"]
        folder = out / "trials" / f"{symbol.replace('/', '-')}-N{n}"
        series = pl.read_parquet(folder / "series.parquet")
        raw = ParquetStore(tmp_path / "data/store").read_bars(symbol)
        units = np.floor(1000000 / raw["open"][251])
        assert trial["units"] == units
        trend, hold = oracle(raw, symbol, n, units)
        # USD PnL and commissions round to cents; < 5 cents / $1m per return.
        v = units * np.round(raw["open"].to_numpy()[251:365] * 0.9996, 5 if "/" in symbol else 2)
        np.testing.assert_allclose(series["position_value"], v, rtol=0, atol=1e-9)
        for key, expected in (
            ("r_trend", np.diff(trend) / v[:-1]),
            ("r_hold", np.diff(hold) / v[:-1]),
            ("e", (np.diff(trend) - np.diff(hold)) / v[:-1]),
        ):
            assert series[key][0] is None
            np.testing.assert_allclose(series[key].to_numpy()[1:], expected, rtol=0, atol=5e-8)
        assert series["ts"][0] == raw["ts"][251]
        assert series["ts"][-1].date() == date(2023, 12, 31)
        hold_fills = pl.read_parquet(folder / "hold/fills.parquet")
        assert hold_fills.height == 1
        assert hold_fills["ts"][0] == series["ts"][0]
        if n == 20:
            trend_fills = pl.read_parquet(folder / "trend/fills.parquet")
            assert trend_fills["ts"][-1] == series["ts"][-1]
            assert trend_fills["side"][-1] == "SELL"
        for book in ("trend", "hold"):
            fills = pl.read_parquet(folder / book / "fills.parquet")
            assert all(t.date() < date(2024, 1, 1) for t in fills["ts"])
        assert trial["measures"]["hold"]["dividends_credited"] == (
            units * 1.25 if symbol == "SPY" else 0
        )
    rows = ev._read_ledger(tmp_path / "ledger.jsonl")
    assert [r["trial_index"] for r in rows] == [1, 2, 3, 4]
    for row, trial in zip(rows, family["trials"], strict=True):
        assert row["p"] == trial["p"] and row["q"] == trial["q"]
        assert row["family_size"] == row["total_trials"] == 4
        assert ev.sha((out / row["evidence"]["trial"]).read_bytes()) == row["evidence"]["sha256"]


def test_invalid_trials_continue_and_defaults_are_warnings(tmp_path: Path) -> None:
    path, data, spec = fixture(tmp_path, short=True)
    spec["schema"] = "future"
    spec["written_before_any_result"] = False
    spec["instruments"]["SPY"] = {"source": "data/snapshots/synthetic"}
    path.write_bytes(ev.canonical(spec))
    result = rf.run_family(
        path, ev.sha(path.read_bytes()), data, tmp_path / "run", tmp_path / "ledger"
    )
    assert len(result["trials"]) == 6
    invalid = [r for r in result["trials"] if r["outcome"] == "INVALID"]
    assert len(invalid) == 2 and all(r["p"] == 1 and "error" in r for r in invalid)
    warnings = " ".join(result["warnings"])
    for text in (
        "schema",
        "written_before_any_result",
        "fee_bps",
        "slippage_bps",
        "periods_per_year",
        "account",
    ):
        assert text in warnings
    assert all(r["warnings"] == result["warnings"] for r in ev._read_ledger(tmp_path / "ledger"))


def test_integrity_refusal_writes_nothing(tmp_path: Path) -> None:
    path, data, _ = fixture(tmp_path)
    before = sorted(tmp_path.rglob("*"))
    with pytest.raises(DataError, match="sha256"):
        rf.run_family(path, "0" * 64, data, tmp_path / "run", tmp_path / "ledger")
    assert sorted(tmp_path.rglob("*")) == before
    with pytest.raises(DataError, match="exist"):
        rf.run_family(path, ev.sha(path.read_bytes()), data, data, tmp_path / "ledger")
    with pytest.raises(DataError, match="git"):
        rf.run_family(
            path, ev.sha(path.read_bytes()), data, Path.cwd() / "bad-run", tmp_path / "ledger"
        )
    with pytest.raises(DataError, match="git"):
        rf.run_family(
            path, ev.sha(path.read_bytes()), data, tmp_path / "run", Path.cwd() / "bad-ledger"
        )
    assert sorted(tmp_path.rglob("*")) == before


@pytest.mark.parametrize(
    ("mean", "q", "expected"),
    [
        (1, 0.09, "SUPPORT"),
        (-1, 0.09, "CONTRADICTION"),
        (1, 0.1, "INSUFFICIENT"),
        (0, 0.01, "INSUFFICIENT"),
    ],
)
def test_classification(mean: float, q: float, expected: str) -> None:
    assert rf.classify(mean, q) == expected


@pytest.mark.parametrize(
    ("outcomes", "expected"),
    [
        (["SUPPORT"], "support within scope"),
        (["CONTRADICTION"], "contradiction"),
        (["SUPPORT", "CONTRADICTION"], "mixed"),
        (["INVALID", "INSUFFICIENT"], "insufficient evidence"),
    ],
)
def test_verdict(outcomes: list[str], expected: str) -> None:
    assert rf.family_verdict(outcomes) == expected


def test_determinism(tmp_path: Path) -> None:
    path, data, _ = fixture(tmp_path)
    outputs = []
    for name in ("a", "b"):
        parent = tmp_path / name
        parent.mkdir()
        out = parent / "run"
        rf.run_family(path, ev.sha(path.read_bytes()), data, out, parent / "ledger")
        outputs.append(
            {str(p.relative_to(out)): p.read_bytes() for p in out.rglob("*") if p.is_file()}
        )
    for output in outputs:
        receipt = json.loads(output.pop("receipt.json"))
        receipt.pop("started_at")
        receipt.pop("ended_at")
        output["receipt.json"] = ev.canonical(receipt)
    assert outputs[0] == outputs[1]


def test_cli_appends_one_complete_block_after_mixed_history(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from tests.unit.test_rdagent_factor_eval import rule_row

    path, data, spec = fixture(tmp_path)
    # Four lookbacks across seven declared instruments, including five missing snapshots.
    # Missing data is still a counted trial, never a smaller statistical family.
    spec["lookbacks_N"] = [20, 60, 120, 250]
    for i in range(5):
        spec["instruments"][f"MISSING{i}"] = {"source": "data/snapshots/absent"}
    path.write_bytes(ev.canonical(spec))
    ledger, out = tmp_path / "ledger", tmp_path / "run"
    history = []
    for index, schema in enumerate(("AlphaRdagentFactorTrialV1", "AlphaRdagentFactorTrialV2"), 1):
        row = {**rule_row(index), "schema": schema, "status": "FAILED", "stage": "none"}
        row.pop("family_id")
        history.append(row)
    history.append(rule_row(3))
    original = b"".join(ev.canonical(r) for r in history)
    ledger.write_bytes(original)
    opened = Path.open
    writes = []

    class AppendObserver:
        def __init__(self, stream: BinaryIO) -> None:
            self.stream = stream

        def __enter__(self) -> AppendObserver:
            self.stream.__enter__()
            return self

        def __exit__(self, *args: Any) -> None:
            self.stream.__exit__(*args)

        def write(self, block: bytes) -> int:
            complete = json.loads((out / "family-result.json").read_bytes())
            assert len(complete["trials"]) == 28
            assert len(block.splitlines()) == 28
            writes.append(block)
            return self.stream.write(block)

        def fileno(self) -> int:
            return self.stream.fileno()

    def observe(self: Path, mode: str = "r", *args: Any, **kwargs: Any) -> Any:
        if self == ledger and mode == "ab":
            return AppendObserver(opened(self, "ab", *args, **kwargs))
        return opened(self, mode, *args, **kwargs)

    monkeypatch.setattr(Path, "open", observe)
    monkeypatch.setattr(
        "sys.argv",
        [
            "rdagent_rule_family",
            "run",
            "--spec",
            str(path),
            "--spec-sha256",
            ev.sha(path.read_bytes()),
            "--data-dir",
            str(data),
            "--run-dir",
            str(out),
            "--ledger",
            str(ledger),
        ],
    )
    rf.main()
    rows = ev._read_ledger(ledger)
    assert len(writes) == 1 and ledger.read_bytes() == original + writes[0]
    assert [r["trial_index"] for r in rows] == list(range(1, 32))
    assert all(r["family_size"] == 28 and r["total_trials"] == 31 for r in rows[3:])
    result = json.loads((out / "family-result.json").read_bytes())
    assert result["counts"]["INVALID"] == 20
    # Independent BH computation excludes all three pre-existing trials.
    p = np.array([r["p"] for r in rows[3:]])
    order = np.argsort(p)
    expected = np.empty(28)
    expected[order] = np.minimum(
        1, np.minimum.accumulate((p[order] * 28 / np.arange(1, 29))[::-1])[::-1]
    )
    np.testing.assert_allclose([r["q"] for r in rows[3:]], expected)
    receipt = json.loads((out / "receipt.json").read_bytes())
    assert receipt["ledger_trial_indices"] == list(range(4, 32))


@pytest.mark.parametrize("kind", ["bars", "dividends"])
def test_loader_escape_aborts_before_the_ledger(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, kind: str
) -> None:
    path, data, _ = fixture(tmp_path)
    original = getattr(_runner, "load_" + kind)

    def escaped(symbol: str, **kwargs: Any) -> Any:
        assert kwargs["as_of"] == datetime(2023, 12, 31, 23, 59, 59, tzinfo=UTC)
        value = original(symbol, **kwargs)
        if kind == "bars":
            bars, snapshot_id = value
            return [
                *bars,
                bars[-1].model_copy(update={"ts": datetime(2024, 1, 1, tzinfo=UTC)}),
            ], snapshot_id
        return [
            *value,
            CorporateAction(
                symbol=symbol, action_type=ActionType.DIVIDEND, ex_date=date(2024, 1, 1), amount=1
            ),
        ]

    monkeypatch.setattr(_runner, "load_" + kind, escaped)
    # A point-in-time leak is an integrity failure, not a trial outcome: the run aborts.
    with pytest.raises(rf.ReservedDataError, match="reserved"):
        rf.run_family(path, ev.sha(path.read_bytes()), data, tmp_path / "run", tmp_path / "ledger")
    assert not list((tmp_path / "run").rglob("*.parquet"))
    assert not (tmp_path / "ledger").exists() or not (tmp_path / "ledger").read_bytes()


def test_primary_statistics_and_execution_descriptions(tmp_path: Path) -> None:
    from alpha_validation.bootstrap import block_bootstrap_ci
    from alpha_validation.proportion import autocorrelation_effective_size

    family, out = run(tmp_path)
    digest = ev.sha((out / "spec.json").read_bytes())
    for trial in family["trials"]:
        symbol, n = trial["instrument"], trial["lookback_N"]
        folder = out / "trials" / f"{symbol.replace('/', '-')}-N{n}"
        frame = pl.read_parquet(folder / "series.parquet")
        excess = frame["e"].drop_nulls().to_numpy()
        metrics = trial["measures"]
        ppy = 365 if "/" in symbol else 252
        sd = float(np.std(excess, ddof=1))
        se = sd / np.sqrt(autocorrelation_effective_size(excess))
        assert metrics["annualised_excess"] == pytest.approx(float(excess.mean()) * ppy)
        assert metrics["se_annual"] == pytest.approx(se * ppy)
        assert metrics["mde_80_annual"] == pytest.approx(2.8 * se * ppy)
        assert metrics["n"] == len(excess)
        seed = int(ev.sha((digest + symbol + str(n)).encode())[:8], 16)
        ci = block_bootstrap_ci(excess, lambda x: float(np.mean(x)), n_resamples=2000, seed=seed)
        assert metrics["ci_95_annual"] == {"lower": ci.lower * ppy, "upper": ci.upper * ppy}
        assert metrics["time_in_market"] == pytest.approx(frame["in_market"].mean())
        mean_position_value = frame["position_value"].mean()
        assert isinstance(mean_position_value, float)
        for book in ("trend", "hold"):
            fills = pl.read_parquet(folder / book / "fills.parquet")
            years = len(excess) / ppy
            assert metrics[book]["trade_count"] == fills.height
            assert metrics[book]["round_trips_per_year"] == pytest.approx(
                fills.filter(pl.col("side") == "SELL").height / years
            )
            notional = (fills["quantity"] * fills["price"]).sum()
            assert isinstance(notional, (int, float))
            assert metrics[book]["annual_turnover"] == pytest.approx(
                notional / mean_position_value / years
            )
            raw = ParquetStore(tmp_path / "data/store").read_bars(symbol)
            opens = dict(zip(raw["ts"], raw["open"], strict=True))
            fees = sum(
                round(f["quantity"] * f["price"] * 0.0001, 8 if "/" in symbol else 2)
                for f in fills.iter_rows(named=True)
            )
            slippage = sum(
                f["quantity"] * (f["price"] - opens[f["ts"]]) * (1 if f["side"] == "BUY" else -1)
                for f in fills.iter_rows(named=True)
            )
            expected_cost = (fees + slippage) / mean_position_value / years
            assert metrics[book]["annual_cost"] == pytest.approx(expected_cost, rel=0, abs=1e-12)


@pytest.mark.parametrize("failure", ["rejected", "reconciliation"])
def test_engine_failure_is_recorded_loudly(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure: str
) -> None:
    from dataclasses import replace

    from alpha_backtest import engine

    path, data, _ = fixture(tmp_path)
    original = engine.run_backtest

    def broken(*args: Any, **kwargs: Any) -> Any:
        result = original(*args, **kwargs)
        if failure == "rejected":
            return replace(result, rejected=1)
        return replace(
            result, equity_curve=[(ts, equity + 100) for ts, equity in result.equity_curve]
        )

    monkeypatch.setattr(engine, "run_backtest", broken)
    result = rf.run_family(
        path, ev.sha(path.read_bytes()), data, tmp_path / "run", tmp_path / "ledger"
    )
    for trial in result["trials"]:
        assert trial["outcome"] == "INVALID" and trial["p"] == trial["q"] == 1
        assert ("rejected" if failure == "rejected" else "reconcile") in trial["error"]
    assert len(ev._read_ledger(tmp_path / "ledger")) == 4


def test_relative_paths_and_new_parents_are_not_extra_refusals(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path, data, _ = fixture(tmp_path)
    monkeypatch.chdir(tmp_path)
    result = rf.run_family(
        path,
        ev.sha(path.read_bytes()),
        data,
        Path("new/runs/study"),
        Path("new/ledger/trials.jsonl"),
    )
    assert len(result["trials"]) == 4
    assert len(ev._read_ledger(tmp_path / "new/ledger/trials.jsonl")) == 4
