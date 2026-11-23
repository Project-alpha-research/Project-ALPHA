"""``alpha propfirm run``: Monte-Carlo a strategy against a funded-trader evaluation.

Resamples a strategy's daily return stream (a fresh backtest of SYMBOL, or ``--from-run RUN_ID``)
and walks it through a prop firm's eval -> funded -> payout rules, reporting pass / bust / payout
probabilities and expected payout. ``--firm`` selects an (illustrative, overridable) preset; any
rule flag overrides it. Artifacts land under ``data_dir/propfirm/<run_id>/manifest.json``.

The simulation is end-of-day granularity (the honest limit of a daily-bar backtest); the preset
numbers are approximate, not authoritative firm terms.
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any

import typer

from alpha_cli import _artifacts, _propfirm, _runner
from alpha_cli._artifacts import sanitize
from alpha_core import DataError
from alpha_core.config import AlphaSettings
from alpha_validation import FIRM_PRESETS, PropFirmRules

# The simulated evaluation length when --horizon is not given. No preset states a time limit, so
# a typical evaluation of about 30 trading days is used, never the whole history (over decades a
# trailing drawdown is breached almost surely, which says nothing about one evaluation).
DEFAULT_EVAL_DAYS = 30

propfirm_app = typer.Typer(
    help="Prop-firm Monte Carlo: pass/payout probabilities for a funded-trader evaluation."
)


@propfirm_app.command()
def run(
    symbol: str | None = typer.Argument(
        None, help="symbol to backtest; omit when using --from-run"
    ),
    strategy: str = "ts_momentum",
    firm: str | None = typer.Option(
        None, help="preset: apex | takeprofit | topstep (omit it for the custom rules)"
    ),
    from_run: str | None = typer.Option(
        None, "--from-run", help="reuse a prior run's equity curve"
    ),
    # rule overrides (override the selected preset / the default custom rules)
    account_size: float | None = None,
    profit_target: float | None = None,
    max_drawdown: float | None = None,
    daily_loss: float | None = None,
    profit_split: float | None = None,
    min_trading_days: int | None = None,
    # Monte-Carlo knobs
    n_paths: int = 5000,
    mean_block: float = 5.0,
    horizon: int | None = typer.Option(
        None,
        help=f"trading days per simulated evaluation (default {DEFAULT_EVAL_DAYS}; "
        "no preset sets a time limit)",
    ),
    seed: int | None = None,
    # backtest knobs (used only for a fresh inline backtest of SYMBOL)
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
    param: list[str] | None = None,
    snapshot: str | None = None,
) -> None:
    """Score SYMBOL (or --from-run RUN_ID) against a prop firm and write a verdict manifest."""
    if (symbol is None) == (from_run is None):
        raise typer.BadParameter("provide exactly one of SYMBOL or --from-run RUN_ID")
    _refuse_unknown(firm)
    eval_days = horizon if horizon is not None else DEFAULT_EVAL_DAYS

    settings = AlphaSettings()
    resolved_seed = seed if seed is not None else settings.random_seed
    overrides = {
        name: value
        for name, value in (
            ("account_size", account_size),
            ("profit_target", profit_target),
            ("max_drawdown", max_drawdown),
            ("daily_loss", daily_loss),
            ("profit_split", profit_split),
            ("min_trading_days", min_trading_days),
        )
        if value is not None
    }
    # walk-forward fields are unused by propfirm (it reads the full equity curve); carry coherent
    # defaults so the RunSpec stays one fixed shape.
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
        size_on_equity=size_on_equity,
        halt_drawdown=halt_drawdown,
    )
    # The run id pins only what the result depends on: the source, the firm + overrides, and the MC
    # knobs. A fresh backtest also depends on the strategy/cost spec; --from-run depends on the run.
    payload: dict[str, Any] = {
        "command": "propfirm",
        "firm": firm,
        "overrides": dict(sorted(overrides.items())),
        "n_paths": n_paths,
        "mean_block": mean_block,
        "horizon": eval_days,
        "seed": resolved_seed,
    }
    if from_run is not None:
        payload["from_run"] = from_run
    else:
        payload["symbol"] = symbol
        payload["snapshot"] = snapshot
        payload.update(vars(spec))
    try:
        out = _propfirm.run_propfirm(
            data_dir=settings.data_dir,
            symbol=symbol,
            from_run=from_run,
            spec=spec,
            snapshot=snapshot,
            firm=firm,
            overrides=overrides,
            n_paths=n_paths,
            mean_block=mean_block,
            seed=resolved_seed,
            horizon_days=eval_days,
        )
    except DataError as exc:  # missing run, unknown firm, degenerate returns, bad rule override
        raise typer.BadParameter(str(exc)) from exc

    payload.update(_propfirm.held_identity(out.held))
    identity = _runner.run_identity_for(
        payload,
        source_fingerprint=out.source_fingerprint,
        snapshot_hash=_runner.verified_snapshot_hash(settings.data_dir, snapshot),
    )
    run_id = identity.run_id
    rdir = settings.data_dir / "propfirm" / run_id
    rdir.mkdir(parents=True, exist_ok=True)
    # per-path outcomes BEFORE the manifest (manifest.json is the run-exists marker)
    _artifacts.write_propfirm_paths(
        rdir,
        passed=out.result.path_passed,
        busted=out.result.path_busted,
        days_to_pass=out.result.path_days_to_pass,
        payout=out.result.path_payout,
    )
    manifest = _manifest(out, run_id=run_id, seed=resolved_seed)
    manifest.update(identity.manifest_fields())
    _propfirm.stamp_held(manifest, out.held)
    _artifacts.write_manifest(rdir, manifest)

    label = symbol if symbol is not None else f"run {from_run}"
    _report(
        out,
        label=label,
        run_id=run_id,
        manifest_path=rdir / "manifest.json",
        horizon=horizon,
        stock_or_etf=is_stock_or_etf(settings.data_dir, symbol),
    )


def _refuse_unknown(firm: str | None) -> None:
    """An unknown preset name stops the command before any data is read."""
    if firm is not None and firm not in FIRM_PRESETS:
        typer.echo(
            f"Unknown firm preset {firm!r}. Valid presets: {', '.join(sorted(FIRM_PRESETS))}. "
            "Leave --firm out for the custom rules. Nothing was run."
        )
        raise typer.Exit(2)


def _report(
    out: _propfirm.PropFirmRunResult,
    *,
    label: str,
    run_id: str,
    manifest_path: Path,
    horizon: int | None,
    stock_or_etf: bool = False,
) -> None:
    """The rules used and the evaluation length first, then the rates, in plain words."""
    res = out.result
    days = "n/a" if math.isnan(res.median_days_to_pass) else f"{res.median_days_to_pass:.0f}"
    length = (
        "(set with --horizon)"
        if horizon is not None
        else "(the default when the preset sets no time limit; change it with --horizon)"
    )
    typer.echo(
        "\n".join(
            [
                *rule_lines(out.firm, out.rules),
                f"Evaluation length: {res.horizon_days} trading days {length}.",
            ]
        )
    )
    typer.echo(
        f"propfirm {label} -> run {run_id}: {out.firm}\n"
        f"  pass {res.pass_probability:.1%}, bust {res.bust_probability:.1%}, "
        f"payout {res.payout_probability:.1%}, median days-to-pass {days}\n"
        f"  expected payout {money(res.expected_payout)} over {res.horizon_days} days "
        f"({res.n_paths} paths)\n"
        f"  manifest at {manifest_path}"
        + (out.held.note() if out.held else "")
        + futures_note(out.firm, stock_or_etf)
    )


def money(value: float) -> str:
    """A money value with the minus sign before the currency sign: ``-$5``, never ``$-5``."""
    sign = "-" if round(value) < 0 else ""
    return f"{sign}${abs(value):,.0f}"


def futures_note(firm: str, stock_or_etf: bool) -> str:
    """One sentence when a futures-firm preset is used on a stock or ETF run; else empty."""
    if firm == "custom" or not stock_or_etf:
        return ""
    return (
        f"\nThe {firm} preset is a futures-firm rule set; this run trades a stock or ETF, "
        "so read the rates as a rough guide."
    )


def is_stock_or_etf(data_dir: Path, symbol: str | None) -> bool:
    """True when the stored dataset of ``symbol`` is a stock or ETF (no dataset: a plain ticker)."""
    if symbol is None:
        return False
    from alpha_data.store import ParquetStore

    provenance = ParquetStore(data_dir / "store").read_provenance(symbol)
    dataset = provenance.get("dataset") if provenance is not None else None
    if isinstance(dataset, dict):
        return dataset.get("asset_class") in {"stock", "etf"}
    return "/" not in symbol


def rule_lines(firm: str, rules: PropFirmRules) -> list[str]:
    """The rule set the simulation used, in plain words, before any result."""
    title = (
        "custom rules"
        if firm == "custom"
        else f"{firm} preset, approximate; check the firm's own terms"
    )
    daily = (
        "none" if rules.daily_loss_limit is None else f"${rules.daily_loss_limit:,.0f} (end of day)"
    )
    floor = "trailing the high-water mark" if rules.trailing else "fixed below the start"
    return [
        f"Rules used ({title}):",
        f"  Profit target: ${rules.profit_target:,.0f} on a ${rules.account_size:,.0f} account",
        f"  Daily loss limit: {daily}",
        f"  Maximum loss: ${rules.max_drawdown:,.0f}, {floor}",
        "  Time limit: none set by this preset" if firm != "custom" else "  Time limit: none set",
        f"  Minimum trading days: {rules.min_trading_days}",
    ]


def _manifest(out: _propfirm.PropFirmRunResult, *, run_id: str, seed: int) -> dict[str, Any]:
    """Byte-stable summary manifest (resolved rules + the simulation metrics)."""
    res = out.result
    rules = out.rules
    manifest = {
        "schema_version": 1,
        "run_id": run_id,
        "command": "propfirm",
        "firm": out.firm,
        "source": out.source,
        "rules": {
            "account_size": rules.account_size,
            "profit_target": rules.profit_target,
            "max_drawdown": rules.max_drawdown,
            "trailing": rules.trailing,
            "lock_at_profit": rules.lock_at_profit,
            "daily_loss_limit": rules.daily_loss_limit,
            "min_trading_days": rules.min_trading_days,
            "profit_split": rules.profit_split,
            "min_payout": rules.min_payout,
            "min_funded_days": rules.min_funded_days,
            "eval_fee": rules.eval_fee,
        },
        "metrics": {
            "pass_probability": res.pass_probability,
            "bust_probability": res.bust_probability,
            "payout_probability": res.payout_probability,
            "median_days_to_pass": res.median_days_to_pass,
            "expected_payout": res.expected_payout,
        },
        "n_paths": res.n_paths,
        "horizon_days": res.horizon_days,
        "seed": seed,
    }
    return {k: sanitize(v) for k, v in manifest.items()}
