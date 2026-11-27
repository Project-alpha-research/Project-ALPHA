"""``alpha backtest cross-sectional``: a cross-sectional momentum book over a universe.

The book is long-short or long-only.
"""

from __future__ import annotations

from typing import Any

import typer

from alpha_cli import _artifacts, _runner
from alpha_cli._backtest_run_inputs import _RESEARCH_GATE_OVERRIDE_HELP
from alpha_cli.spine import reserve
from alpha_core import DataError
from alpha_core.config import AlphaSettings

cross_sectional_app = typer.Typer()


@cross_sectional_app.command(name="cross-sectional")
def cross_sectional(
    symbols: list[str],
    lookback: int = 252,
    skip: int = 21,
    vol_window: int = 63,
    target_vol: float = 0.15,
    rebalance_every: int = 21,
    top_quantile: float = 0.3,
    long_short: bool = True,
    max_leverage: float = 2.0,
    fee_bps: float = 1.0,
    slippage_bps: float = 2.0,
    periods_per_year: int = 252,
    seed: int | None = None,
    snapshot: str | None = None,
    as_of: str | None = typer.Option(None, "--as-of", help="inclusive research cutoff YYYY-MM-DD"),
    research_gate_override: bool = typer.Option(
        False, "--research-gate-override", help=_RESEARCH_GATE_OVERRIDE_HELP
    ),
) -> None:
    """Backtest a cross-sectional momentum book: long the universe's winners, short its losers.

    Ranks SYMBOLS each rebalance by trailing return; longs the top ``--top-quantile`` and (unless
    ``--no-long-short``) shorts the bottom, vol-targeted. Reports OOS metrics + PSR + BCa intervals
    and writes a manifest under ``data_dir/cross_sectional``.
    """

    from alpha_cli import _cross_sectional

    settings = AlphaSettings()
    symbols = sorted(symbols)  # canonical order (see portfolio)
    resolved_seed = seed if seed is not None else settings.random_seed
    try:
        held = reserve.hold_many(symbols, settings.data_dir, as_of, snapshot)
        result = _cross_sectional.run_cross_sectional(
            symbols,
            data_dir=settings.data_dir,
            lookback=lookback,
            skip=skip,
            vol_window=vol_window,
            target_vol=target_vol,
            rebalance_every=rebalance_every,
            top_quantile=top_quantile,
            long_short=long_short,
            max_leverage=max_leverage,
            fee_bps=fee_bps,
            slippage_bps=slippage_bps,
            periods_per_year=periods_per_year,
            seed=resolved_seed,
            snapshot_id=snapshot,
            as_of=held.as_of,
        )
    except DataError as exc:
        raise typer.BadParameter(str(exc)) from exc

    identity = _runner.run_identity_for(
        {
            "command": "cross_sectional",
            "symbols": symbols,
            "lookback": lookback,
            "skip": skip,
            "vol_window": vol_window,
            "target_vol": target_vol,
            "rebalance_every": rebalance_every,
            "top_quantile": top_quantile,
            "long_short": long_short,
            "max_leverage": max_leverage,
            "fee_bps": fee_bps,
            "slippage_bps": slippage_bps,
            "periods_per_year": periods_per_year,
            "seed": resolved_seed,
            "snapshot_id": snapshot,
            **held.identity(),
            **_artifacts.research_gate_override_identity(research_gate_override),
        },
        source_fingerprint=result.source_fingerprint,
        snapshot_hash=_runner.verified_snapshot_hash(settings.data_dir, snapshot),
    )
    run_id = identity.run_id
    rdir = settings.data_dir / "cross_sectional" / run_id
    rdir.mkdir(parents=True, exist_ok=True)
    # the OOS stream as an equity curve (validate-run schema, base 1.0), written BEFORE the
    # manifest — manifest.json is the run-exists marker (see _artifacts.write_run)
    _artifacts.write_equity_curve(
        rdir,
        baseline_ts=result.baseline_ts,
        timestamps=result.timestamps,
        returns=result.returns.tolist(),
        periods_per_year=periods_per_year,
    )
    manifest: dict[str, Any] = {
        "schema_version": 1,
        "run_id": run_id,
        "command": "cross_sectional",
        "seed": resolved_seed,
        "snapshot_id": snapshot,
        "research_cutoff": held.research_cutoff,
        "symbols": list(result.symbols),
        "long_short": result.long_short,
        "n_long": result.n_long,
        "n_periods": result.n_periods,
        "metrics": {k: (v if v == v else None) for k, v in result.metrics.items()},
        "psr": result.psr if result.psr == result.psr else None,
        "dsr": result.dsr if result.dsr == result.dsr else None,
        "sharpe_ci": {"lower": result.sharpe_ci.lower, "upper": result.sharpe_ci.upper},
        "cagr_ci": {"lower": result.cagr_ci.lower, "upper": result.cagr_ci.upper},
        **_artifacts.research_gate_override_fields(research_gate_override),
        **identity.manifest_fields(),
    }
    held.stamp(manifest)
    book = "long-short" if long_short else "long-only"
    from alpha_validation import render_returns_tearsheet

    _artifacts.publish_artifact(
        rdir / "tearsheet.html",
        lambda path: render_returns_tearsheet(
            result.returns,
            result.timestamps,
            title=(
                f"ALPHA Cross-Sectional — {', '.join(result.symbols)} ({book}, {result.n_long}/leg)"
            ),
            summary_rows=[
                ("OOS Sharpe", f"{result.metrics['sharpe']:.3f}"),
                (
                    "Sharpe 95% CI",
                    f"[{result.sharpe_ci.lower:.2f}, {result.sharpe_ci.upper:.2f}]",
                ),
                ("CAGR", f"{result.metrics['cagr']:.3f}"),
                ("Max drawdown", f"{result.metrics['max_drawdown']:.3f}"),
                ("Probabilistic Sharpe", f"{result.psr:.3f}"),
                ("Book", f"{book}, {result.n_long} names/leg"),
                ("Periods", str(result.n_periods)),
            ],
            output_path=path,
        ),
    )
    _artifacts.write_manifest(rdir, manifest)
    typer.echo(
        f"cross-sectional [{', '.join(result.symbols)}] ({book}, {result.n_long}/leg) -> "
        f"run {run_id}: OOS Sharpe {result.metrics['sharpe']:.3f} "
        f"[{result.sharpe_ci.lower:.2f}, {result.sharpe_ci.upper:.2f}], "
        f"CAGR {result.metrics['cagr']:.3f}, PSR {result.psr:.3f} "
        f"over {result.n_periods} periods; manifest at {rdir / 'manifest.json'}"
    )
    held.announce()
