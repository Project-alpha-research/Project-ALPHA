"""``alpha validate <symbol>``: run the validation gauntlet and emit a tear sheet (spec §11.2).

Walk-forward OOS (net of costs) + the two-tier randomized-price null + block-bootstrap BCa CIs,
written as a byte-stable JSON manifest, an equity/trade Parquet pair, and a quantstats HTML tear
sheet under ``data_dir/runs/<run_id>/``.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import TYPE_CHECKING, Any

import typer

from alpha_cli import _artifacts, _forecast_cache, _gauntlet, _runner, rules_cmds
from alpha_cli._identity import RunIdentity
from alpha_cli.spine.deflation import validation_family
from alpha_cli.spine.errors import SpineError, fail
from alpha_core import Bar, DataError, bps_rate
from alpha_core.config import AlphaSettings
from alpha_validation import FloatArray, render_tearsheet_html, report_to_manifest

if TYPE_CHECKING:
    from alpha_backtest.results import BacktestResult


# monkeypatchable load seams (mirror backtest_cmds); tests point them at fixture stores
_load_bars = _runner.load_bars
_load_dividends = _runner.load_dividends


def validate(
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
    periods_per_year: int = 252,
    train_size: int = 504,  # >= warmup floor for the default 252/21/63 params (max=274); ~2y train
    test_size: int = 63,
    embargo: int = 5,
    anchored: bool = False,
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
    tier1_paths: int = 1000,
    tier2_paths: int = 64,
    tier3_paths: int = 64,
    n_resamples: int = 2000,
    mean_block: float = 5.0,
    threshold: float = 0.95,
    null_model: str = "bootstrap",
    tier1_divergence_tol: float = 0.25,
    tier2_mode: str = typer.Option(
        "replay",
        help="kronos engine-tier policy (Tier 2 and the Tier-3 bar-permutation paths): replay "
        "(cached signals, cheap) | model (re-forecast every synthetic path — honest but "
        "~(tier2-paths + tier3-paths) x the model cost)",
    ),
    seed: int | None = None,
    max_workers: int | None = None,
    snapshot: str | None = None,
    as_of: str | None = typer.Option(None, "--as-of", help="inclusive research cutoff YYYY-MM-DD"),
    research_gate_override: bool = typer.Option(
        False,
        "--research-gate-override",
        help="watermark this run EXPLORATORY / RESEARCH GATE NOT COMPLETED "
        "(launched under an owner research-gate override)",
    ),
) -> None:
    """Validate SYMBOL end-to-end and write the run artifacts (manifest, parquet, tear sheet).

    ``--strategy`` selects the registered strategy; ``--param name=value`` (repeatable) supplies any
    strategy-specific parameters beyond the shared ones.
    """
    settings = AlphaSettings()
    resolved_seed = seed if seed is not None else settings.random_seed
    try:
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
        rules_spec=rules_spec,
    )
    gparams = _gauntlet.GauntletParams(
        seed=resolved_seed,
        tier1_paths=tier1_paths,
        tier2_paths=tier2_paths,
        tier3_paths=tier3_paths,
        n_resamples=n_resamples,
        mean_block=mean_block,
        threshold=threshold,
        null_model=null_model,
        max_workers=max_workers,
        tier1_divergence_tol=tier1_divergence_tol,
        tier2_mode=tier2_mode,
    )
    if tier2_mode == "model" and strategy != "kronos":
        raise typer.BadParameter(
            "--tier2-mode model re-derives forecasts per synthetic path and applies only to "
            "the kronos strategy"
        )
    try:
        research_cutoff = _runner.parse_as_of(as_of)
        bars, snapshot_id = _load_bars(
            symbol,
            data_dir=settings.data_dir,
            snapshot_id=snapshot,
            as_of=research_cutoff,
        )
        dividends = _load_dividends(
            symbol,
            data_dir=settings.data_dir,
            snapshot_id=snapshot,
            as_of=research_cutoff,
        )
        spec, forecast_meta = _forecast_cache.prepare_spec_for_engine(
            bars, spec, data_dir=settings.data_dir, seed=resolved_seed
        )
        tier2_spec_for_path = None
        if tier2_mode == "model":
            prepared_spec = spec

            def tier2_spec_for_path(path_bars: list[Bar]) -> _runner.RunSpec:
                return _forecast_cache.prepare_spec_for_engine(
                    path_bars, prepared_spec, data_dir=settings.data_dir, seed=resolved_seed
                )[0]

        # max_workers is an execution-only knob (results are order-preserving and identical
        # serial or pooled), so it must NOT change the run id (same params -> same id).
        gauntlet_knobs = {k: v for k, v in vars(gparams).items() if k != "max_workers"}
        identity = _runner.run_identity_for(
            {
                "command": "validate",
                "symbol": symbol,
                "snapshot_id": snapshot_id,
                "research_cutoff": as_of,
                **_artifacts.research_gate_override_identity(research_gate_override),
                **vars(spec),
                **gauntlet_knobs,
            },
            source_fingerprint=_runner.source_fingerprint(bars, dividends=dividends),
            snapshot_hash=_runner.verified_snapshot_hash(settings.data_dir, snapshot_id),
        )
        run_id = identity.run_id
        out = _gauntlet.run_gauntlet(
            bars,
            spec,
            gparams,
            run_id=run_id,
            snapshot_id=snapshot_id,
            dividends=dividends,
            tier2_spec_for_path=tier2_spec_for_path,
            **_ledger_family(settings.data_dir, strategy, spec.periods_per_year, run_id),
        )
    except DataError as exc:  # no bars, unknown strategy/null-model, train < warmup floor, etc.
        raise typer.BadParameter(str(exc)) from exc

    rdir, _ = write_validation_run(
        settings.data_dir,
        bars,
        spec,
        out,
        identity,
        as_of=as_of,
        research_gate_override=research_gate_override,
        forecast_meta=forecast_meta,
        tier2_mode=tier2_mode,
    )

    status = "PASS" if out.report.passed else "FAIL"
    sharpe = out.report.oos_metrics["sharpe"]
    v = out.report.verdict
    grade = (
        f"Verdict {v.overall} "
        f"(edge {v.edge}/robustness {v.robustness}/risk {v.risk}/sample {v.sample}), "
        if v is not None
        else ""
    )
    typer.echo(
        f"validate {symbol} -> run {run_id}: {status} "
        f"({grade}OOS Sharpe {sharpe:.3f}, "
        f"null pct {'/'.join(f'{n.percentile:.2f}' for n in out.report.nulls)}); "
        f"tear sheet at {rdir / 'tearsheet.html'}"
    )
    if forecast_meta is not None:
        typer.echo(f"  kronos: cache {forecast_meta['cache_key']}, tier2 policy {tier2_mode}")
        if forecast_meta["pretrain"]["overlap"]:
            typer.secho(
                "WARNING: the forecast windows overlap the assumed Kronos pretraining "
                f"period (<= {forecast_meta['pretrain']['cutoff']}) — the verdict may "
                "reflect memorization (ADR-0009)",
                fg=typer.colors.YELLOW,
            )


def _ledger_family(data_dir: Path, strategy: str, periods_per_year: int, run_id: str) -> Any:
    """The run's ledger family inputs; an unreadable ledger stops with its typed error."""
    try:
        return validation_family(data_dir, strategy, periods_per_year, run_id)
    except SpineError as exc:
        fail(exc, json_out=False)


def scored_bar_returns(
    bars: Sequence[Bar],
    spec: _runner.RunSpec,
    result: BacktestResult,
    net_returns: FloatArray,
) -> tuple[FloatArray, FloatArray]:
    """Split each scored bar's net return into before-cost return and costs charged.

    The engine values a long position at the opening quote's BID (its liquidation price), so a
    buy at the ask loses the whole bid-ask gap in the very bar it fills, and a later sell at the
    bid costs only its fee. Costs are therefore booked on the bar where the engine's equity takes
    them: fee on every fill, plus ``quantity x (price - bid)`` on a buy. The before-cost return is
    the bid-to-bid move of the held units (plus any dividend cash), so it equals net + cost.
    Long-or-flat only: a short would be valued at the ask instead.
    """
    import numpy as np
    from nautilus_trader.model.objects import Money, Price

    from alpha_backtest.instruments import instrument_for

    if result.fills != len(result.fill_trace):
        raise DataError("Scored costs require a complete fill trace")
    if not result.fill_trace:
        return net_returns.copy(), np.zeros_like(net_returns)
    equity = result.equity_curve
    if len(equity) != len(net_returns) + 1 or equity[0][1] != 1.0:
        raise DataError("Scored costs require the normalized fresh portfolio and its bar returns")
    # Equity is pre-fill except at the terminal open, which settles its own fills too.
    interval = {ts: min(i, len(net_returns) - 1) for i, (ts, _) in enumerate(equity)}
    instrument = instrument_for(bars[0].symbol)
    opens = {bar.ts: bar.open for bar in bars}
    rate = bps_rate(spec.fee_bps)
    charged = np.zeros_like(net_returns)
    units = 0.0
    for fill in sorted(result.fill_trace, key=lambda item: item.sequence_id):
        if fill.ts not in interval or fill.ts not in opens:
            raise DataError("Scored fill has no matching equity sample and opening price")
        # The same bid as feed.to_execution_feed: open less the half-spread, on the tick grid.
        bid = float(
            Price(opens[fill.ts] * (1.0 - spec.slippage_bps / 10_000.0), instrument.price_precision)
        )
        units += fill.quantity if fill.side == "BUY" else -fill.quantity
        spread = fill.price - bid if fill.side == "BUY" else bid - fill.price
        if fill.side not in {"BUY", "SELL"} or spread < 0 or fill.quantity <= 0 or units < 0:
            raise DataError("Scored costs need long-or-flat fills at or beyond the bid")
        # BpsFeeModel charges Money in quote currency, rounded on each fill.
        fee = float(Money(fill.quantity * fill.price * rate, instrument.quote_currency))
        charged[interval[fill.ts]] += fee + fill.quantity * spread
    prior_capital = np.array([value for _, value in equity[:-1]]) * spec.starting_cash
    costs = charged / prior_capital
    return net_returns + costs, costs


def write_validation_sidecars(
    rdir: Path,
    bars: Sequence[Bar],
    spec: _runner.RunSpec,
    out: _gauntlet.GauntletOutput,
    *,
    rule_test: bool,
) -> None:
    """Stage the same scored evidence for the diagnostic audit and final publication."""
    equity = list(zip(out.oos.oos_timestamps, out.oos.oos_equity.tolist(), strict=True))
    if rule_test and equity != out.result.equity_curve:
        raise DataError("Scored equity timestamps and values must match the execution trace")
    _artifacts.write_run_sidecars(
        rdir,
        equity=equity,
        trades=out.result.trades,
        trace_result=out.result,
        bar_returns=(
            scored_bar_returns(bars, spec, out.result, out.oos.oos_returns) if rule_test else None
        ),
        periods_per_year=spec.periods_per_year,
    )


def write_validation_run(
    data_dir: Path,
    bars: Sequence[Bar],
    spec: _runner.RunSpec,
    out: _gauntlet.GauntletOutput,
    identity: RunIdentity,
    *,
    as_of: str | None = None,
    research_gate_override: bool = False,
    forecast_meta: dict[str, Any] | None = None,
    tier2_mode: str = "replay",
    extra_manifest: dict[str, Any] | None = None,
) -> tuple[Path, dict[str, Any]]:
    """Publish the common validation artifact contract, with the manifest always last."""
    rdir = _artifacts.run_dir(data_dir, identity.run_id)
    manifest = report_to_manifest(out.report)
    if manifest.get("dsr") is not None and manifest.get("verdict") is not None:
        manifest["verdict"]["n_trials"] = manifest["dsr"]["n_trials"]
        manifest["verdict"]["trial_basis"] = manifest["dsr"].get(
            "trial_basis", "no ledger family: counted as one trial"
        )
    manifest["command"] = "validate"
    manifest["research_cutoff"] = as_of
    manifest["oos_semantics"] = "fixed_rule_evaluation_no_refit"
    manifest["folds"] = [_runner.fold_manifest(fold, bars) for fold in out.oos.folds]
    manifest["oos_execution_boundary"] = "fresh_portfolio_after_causal_indicator_priming"
    manifest["oos_trace_scope"] = "scored_test_sessions_plus_originating_prior_close_decision"
    manifest["rejected"] = out.result.rejected
    manifest["pretrade_rejections"] = len(out.result.execution_rejections)
    if spec.rules_spec is not None:
        # the owner's exact rule set, so the report can show what was validated (identity
        # already includes these bytes through ``vars(spec)``)
        manifest["rules_spec"] = spec.rules_spec
    manifest.update(_artifacts.research_gate_override_fields(research_gate_override))
    manifest.update(identity.manifest_fields())
    if forecast_meta is not None:
        manifest["forecast"] = {**forecast_meta, "tier2_policy": tier2_mode}
    if extra_manifest is not None:
        manifest.update(extra_manifest)
    if spec.sizing == "all_in":
        manifest["metadata"]["sizing"] = "all_in"
        manifest["metadata"].pop("target_vol", None)
    # raw three-tier null distributions BEFORE the manifest (manifest.json is the run-exists marker)
    _artifacts.write_nulls(
        rdir,
        tiers=(
            ("returns_level", out.tier1_null.tolist()),
            ("full_engine", out.tier2_null.tolist()),
            ("bar_permutation", out.tier3_null.tolist()),
        ),
    )
    write_validation_sidecars(rdir, bars, spec, out, rule_test="spine" in manifest)
    _artifacts.publish_artifact(
        rdir / "tearsheet.html",
        lambda path: render_tearsheet_html(
            out.report,
            oos_returns=out.oos.oos_returns,
            oos_timestamps=out.oos.oos_timestamps[1:],
            output_path=path,
            periods_per_year=spec.periods_per_year,
        ),
    )
    _artifacts.write_manifest(rdir, manifest)

    # Figure cache keys use the published artifact hashes and contract version.
    return rdir, _artifacts.read_manifest(rdir)
