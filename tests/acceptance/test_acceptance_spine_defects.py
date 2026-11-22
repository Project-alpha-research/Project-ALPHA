"""Regression cases promoted from the 2026-09-28 agentic benchmark (tools/alpha-eval).

Ported from the old `alpha validate` command. P09: malformed provider bars become a typed error
of `alpha test` before any run is published. P02: an unaffordable CASH buy is suppressed before
venue submission and disclosed; it runs on the engine that stays (`_runner`, `_gauntlet`,
`write_validation_run`), because `alpha test` sizes all-in and resizes a too-large entry instead.
A third case checks that `alpha test` discloses those resized entries and sends none to the venue.
"""

from __future__ import annotations

import json
from dataclasses import asdict
from datetime import UTC, date, datetime
from pathlib import Path

import numpy as np
import polars as pl
import pytest
from typer.testing import CliRunner

from alpha_cli import _gauntlet, _runner
from alpha_cli.main import app
from alpha_cli.spine import reserve
from alpha_cli.validate_cmds import write_validation_run
from alpha_data.store import ParquetStore

_QUICK = ["--quick", "--no-diagnose", "--json"]
_SMALL = _gauntlet.GauntletParams(
    seed=7, tier1_paths=50, tier2_paths=8, tier3_paths=8, n_resamples=100, max_workers=1
)


def _frame(closes: np.ndarray) -> pl.DataFrame:
    start = date(2020, 1, 1)
    return pl.DataFrame(
        [
            {
                "ts": datetime.fromordinal(start.toordinal() + i).replace(tzinfo=UTC),
                "open": c,
                "high": c,
                "low": c,
                "close": c,
                "volume": 1e6,
            }
            for i, c in enumerate(closes.tolist())
        ]
    )


def _provenance(home: Path, symbol: str) -> None:
    ParquetStore(home / "store").write_provenance(
        symbol, source="alpaca", adapter_version="1", parser_version="1"
    )


def _downup(home: Path, symbol: str) -> None:
    """World: uptrend, drawdown, uptrend (the original P02 world, same seed)."""
    rng = np.random.default_rng(0)
    drift = np.r_[np.full(200, 0.004), np.full(80, -0.012), np.full(320, 0.004)]
    closes = 100.0 * np.cumprod(1.0 + drift + rng.normal(0.0, 0.01, drift.size))
    ParquetStore(home / "store").write_bars(symbol, _frame(closes))
    _provenance(home, symbol)


def test_alpha_test_on_non_finite_close_fails_loud_with_a_typed_data_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Fail-loud contract: invalid data is a typed error, never a raw traceback, never a run.

    `alpha test` gives every error the typed payload and exit 1 (`spine/errors.py::fail`);
    the old command used exit 2 (typer's usage error). The code and the words are checked.
    """
    monkeypatch.setenv("ALPHA_DATA_DIR", str(tmp_path))
    rng = np.random.default_rng(0)
    closes = 100.0 * np.cumprod(1.0 + 0.002 + rng.normal(0.0, 0.01, 300))
    closes[150] = float("nan")
    path = tmp_path / "store" / "bars" / "NANX.parquet"
    path.parent.mkdir(parents=True)
    _frame(closes).write_parquet(path)  # raw write: data that bypassed provider ingestion
    _provenance(tmp_path, "NANX")
    args = ["test", "--rule", "ma_cross", "--param", "fast=5", "--param", "slow=20"]
    result = CliRunner().invoke(app, [*args, "--asset", "NANX", *_QUICK])
    assert result.exit_code == 1, (result.exit_code, repr(result.exception))
    error = json.loads(result.stdout)["error"]
    assert error["code"] == "TEST_FAILED"
    assert "NANX" in error["message"]
    assert "2020-05-30" in error["message"]
    assert "must be finite" in error["message"]
    assert "Traceback" not in result.output
    assert not (tmp_path / "runs").exists()
    plain = CliRunner().invoke(app, [*args, "--asset", "NANX", "--quick", "--no-diagnose"])
    assert plain.exit_code == 1 and "must be finite" in plain.output
    assert "Traceback" not in plain.output


def test_cash_affordability_rejections_are_disclosed_in_the_validation_manifest(
    tmp_path: Path,
) -> None:
    """An unaffordable OOS CASH buy is suppressed before venue submission and disclosed.

    After the drawdown a cash-account BUY sized from starting capital is suppressed, leaving the
    interval flat; its exact reason must remain reviewable. The spec is the old command's
    (`--rebalance-every 5 --train-size 150 --test-size 60 --embargo 2 --periods-per-year 365
    --lookback 20 --skip 1 --vol-window 10`, other options at their defaults).
    """
    _downup(tmp_path, "DNY")
    bars, snapshot_id = _runner.load_bars("DNY", data_dir=tmp_path, as_of=reserve.CUTOFF)
    spec = _runner.RunSpec(
        lookback=20, skip=1, vol_window=10, target_vol=0.15, rebalance_every=5,
        max_leverage=1.0, allow_short=False, periods_per_year=365, fee_bps=1.0,
        slippage_bps=2.0, starting_cash=1_000_000.0, account_type="CASH", train_size=150,
        test_size=60, embargo=2, anchored=False, strategy_name="ts_momentum",
    )  # fmt: skip
    knobs = {k: v for k, v in asdict(_SMALL).items() if k != "max_workers"}
    identity = _runner.run_identity_for(
        {
            "command": "validate",
            "symbol": "DNY",
            "snapshot_id": snapshot_id,
            **asdict(spec),
            **knobs,
        },
        source_fingerprint=_runner.source_fingerprint(bars),
    )
    out = _gauntlet.run_gauntlet(
        bars, spec, _SMALL, run_id=identity.run_id, snapshot_id=snapshot_id
    )
    run_dir, _ = write_validation_run(tmp_path, bars, spec, out, identity)
    orders = pl.read_parquet(run_dir / "orders.parquet")
    denied = orders.filter(pl.col("status") == "DENIED").height
    rejected = pl.read_parquet(run_dir / "pretrade_rejections.parquet")
    manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
    assert denied == 0  # unaffordable orders do not reach the venue matcher
    assert rejected.height > 0
    assert manifest["pretrade_rejections"] == rejected.height
    assert manifest["rejected"] == denied + rejected.height
    assert set(rejected["reason"].to_list()) == {"cash_notional_exceeds_free_balance"}


def test_alpha_test_discloses_resized_cash_entries_and_sends_none_unaffordable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The same world through `alpha test`: all-in entries that do not fit are resized, counted
    in the manifest and the result, and no order is denied at the venue."""
    monkeypatch.setenv("ALPHA_DATA_DIR", str(tmp_path))
    _downup(tmp_path, "DNY")
    args = ["test", "--rule", "tsmom", "--param", "lookback=20", "--param", "skip=1"]
    result = CliRunner().invoke(app, [*args, "--asset", "DNY", *_QUICK])
    assert result.exit_code == 0, result.output
    out = json.loads(result.stdout)["results"][0]
    assert out["error"] is None, out["error"]
    run_dir = Path(out["run_dir"])
    manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
    orders = pl.read_parquet(run_dir / "orders.parquet")
    assert orders.filter(pl.col("status") == "DENIED").height == 0
    assert out["resized_entries"] == manifest["resized_entries"] > 0
    assert manifest["rejected"] == manifest["pretrade_rejections"]
    rejections = run_dir / "pretrade_rejections.parquet"
    assert manifest["pretrade_rejections"] == (
        pl.read_parquet(rejections).height if rejections.exists() else 0
    )
