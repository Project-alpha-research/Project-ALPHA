"""``alpha backtest run``: run the v1 strategy once and persist the trade log + equity curve.

Satisfies spec §11.1. Shares ``_runner.run_full_backtest`` (and the ``RunSpec``) with the
validation gauntlet, so both drive the engine through one code path.
"""

from __future__ import annotations

import re
from datetime import date
from pathlib import Path
from typing import Any

import numpy as np
import typer

from alpha_cli import _artifacts, _forecast_cache, _runner, rules_cmds
from alpha_cli import _backtest_run_inputs as run_inputs
from alpha_cli._backtest_run_inputs import _RESEARCH_GATE_OVERRIDE_HELP
from alpha_cli.backtest_cross_sectional_cmds import cross_sectional_app
from alpha_cli.spine import reserve
from alpha_core import DataError
from alpha_core.config import AlphaSettings
from alpha_data.timeframe import BarTimeframe
from alpha_validation import annualized_volatility, cagr, max_drawdown, sharpe_ratio

backtest_app = typer.Typer(help="Run the v1 strategy through the backtest engine.")

# monkeypatchable load seams (mirror data_cmds._ADAPTERS); tests point them at fixture stores
_load_bars = _runner.load_bars
_load_dividends = _runner.load_dividends


def _holdout_date(value: str, label: str) -> date:
    try:
        parsed = date.fromisoformat(value)
    except ValueError as exc:
        raise DataError(f"{label} must be canonical YYYY-MM-DD") from exc
    if parsed.isoformat() != value:
        raise DataError(f"{label} must be canonical YYYY-MM-DD")
    return parsed


def _holdout_line(
    symbol: str, run_id: str, sharpe: float | None, sessions: int, min_sharpe: float
) -> str:
    """The locked-holdout line: the number, the plain comparison and the level of the old grade."""
    if sharpe is None:
        found = f"Sharpe unavailable over {sessions} sessions."
    else:
        side = "at or above" if sharpe >= min_sharpe else "below"
        found = (
            f"Sharpe {sharpe:.3f} over {sessions} sessions is {side} {min_sharpe:g}, "
            "the minimum Sharpe set for this run."
        )
    old = f"The level used by the old grade: Sharpe at least {min_sharpe:g}."
    return f"locked holdout {symbol} -> run {run_id}: {found} {old}"


@backtest_app.command()
def holdout(
    symbol: str,
    strategy: str = "ts_momentum",
    lookback: int = 252,
    skip: int = 21,
    vol_window: int = 63,
    target_vol: float = 0.15,
    rebalance_every: int = 21,
    max_leverage: float = 1.0,
    allow_short: bool | None = None,
    fee_bps: float = 1.0,
    slippage_bps: float = 2.0,
    starting_cash: float = 1_000_000.0,
    account_type: str = "CASH",
    periods_per_year: int = 252,
    param: list[str] | None = None,
    snapshot: str = typer.Option(..., help="frozen market-data snapshot"),
    holdout_start: str = typer.Option(..., help="revealed inclusive YYYY-MM-DD boundary"),
    holdout_end: str = typer.Option(..., help="revealed inclusive YYYY-MM-DD boundary"),
    holdout_spec_hash: str = typer.Option(..., help="sealed holdout specification SHA-256"),
    min_sharpe: float = typer.Option(0.0, help="predeclared pass threshold"),
    research_gate_override: bool = typer.Option(
        False, "--research-gate-override", help=_RESEARCH_GATE_OVERRIDE_HELP
    ),
) -> None:
    """Evaluate one frozen fixed-parameter candidate on its revealed final holdout once."""
    settings = AlphaSettings()
    try:
        start = _holdout_date(holdout_start, "holdout_start")
        end = _holdout_date(holdout_end, "holdout_end")
        if start > end:
            raise DataError("holdout_start must not follow holdout_end")
        if re.fullmatch(r"[0-9a-f]{64}", holdout_spec_hash) is None:
            raise DataError("holdout_spec_hash must be a 64-hex SHA-256 digest")
        if not np.isfinite(min_sharpe):
            raise DataError("min_sharpe must be finite")
        spec = _runner.RunSpec(
            lookback=lookback,
            skip=skip,
            vol_window=vol_window,
            target_vol=target_vol,
            rebalance_every=rebalance_every,
            max_leverage=max_leverage,
            allow_short=_runner.resolve_allow_short(allow_short, account_type),
            periods_per_year=periods_per_year,
            fee_bps=fee_bps,
            slippage_bps=slippage_bps,
            starting_cash=starting_cash,
            account_type=account_type,
            train_size=504,
            test_size=63,
            embargo=5,
            anchored=False,
            strategy_name=strategy,
            strategy_params=_runner.parse_strategy_params(strategy, param),
        )
        holdout_cutoff = _runner.parse_as_of(holdout_end)
        bars, snapshot_id = _load_bars(
            symbol,
            data_dir=settings.data_dir,
            snapshot_id=snapshot,
            as_of=holdout_cutoff,
        )
        if len(bars) < 2:
            raise DataError("holdout end leaves fewer than two causal bars")
        dividends = [
            action
            for action in _load_dividends(
                symbol,
                data_dir=settings.data_dir,
                snapshot_id=snapshot,
                as_of=holdout_cutoff,
            )
            if action.knowledge_time <= end and (action.pay_date or action.ex_date) <= end
        ]
        spec, forecast_meta = _forecast_cache.prepare_spec_for_engine(
            bars, spec, data_dir=settings.data_dir, seed=settings.random_seed
        )
        first_index = next(
            (index for index, bar in enumerate(bars) if bar.ts.date() >= start),
            None,
        )
        if first_index is None or first_index == 0:
            raise DataError("revealed holdout requires at least one prior causal decision bar")
        final_index = len(bars) - 1
        scoped = _runner.fresh_scored_execution(
            bars,
            spec,
            first_scored_index=first_index,
            final_scored_index=final_index,
            dividends=dividends,
            normalize_equity=False,
        )
        equity = scoped.equity_curve
    except DataError as exc:
        raise typer.BadParameter(str(exc)) from exc

    values = np.asarray([value for _, value in equity], dtype=np.float64)
    normalized = values / values[0]
    returns = normalized[1:] / normalized[:-1] - 1.0
    volatility = annualized_volatility(returns, periods_per_year=periods_per_year)
    sharpe = (
        sharpe_ratio(returns, periods_per_year=periods_per_year)
        if returns.size >= 2 and float(np.std(returns, ddof=1)) > 0.0
        else None
    )
    passed = sharpe is not None and sharpe >= min_sharpe

    scoped_trades = scoped.trades
    identity = _runner.run_identity_for(
        {
            "command": "backtest_holdout",
            "symbol": symbol,
            "snapshot_id": snapshot_id,
            "holdout_start": holdout_start,
            "holdout_end": holdout_end,
            "holdout_spec_hash": holdout_spec_hash,
            "min_sharpe": min_sharpe,
            **_artifacts.research_gate_override_identity(research_gate_override),
            **vars(spec),
        },
        source_fingerprint=_runner.source_fingerprint(bars, dividends=dividends),
        snapshot_hash=_runner.verified_snapshot_hash(settings.data_dir, snapshot_id),
    )
    run_id = identity.run_id
    manifest = _artifacts.sanitize(
        {
            "schema_version": 1,
            "run_id": run_id,
            "command": "backtest_holdout",
            "symbol": symbol,
            "snapshot_id": snapshot_id,
            "params": vars(spec),
            "holdout_start": holdout_start,
            "holdout_end": holdout_end,
            "holdout_spec_hash": holdout_spec_hash,
            "holdout_policy": "fixed_candidate_one_shot_after_owner_reveal",
            "warmup_history_included": True,
            "holdout_execution_boundary": "fresh_portfolio_after_causal_indicator_priming",
            "holdout_trace_scope": (
                "scored_holdout_sessions_plus_originating_prior_close_decision"
            ),
            "min_sharpe": min_sharpe,
            "passed": passed,
            "metrics": {
                "total_return": float(normalized[-1] - 1.0),
                "cagr": cagr(normalized, periods_per_year=periods_per_year),
                "annual_volatility": volatility,
                "sharpe": sharpe,
                "max_drawdown": max_drawdown(normalized),
            },
            "n_scored_sessions": len(equity),
            "n_trades": len(scoped_trades),
            "rejected": scoped.rejected,
            "pretrade_rejections": len(scoped.execution_rejections),
            **_artifacts.research_gate_override_fields(research_gate_override),
            **identity.manifest_fields(),
        }
    )
    if forecast_meta is not None:
        manifest["forecast"] = forecast_meta
    rdir = _artifacts.run_dir(settings.data_dir, run_id)
    _artifacts.write_run(
        rdir,
        manifest=manifest,
        equity=equity,
        trades=scoped_trades,
        trace_result=scoped,
        periods_per_year=periods_per_year,
    )
    typer.echo(_holdout_line(symbol, run_id, sharpe, len(equity), min_sharpe))


@backtest_app.command()
def oos(
    symbol: str,
    strategy: str = "ts_momentum",
    lookback: int = 252,
    skip: int = 21,
    vol_window: int = 63,
    target_vol: float = 0.15,
    rebalance_every: int = 21,
    max_leverage: float = 1.0,
    allow_short: bool | None = None,
    fee_bps: float = 1.0,
    slippage_bps: float = 2.0,
    starting_cash: float = 1_000_000.0,
    account_type: str = "CASH",
    periods_per_year: int = 252,
    train_size: int = 504,
    test_size: int = 63,
    embargo: int = 5,
    anchored: bool = False,
    param: list[str] | None = None,
    snapshot: str | None = None,
    as_of: str | None = typer.Option(None, "--as-of", help="inclusive research cutoff YYYY-MM-DD"),
    research_gate_override: bool = typer.Option(
        False, "--research-gate-override", help=_RESEARCH_GATE_OVERRIDE_HELP
    ),
) -> None:
    """Evaluate one fixed rule over causal walk-forward OOS windows; no model is refit."""
    settings = AlphaSettings()
    spec = _runner.RunSpec(
        lookback=lookback,
        skip=skip,
        vol_window=vol_window,
        target_vol=target_vol,
        rebalance_every=rebalance_every,
        max_leverage=max_leverage,
        allow_short=_runner.resolve_allow_short(allow_short, account_type),
        periods_per_year=periods_per_year,
        fee_bps=fee_bps,
        slippage_bps=slippage_bps,
        starting_cash=starting_cash,
        account_type=account_type,
        train_size=train_size,
        test_size=test_size,
        embargo=embargo,
        anchored=anchored,
        strategy_name=strategy,
        strategy_params=_runner.parse_strategy_params(strategy, param),
    )
    try:
        held = reserve.hold(symbol, data_dir=settings.data_dir, as_of=as_of, snapshot_id=snapshot)
        bars, snapshot_id = _load_bars(
            symbol, data_dir=settings.data_dir, snapshot_id=snapshot, as_of=held.as_of
        )
        dividends = _load_dividends(
            symbol, data_dir=settings.data_dir, snapshot_id=snapshot, as_of=held.as_of
        )
        spec, forecast_meta = _forecast_cache.prepare_spec_for_engine(
            bars, spec, data_dir=settings.data_dir, seed=settings.random_seed
        )
        oos_result, scoped = _runner.fresh_oos_execution(bars, spec, dividends=dividends)
    except DataError as exc:
        raise typer.BadParameter(str(exc)) from exc
    identity = _runner.run_identity_for(
        {
            "command": "backtest_oos",
            "symbol": symbol,
            "snapshot_id": snapshot_id,
            **held.identity(),
            **_artifacts.research_gate_override_identity(research_gate_override),
            **vars(spec),
        },
        source_fingerprint=_runner.source_fingerprint(bars, dividends=dividends),
        snapshot_hash=_runner.verified_snapshot_hash(settings.data_dir, snapshot_id),
    )
    run_id = identity.run_id
    equity = scoped.equity_curve
    equity_values = np.asarray([value for _, value in equity], dtype=np.float64)
    returns = oos_result.oos_returns
    folds = oos_result.folds
    volatility = annualized_volatility(returns, periods_per_year=periods_per_year)
    sharpe = (
        sharpe_ratio(returns, periods_per_year=periods_per_year)
        if returns.size >= 2 and float(np.std(returns, ddof=1)) > 0.0
        else None
    )
    manifest = _artifacts.sanitize(
        {
            "schema_version": 1,
            "run_id": run_id,
            "command": "backtest_oos",
            "symbol": symbol,
            "snapshot_id": snapshot_id,
            **held.identity(),
            "params": vars(spec),
            "oos_semantics": "fixed_rule_evaluation_no_refit",
            "folds": [_runner.fold_manifest(fold, bars) for fold in folds],
            "oos_execution_boundary": "fresh_portfolio_after_causal_indicator_priming",
            "oos_trace_scope": "scored_test_sessions_plus_originating_prior_close_decision",
            "oos_metrics": {
                "total_return": float(equity_values[-1] - 1.0),
                "cagr": cagr(equity_values, periods_per_year=periods_per_year),
                "annual_volatility": volatility,
                "sharpe": sharpe,
                "max_drawdown": max_drawdown(equity_values),
            },
            "rejected": scoped.rejected,
            "pretrade_rejections": len(scoped.execution_rejections),
            **_artifacts.research_gate_override_fields(research_gate_override),
            **identity.manifest_fields(),
        }
    )
    if forecast_meta is not None:
        manifest["forecast"] = forecast_meta
    held.stamp(manifest)
    rdir = _artifacts.run_dir(settings.data_dir, run_id)
    _artifacts.write_run_sidecars(
        rdir,
        equity=equity,
        trades=scoped.trades,
        trace_result=scoped,
        periods_per_year=periods_per_year,
    )
    _artifacts.write_manifest(rdir, manifest)
    typer.echo(
        f"rule OOS {symbol} (fixed parameters, no refit) -> run {run_id}: "
        f"{len(folds)} folds, {returns.size} scored sessions"
    )
    held.announce()


def _run_hold(
    symbol: str,
    data_dir: Path,
    as_of: str | None,
    snapshot: str | None,
    stored: BarTimeframe,
    manifest_id: str | None,
) -> reserve.Hold:
    """The run's cut-off. An archive read (``--manifest-id``) is cut by the same rule."""
    if manifest_id is not None:
        from alpha_cli._archive_bars import hold_archive
        from alpha_cli.crypto_data_cmds import _bulk_store

        return hold_archive(_bulk_store(), manifest_id, symbol, as_of)
    return reserve.hold(
        symbol,
        data_dir=data_dir,
        as_of=as_of,
        snapshot_id=snapshot,
        timeframe=stored.canonical,
        instant=True,
    )


def _run_manifest(
    identity: Any,
    symbol: str,
    snapshot_id: str | None,
    held: reserve.Hold,
    spec: _runner.RunSpec,
    result: Any,
    research_gate_override: bool,
    timeframe_fields: dict[str, str | None],
    forecast_meta: dict[str, Any] | None,
) -> dict[str, Any]:
    """The ``backtest run`` manifest; a daily run carries no timeframe fields (keys unchanged)."""
    run_id = identity.run_id
    manifest: dict[str, Any] = {
        "schema_version": 1,
        "run_id": run_id,
        "command": "backtest_run",
        "symbol": symbol,
        "snapshot_id": snapshot_id,
        **held.fields(),
        "params": vars(spec),
        "orders": result.orders,
        "fills": result.fills,
        "rejected": result.rejected,
        "pretrade_rejections": len(result.execution_rejections),
        "n_trades": len(result.trades),
        "starting_equity": result.starting_equity,
        "final_equity": result.final_equity,
        **_artifacts.research_gate_override_fields(research_gate_override),
        **identity.manifest_fields(),
        **timeframe_fields,
    }
    if forecast_meta is not None:
        manifest["forecast"] = forecast_meta
    return manifest


@backtest_app.command()
def run(
    symbol: str,
    strategy: str = "ts_momentum",
    lookback: int = 252,
    skip: int = 21,
    vol_window: int = 63,
    target_vol: float = 0.15,
    rebalance_every: int = 21,
    max_leverage: float = 1.0,
    allow_short: bool | None = None,  # default: MARGIN->True, CASH->False
    fee_bps: float = 1.0,
    slippage_bps: float = 2.0,
    starting_cash: float = 1_000_000.0,
    account_type: str = "CASH",
    periods_per_year: int | None = None,
    size_on_equity: bool = False,
    halt_drawdown: float | None = None,
    param: list[str] | None = None,
    rules: str | None = typer.Option(
        None, "--rules", help="saved rule set for --strategy rules (alpha rules save NAME)"
    ),
    rules_file: Path | None = typer.Option(  # noqa: B008
        None, "--rules-file", help="canonical frozen rule file (local path)"
    ),
    rules_sha256: str | None = typer.Option(
        None, "--rules-sha256", help="SHA-256 of exact frozen rule file bytes"
    ),
    snapshot: str | None = None,
    timeframe: str = typer.Option("1D", help="bar timeframe, from one minute to one day"),
    from_timeframe: str | None = typer.Option(None, help="stored timeframe to resample from"),
    session: str | None = typer.Option(None, help="regular, extended or continuous"),
    manifest_id: str | None = typer.Option(None, help="verified archive chart-dataset group id"),
    as_of: str | None = typer.Option(None, "--as-of", help="date or ISO instant with offset"),
    research_gate_override: bool = typer.Option(
        False, "--research-gate-override", help=_RESEARCH_GATE_OVERRIDE_HELP
    ),
) -> None:
    """Backtest SYMBOL with the fixed-parameter strategy; write the run artifacts.

    ``--strategy`` selects the registered strategy; ``--param name=value`` (repeatable) supplies any
    strategy-specific parameters beyond the shared ones; ``--rules NAME`` selects the owner's saved
    rule set for ``--strategy rules``.
    """
    settings = AlphaSettings()
    try:
        target, stored = run_inputs._run_timeframes(
            timeframe, from_timeframe, manifest_id, snapshot
        )
        rules_spec = rules_cmds.resolve_rules_spec(
            strategy, rules, settings.data_dir, rules_file=rules_file, rules_sha256=rules_sha256
        )
    except DataError as exc:
        raise typer.BadParameter(str(exc)) from exc
    spec = _runner.RunSpec(
        lookback=lookback,
        skip=skip,
        vol_window=vol_window,
        target_vol=target_vol,
        rebalance_every=rebalance_every,
        max_leverage=max_leverage,
        allow_short=_runner.resolve_allow_short(allow_short, account_type),
        periods_per_year=252 if periods_per_year is None else periods_per_year,
        fee_bps=fee_bps,
        slippage_bps=slippage_bps,
        starting_cash=starting_cash,
        account_type=account_type,
        train_size=504,  # walk-forward fields are unused by a plain backtest; kept coherent
        test_size=63,
        embargo=5,
        anchored=False,
        strategy_name=strategy,
        strategy_params=_runner.parse_strategy_params(strategy, param),
        size_on_equity=size_on_equity,
        halt_drawdown=halt_drawdown,
        rules_spec=rules_spec,
    )
    try:
        held = _run_hold(symbol, settings.data_dir, as_of, snapshot, stored, manifest_id)
        symbol, bars, snapshot_id, dividends, timeframe_fields = run_inputs._load_run_bars(
            symbol,
            data_dir=settings.data_dir,
            snapshot=snapshot,
            as_of=held.as_of,
            target=target,
            stored=stored,
            session=session,
            manifest_id=manifest_id,
            resampled=stored != target,
        )
        spec = run_inputs._annualised(spec, bars, target, timeframe_fields, periods_per_year)
        # kronos: precompute the signal cache (slow model, runs once) and pin its key on the
        # spec; every other strategy passes through untouched.
        spec, forecast_meta = _forecast_cache.prepare_spec_for_engine(
            bars, spec, data_dir=settings.data_dir, seed=settings.random_seed
        )
        result = _runner.run_full_backtest(bars, spec, dividends=dividends, timeframe=target)
    except DataError as exc:  # no bars stored, unknown strategy, bad account-type, etc.
        raise typer.BadParameter(str(exc)) from exc
    # Fail loud (golden rule): a run that submitted orders but filled none — every order rejected —
    # would otherwise report a misleading flat equity. The usual cause is a vol-targeted notional
    # that exceeds CASH buying power once fees apply.
    if result.fills == 0 and result.rejected > 0:
        raise typer.BadParameter(
            f"all {result.rejected} orders were rejected (no fills) for {symbol}: the vol-targeted "
            f"notional exceeds buying power. Use --account-type MARGIN, lower --target-vol, or set "
            f"--max-leverage below 1."
        )
    identity = _runner.run_identity_for(
        {
            "command": "backtest_run",
            "symbol": symbol,
            "snapshot_id": snapshot_id,
            **held.identity(),
            **_artifacts.research_gate_override_identity(research_gate_override),
            **vars(spec),
            **timeframe_fields,
        },
        source_fingerprint=_runner.source_fingerprint(bars, dividends=dividends),
        snapshot_hash=_runner.verified_snapshot_hash(
            settings.data_dir, snapshot_id, timeframe=stored.canonical
        ),
    )
    run_id = identity.run_id
    rdir = _artifacts.run_dir(settings.data_dir, run_id)
    manifest = _run_manifest(
        identity,
        symbol,
        snapshot_id,
        held,
        spec,
        result,
        research_gate_override,
        timeframe_fields,
        forecast_meta,
    )
    _artifacts.write_run(
        rdir,
        manifest=manifest,
        equity=result.equity_curve,
        trades=result.trades,
        trace_result=result,
        periods_per_year=spec.periods_per_year,
    )
    warn = f" ({result.rejected} orders rejected)" if result.rejected else ""
    typer.echo(
        f"backtest {symbol}{'' if target.is_daily else ' ' + target.canonical} -> run {run_id}: "
        f"{result.orders} orders, {result.fills} fills, {len(result.trades)} trades, "
        f"final equity {result.final_equity:.2f}{warn}{held.note()}"
    )
    if forecast_meta is not None and forecast_meta["pretrain"]["overlap"]:
        typer.secho(
            "WARNING: the forecast windows overlap the assumed Kronos pretraining period "
            f"(<= {forecast_meta['pretrain']['cutoff']}) — backtest may reflect memorization "
            "(ADR-0009)",
            fg=typer.colors.YELLOW,
        )


@backtest_app.command()
def portfolio(
    symbols: list[str],
    strategy: str = "ts_momentum",
    weighting: str = "equal",
    lookback: int = 252,
    skip: int = 21,
    vol_window: int = 63,
    target_vol: float = 0.15,
    rebalance_every: int = 21,
    max_leverage: float = 1.0,
    allow_short: bool | None = None,  # default: MARGIN->True, CASH->False
    fee_bps: float = 1.0,
    slippage_bps: float = 2.0,
    starting_cash: float = 1_000_000.0,
    account_type: str = "CASH",
    periods_per_year: int = 252,
    size_on_equity: bool = False,
    halt_drawdown: float | None = None,
    train_size: int = 504,
    test_size: int = 63,
    embargo: int = 5,
    anchored: bool = False,
    seed: int | None = None,
    param: list[str] | None = None,
    snapshot: str | None = None,
    as_of: str | None = typer.Option(None, "--as-of", help="inclusive research cutoff YYYY-MM-DD"),
    research_gate_override: bool = typer.Option(
        False, "--research-gate-override", help=_RESEARCH_GATE_OVERRIDE_HELP
    ),
) -> None:
    """Backtest a diversified basket: run the strategy across SYMBOLS and combine the OOS streams.

    ``--weighting`` is ``equal`` or ``inverse_vol``. Reports the basket's headline metrics +
    Probabilistic Sharpe and each leg's OOS Sharpe; writes a manifest under ``data_dir/portfolio``.
    """

    from alpha_cli import _portfolio

    settings = AlphaSettings()
    # canonical (sorted) symbol order: the run_id already sorts, and rank ties / float-summation
    # order must not depend on how the shell happened to order the arguments
    symbols = sorted(symbols)
    resolved_seed = seed if seed is not None else settings.random_seed
    spec = _runner.RunSpec(
        lookback=lookback,
        skip=skip,
        vol_window=vol_window,
        target_vol=target_vol,
        rebalance_every=rebalance_every,
        max_leverage=max_leverage,
        allow_short=_runner.resolve_allow_short(allow_short, account_type),
        periods_per_year=periods_per_year,
        fee_bps=fee_bps,
        slippage_bps=slippage_bps,
        starting_cash=starting_cash,
        account_type=account_type,
        train_size=train_size,
        test_size=test_size,
        embargo=embargo,
        anchored=anchored,
        strategy_name=strategy,
        strategy_params=_runner.parse_strategy_params(strategy, param),
        size_on_equity=size_on_equity,
        halt_drawdown=halt_drawdown,
    )
    try:
        held = reserve.hold_many(symbols, settings.data_dir, as_of, snapshot)
        result = _portfolio.run_portfolio(
            symbols,
            spec,
            data_dir=settings.data_dir,
            weighting=weighting,
            seed=resolved_seed,
            snapshot_id=snapshot,
            as_of=held.as_of,
        )
    except DataError as exc:
        raise typer.BadParameter(str(exc)) from exc

    snapshot_hash = _runner.verified_snapshot_hash(settings.data_dir, snapshot)
    identity = _runner.run_identity_for(
        {
            "command": "backtest_portfolio",
            "symbols": symbols,
            "weighting": weighting,
            "seed": resolved_seed,
            "snapshot_id": snapshot,
            **held.identity(),
            **_artifacts.research_gate_override_identity(research_gate_override),
            **vars(spec),
        },
        source_fingerprint=result.source_fingerprint,
        snapshot_hash=snapshot_hash,
    )
    run_id = identity.run_id
    rdir = settings.data_dir / "portfolio" / run_id
    rdir.mkdir(parents=True, exist_ok=True)
    # the combined OOS stream as an equity curve (validate-run schema, base 1.0), written BEFORE
    # the manifest — manifest.json is the run-exists marker (see _artifacts.write_run)
    _artifacts.write_equity_curve(
        rdir,
        baseline_ts=result.baseline_ts,
        timestamps=result.portfolio_timestamps,
        returns=result.portfolio_returns.tolist(),
        periods_per_year=spec.periods_per_year,
        gross_exposure=result.portfolio_gross_exposure.tolist(),
        net_exposure=result.portfolio_net_exposure.tolist(),
    )
    _artifacts.write_portfolio_analytics(
        rdir,
        source_run_id=run_id,
        snapshot_id=snapshot,
        snapshot_hash=snapshot_hash,
        research_cutoff=held.research_cutoff,
        allocations=result.allocations,
        correlations=result.correlations,
    )
    manifest: dict[str, Any] = {
        "schema_version": 1,
        "run_id": run_id,
        "command": "backtest_portfolio",
        "seed": resolved_seed,
        "snapshot_id": snapshot,
        **held.fields(),
        "symbols": list(result.symbols),
        "weighting": result.weighting,
        "n_periods": result.n_periods,
        "metrics": {k: (v if v == v else None) for k, v in result.metrics.items()},
        "psr": result.psr if result.psr == result.psr else None,
        "dsr": result.dsr if result.dsr == result.dsr else None,
        "sharpe_ci": {"lower": result.sharpe_ci.lower, "upper": result.sharpe_ci.upper},
        "cagr_ci": {"lower": result.cagr_ci.lower, "upper": result.cagr_ci.upper},
        "legs": [
            {
                "symbol": leg.symbol,
                "n_oos": leg.n_oos,
                "oos_sharpe": leg.oos_sharpe if leg.oos_sharpe == leg.oos_sharpe else None,
                "weight": leg.weight,
            }
            for leg in result.legs
        ],
        **_artifacts.research_gate_override_fields(research_gate_override),
        **identity.manifest_fields(),
    }
    from alpha_validation import render_returns_tearsheet

    _artifacts.publish_artifact(
        rdir / "tearsheet.html",
        lambda path: render_returns_tearsheet(
            result.portfolio_returns,
            result.portfolio_timestamps,
            title=f"ALPHA Portfolio — {', '.join(result.symbols)} ({weighting})",
            summary_rows=[
                ("OOS Sharpe", f"{result.metrics['sharpe']:.3f}"),
                (
                    "Sharpe 95% CI",
                    f"[{result.sharpe_ci.lower:.2f}, {result.sharpe_ci.upper:.2f}]",
                ),
                ("CAGR", f"{result.metrics['cagr']:.3f}"),
                ("Max drawdown", f"{result.metrics['max_drawdown']:.3f}"),
                ("Probabilistic Sharpe", f"{result.psr:.3f}"),
                ("Periods", str(result.n_periods)),
                ("Legs", ", ".join(f"{leg.symbol}={leg.weight:.2f}" for leg in result.legs)),
            ],
            output_path=path,
        ),
    )
    _artifacts.write_manifest(rdir, manifest)
    typer.echo(
        f"portfolio [{', '.join(result.symbols)}] ({weighting}) -> run {run_id}: "
        f"OOS Sharpe {result.metrics['sharpe']:.3f} "
        f"[{result.sharpe_ci.lower:.2f}, {result.sharpe_ci.upper:.2f}], "
        f"CAGR {result.metrics['cagr']:.3f}, maxDD {result.metrics['max_drawdown']:.3f}, "
        f"PSR {result.psr:.3f} over {result.n_periods} periods; "
        f"manifest at {rdir / 'manifest.json'}{held.note()}"
    )


backtest_app.add_typer(cross_sectional_app)
