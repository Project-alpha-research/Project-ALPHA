"""Compose automatic diagnostics before immutable validation publication."""

from __future__ import annotations

import json
import math
from dataclasses import replace
from pathlib import Path
from typing import Any

import polars as pl
from pydantic import ValidationError

from alpha_cli import _artifacts, _gauntlet, _runner
from alpha_cli._identity import RunIdentity
from alpha_cli._strategies import surrogate_for
from alpha_cli.artifact_contract import artifact_contract, verify_manifest_artifacts
from alpha_cli.spine import diagnostics as d
from alpha_cli.spine.audit import audit
from alpha_cli.spine.ledger import read_trials
from alpha_cli.spine.macro import macro_window
from alpha_cli.spine.spec import IdeaSpec, Rule
from alpha_core import Bar, CorporateAction, DataError
from alpha_validation.dsr import deflated_sharpe
from alpha_validation.metrics import to_returns


def variant_specs(idea: IdeaSpec, spec: _runner.RunSpec) -> list[tuple[str, str, _runner.RunSpec]]:
    variants = [
        (
            "costs_x2",
            "costs",
            replace(spec, fee_bps=spec.fee_bps * 2, slippage_bps=spec.slippage_bps * 2),
        )
    ]
    for key, value in idea.rule.params.items():
        for factor in (0.8, 1.2):
            neighbour = round(value * factor)
            if neighbour == value:
                continue
            try:
                rule = Rule.model_validate(
                    {"kind": idea.rule.kind, **idea.rule.params, key: neighbour}
                )
            except ValidationError:
                # Invalid neighbours are explicitly excluded by the diagnostic protocol.
                continue
            changed = (
                replace(spec, lookback=rule.params["lookback"], skip=rule.params["skip"])
                if rule.kind == "tsmom"
                else replace(
                    spec,
                    strategy_params=tuple(sorted((k, float(v)) for k, v in rule.params.items())),
                )
            )
            variants.append((f"{key}={neighbour}", "parameter", changed))
    return variants


def trials(
    home: Path, symbol: str, returns: Any, ppy: int, variants: list[dict[str, Any]]
) -> dict[str, Any]:
    rows = read_trials(home)
    sharpes = [
        row["oos_sharpe"] / math.sqrt(row["periods_per_year"])
        for row in rows
        if row.get("symbol") == symbol
        and row.get("oos_sharpe") is not None
        and row.get("periods_per_year")
    ]
    current, reason = d.score(returns, ppy)
    if current is not None:
        sharpes.append(current / math.sqrt(ppy))
    sharpes.extend(v["sharpe"] / math.sqrt(ppy) for v in variants if v["sharpe"] is not None)
    value = None
    if len(sharpes) < 2:
        reason = "fewer than two available trial Sharpes"
    elif reason is None:
        try:
            value = deflated_sharpe(returns, trial_sharpes=sharpes).dsr
        except DataError as exc:
            reason = str(exc)
    return {
        "basis": (
            "walk-forward out-of-sample returns; same-symbol ledger OOS and "
            "this run's full-sample variants, in per-observation Sharpe units"
        ),
        "total_trials": len(rows) + 1,
        "available_sharpes": len(sharpes),
        "dsr": value,
        "reasons": {"dsr": reason} if value is None else {},
    }


def _publish(rdir: Path, document: dict[str, Any], identity: RunIdentity) -> None:
    # Verify the currently published sidecars against their freshly built contract. The shared
    # validation writer subsequently verifies the complete set, including diagnostics, before
    # publishing the completion marker. Failed verification never produces a completed run.
    candidate = {
        "run_id": identity.run_id,
        **identity.manifest_fields(),
        "schema_version": 3,
        "artifact_contract_version": 3,
        "artifacts": artifact_contract(rdir),
    }
    verify_manifest_artifacts(rdir, candidate)
    check = next(item for item in document["audit"] if item["check"] == "artifacts-intact")
    check.update(
        status="PASS",
        detail=(
            "Pre-publication sidecar contract verified; completion requires "
            "verification of the complete manifest artifact set."
        ),
    )
    _artifacts.publish_artifact(
        rdir / "diagnostics.json",
        lambda path: path.write_text(
            json.dumps(document, sort_keys=True, indent=2, allow_nan=False), encoding="utf-8"
        ),
    )


def write_diagnostics(
    idea: IdeaSpec,
    bars: list[Bar],
    dividends: list[CorporateAction],
    spec: _runner.RunSpec,
    out: _gauntlet.GauntletOutput,
    identity: RunIdentity,
    home: Path,
    result: dict[str, Any],
) -> None:
    rdir = Path(result["run_dir"])
    # These exact sidecars are reused by write_validation_run's idempotent publication seam.
    _artifacts.write_run_sidecars(
        rdir,
        equity=list(zip(out.oos.oos_timestamps, out.oos.oos_equity.tolist(), strict=True)),
        trades=out.result.trades,
        trace_result=out.result,
        periods_per_year=spec.periods_per_year,
    )
    full = _runner.run_full_backtest(bars, spec, dividends=dividends)
    dates, equity = zip(*full.equity_curve, strict=True)
    closes = {bar.ts: float(bar.close) for bar in bars}
    market = [closes[date] for date in dates]
    ppy = spec.periods_per_year
    document: dict[str, Any] = {
        "full_sample": d.performance(equity, ppy, "full-sample backtest"),
        "benchmark": d.performance(market, ppy, "buy and hold, same bars, no costs; close prices"),
    }
    states = {item.ts: item.net_exposure for item in full.portfolio_state_trace}
    exposure = (
        sum(states[date] > 0 for date in dates) / len(dates)
        if set(dates) <= states.keys()
        else None
    )
    document["full_sample"].update(trades=len(full.trades), exposure=exposure)
    if exposure is None:
        document["full_sample"]["reasons"]["exposure"] = (
            "portfolio state trace does not cover every bar"
        )
    excess, reasons = {}, {}
    for metric in ("total_return", "cagr", "sharpe", "max_drawdown"):
        strategy, benchmark = document["full_sample"][metric], document["benchmark"][metric]
        excess[metric] = (
            strategy - benchmark if strategy is not None and benchmark is not None else None
        )
        if excess[metric] is None:
            reasons[metric] = "strategy or benchmark metric is unavailable"
    document["benchmark"].update(strategy_minus_benchmark={**excess, "reasons": reasons})
    document["drawdowns"] = d.drawdowns(equity, market, dates)
    document["by_year"] = d.yearly(equity, market, dates)
    document["concentration"] = d.concentration([trade.realized_pnl for trade in full.trades])
    variants = []
    for name, kind, changed in variant_specs(idea, spec):
        result["variants_evaluated"] += 1
        rerun = _runner.run_full_backtest(bars, changed, dividends=dividends)
        variants.append(
            {
                "name": name,
                "kind": kind,
                **d.performance(
                    [v for _, v in rerun.equity_curve], ppy, "full-sample engine re-run"
                ),
            }
        )
    document["sensitivity"] = {
        "basis": "full-sample engine re-runs on the same loaded bars",
        "variants": variants,
    }
    document["variants_evaluated"] = result["variants_evaluated"]
    returns = to_returns([float(bar.close) for bar in bars])
    weights, costs = surrogate_for(spec).weights_and_costs(returns)
    document["delay"] = d.delay(returns, weights, costs, ppy)
    document["trials"] = trials(home, bars[0].symbol, out.oos.oos_returns, ppy, variants)
    document["macro_window"] = macro_window(home, document["drawdowns"]["episodes"])
    document["flags"] = d.flags(document)
    document["audit"] = audit(
        pl.read_parquet(rdir / "decision_trace.parquet"),
        pl.read_parquet(rdir / "orders.parquet"),
        pl.read_parquet(rdir / "fills.parquet"),
        {bar.ts: (float(bar.low), float(bar.high)) for bar in bars},
        fee=spec.fee_bps,
        slippage=spec.slippage_bps,
        trades=len(out.result.trades),
        years=(bars[-1].ts - bars[0].ts).total_seconds() / (365.25 * 86400),
        labels=result["labels"],
        benchmark=all(document["benchmark"][key] is not None for key in excess),
        variants=len(variants),
    )
    _publish(rdir, document, identity)
