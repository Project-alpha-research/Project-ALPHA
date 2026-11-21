"""Compose automatic diagnostics before immutable validation publication."""

from __future__ import annotations

import json
import tempfile
from bisect import bisect_right
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import asdict, replace
from pathlib import Path
from typing import TYPE_CHECKING, Any

import polars as pl
from pydantic import ValidationError

from alpha_cli import _artifacts, _gauntlet, _runner
from alpha_cli._identity import RunIdentity
from alpha_cli._strategies import surrogate_for
from alpha_cli.artifact_contract import artifact_contract, verify_manifest_artifacts
from alpha_cli.spine import diagnostics as d
from alpha_cli.spine.audit import ENOUGH_TRADES, audit, cap_sparse_run, plausibility
from alpha_cli.spine.controls import (
    in_sample_rows,
    inverted_summary,
    run_inverted_backtest,
    unavailable_control,
    walk_forward_efficiency,
)
from alpha_cli.spine.deflation import (
    TrialFamily,
    count_snapshot,
    family_deflation,
    family_sharpes,
    same_asset_tests,
    spine_test_key,
)
from alpha_cli.spine.macro import macro_window
from alpha_cli.spine.owner_rule import VARIANTS_NOTE, OwnerRule
from alpha_cli.spine.price_noise import price_noise
from alpha_cli.spine.spec import IdeaSpec, Rule
from alpha_cli.spine.trial_reader import LedgerSnapshot, spine_snapshot
from alpha_cli.spine.trial_record import TestKey
from alpha_cli.validate_cmds import write_validation_sidecars
from alpha_core import Bar, CorporateAction, DataError
from alpha_validation.metrics import to_returns

if TYPE_CHECKING:
    from alpha_backtest.results import BacktestResult


@contextmanager
def staged_run(result: dict[str, Any]) -> Iterator[Path]:
    """Publish diagnostics and their manifest together by renaming a completed directory."""
    final = Path(result["run_dir"])
    final.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".pending-", dir=final.parent) as temporary:
        staged_home = Path(temporary)
        staged = _artifacts.run_dir(staged_home, final.name)
        result["run_dir"] = str(staged)
        try:
            yield staged_home
            if not (staged / "manifest.json").is_file():
                raise DataError("cannot publish a staged run without its manifest")
            staged.rename(final)
        finally:
            result["run_dir"] = str(final)


def variant_specs(idea: IdeaSpec, spec: _runner.RunSpec) -> list[tuple[str, str, _runner.RunSpec]]:
    variants = [
        (
            "costs_x2",
            "costs",
            replace(spec, fee_bps=spec.fee_bps * 2, slippage_bps=spec.slippage_bps * 2),
        )
    ]
    if isinstance(idea.rule, OwnerRule):
        return variants
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
    home: Path,
    symbol: str,
    returns: Any,
    ppy: int,
    variants: list[dict[str, Any]],
    rule_kind: str,
    *,
    snapshot: LedgerSnapshot | None = None,
    current_test: TestKey | None = None,
) -> dict[str, Any]:
    """The trial count and family-deflated Sharpe, from the same inputs as the verdict's ``dsr``."""
    snapshot = snapshot if snapshot is not None else spine_snapshot(home)
    count = count_snapshot(snapshot, rule_kind, current_test)
    # Distinct same-asset tests of any rule (one per test key; repeats not counted): only their
    # number is used, as a wider count of tries when it is larger than the family's.
    same_asset, same_asset_repeats, current_seen = same_asset_tests(snapshot, symbol, current_test)
    current, _ = d.score(returns, ppy)
    variants_scored = sum(v["sharpe"] is not None for v in variants)
    available = same_asset + (current is not None and not current_seen) + variants_scored
    n_trials = count.prior_trials + count.this_run + count.unknown_rows + variants_scored
    prior = family_sharpes(snapshot, count.family_id, ppy, current_test)
    family = TrialFamily(
        count.family_id, n_trials, max(n_trials, available), len(prior) + 1, count.repeats
    )
    value = family_deflation(returns, prior, family)
    return {
        "basis": (
            "walk-forward out-of-sample returns, the same inputs as the verdict's dsr: spread from "
            "the idea family's distinct tests at this bar size and this run (sensitivity variants "
            "count as tries but are full-sample figures, so they stay out of the spread); tries "
            "from the family in the one trial ledger, or the wider count of distinct same-asset "
            "tests of any rule when that is larger; a test is what was tested (spec, asset, data "
            "window, bar size, store, data content), so a re-run after a code change is a repeat "
            "and is not counted"
        ),
        "total_trials": count.ledger_rows + 1,
        "available_sharpes": available,
        **value,
        "family": {
            "family_id": count.family_id,
            "prior_trials": count.prior_trials,
            "this_run": count.this_run,
            "repeats_not_counted": count.repeats,
            "variants_scored": variants_scored,
            "same_asset_tests": same_asset,
            "same_asset_repeats": same_asset_repeats,
            "unknown_rows": count.unknown_rows,
            "n_trials": n_trials,
            "available_sharpes": available,
            "comparable_trials": family.comparable,
            "n_trials_used": value["n_trials_used"],
            "ledger": "ledger/trials.jsonl",
            "ledger_rows": count.ledger_rows,
            "reader_version": count.reader_version,
        },
    }


def full_sample(
    bars: list[Bar], dividends: list[CorporateAction], spec: _runner.RunSpec
) -> tuple[Any, tuple[Any, ...], tuple[float, ...]]:
    """The one full-sample backtest path: the result, its bar dates and its equity curve.

    The diagnostic pass and the investigation tools (``toolbox/``) both read this.
    """
    full = _runner.run_full_backtest(bars, spec, dividends=dividends)
    dates, equity = zip(*full.equity_curve, strict=True)
    return full, dates, equity


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


def _inverted_control(
    bars: list[Bar],
    dividends: list[CorporateAction],
    spec: _runner.RunSpec,
    full: BacktestResult,
    document: dict[str, Any],
) -> dict[str, Any]:
    """The opposite-direction control; a control that cannot run is recorded, never fatal."""
    try:
        inverted = run_inverted_backtest(bars, spec, full, dividends=dividends)
        return inverted_summary(
            document["full_sample"],
            [v for _, v in inverted.equity_curve],
            len(inverted.trades),
            spec.periods_per_year,
            hypothetical=spec.account_type.upper() == "CASH",
            market_return=document["benchmark"]["total_return"],
        )
    except DataError as exc:
        return unavailable_control(document["full_sample"], str(exc))


def _efficiency(out: _gauntlet.GauntletOutput, full: BacktestResult, ppy: int) -> dict[str, Any]:
    """WFE: each fold's recorded train window, read from the full-sample run the folds index.

    The fold bounds index the returns of a series one point per loaded bar, which is the
    full-sample run's equity curve; ``out.result`` is the OOS-only execution and cannot be used.
    """
    timestamps = [ts for ts, _ in full.equity_curve]
    trace = full.decision_trace
    # The first decision is on the close of bar j and fills at the open of bar j + 1; equity at
    # timestamps[j + 1] is sampled before that fill, so returns[j] is flat and returns[j + 1] is
    # the first that can carry a position. bisect_right gives j + 1 (bar stamps precede closes).
    first_tradable = bisect_right(timestamps, trace[0].ts) if trace else 0
    folds = []
    offset = 0
    states = {row.ts: row.net_exposure != 0 for row in out.result.portfolio_state_trace}
    fills = {row.ts for row in out.result.fill_trace}
    for fold in out.oos.folds:
        # OOS folds partition returns; include the starting session's post-fill holding.
        dates = out.oos.oos_timestamps[offset : offset + fold.n_test + 1]
        if not set(dates) <= states.keys():
            raise DataError("OOS portfolio state trace does not cover the fold")
        folds.append(
            {**asdict(fold), "oos_had_trade": any(states[ts] or ts in fills for ts in dates)}
        )
        offset += fold.n_test
    rows = in_sample_rows(
        folds,
        [v for _, v in full.equity_curve],
        ppy,
        first_tradable=first_tradable,
    )
    return walk_forward_efficiency(rows)


def _evidence_reading(out: _gauntlet.GauntletOutput, document: dict[str, Any]) -> None:
    count_trades = len(out.result.trades)
    if count_trades < ENOUGH_TRADES:
        document["labels"] = ["too-few-trades"]
        document["sentence"] = f"Only {count_trades} closed trades: too few to judge."
        document["trials"]["labels"] = ["too-few-trades"]
        document["trials"]["sentence"] = document["sentence"]
    document["closed_oos_trades"] = count_trades
    # The rule-test lane is daily only. Net realised returns include actual execution costs.
    returns_per_trade = [
        trade.realized_pnl / (trade.quantity * trade.entry_price) for trade in out.result.trades
    ]
    document["plausibility"] = plausibility(
        out.report.oos_metrics.get("sharpe"),
        sum(value > 0 for value in returns_per_trade) / count_trades if count_trades else None,
        sum(returns_per_trade) / count_trades if count_trades else None,
        count_trades,
        daily=True,
    )


def _record_periods(
    bars: list[Bar],
    dividends: list[CorporateAction],
    spec: _runner.RunSpec,
    full: BacktestResult,
    out: _gauntlet.GauntletOutput,
    result: dict[str, Any],
) -> tuple[_gauntlet.GauntletOutput, list[float]]:
    basis = "with dividends" if dividends else "price only, no dividends"
    dates = [bar.ts for bar in bars]
    if dates != [ts for ts, _ in full.equity_curve]:
        raise DataError("full equity timestamps must match the loaded bars")
    equity = [value for _, value in full.equity_curve]
    scored_dates = out.oos.oos_timestamps
    start = dates.index(scored_dates[0])
    scored_bars = bars[start : start + len(scored_dates)]
    if [bar.ts for bar in scored_bars] != list(scored_dates):
        raise DataError("scored benchmark must cover the exact scored sessions")
    # The rule decides after min_train closes and can first fill at the following open.
    warmup = spec.min_train
    periods = {}
    markets = {}
    for name, window, values, trades in (
        ("full_history", bars, equity, len(full.trades)),
        ("tradable", bars[warmup:], equity[warmup:], len(full.trades)),
        ("scored", scored_bars, out.oos.oos_equity.tolist(), len(out.result.trades)),
    ):
        market = markets[name] = d.buy_and_hold(window, dividends)
        strategy = d.performance(values, spec.periods_per_year, "engine equity after costs")
        benchmark = d.performance(
            market, spec.periods_per_year, "buy and hold from the first open, no costs"
        )
        periods[name] = {
            "period": name,
            "first_ts": window[0].ts.isoformat(),
            "last_ts": window[-1].ts.isoformat(),
            "price_basis": basis,
            "strategy": {**strategy, "trades": trades},
            "benchmark": benchmark,
            "relative_return": (1 + strategy["total_return"]) / (1 + benchmark["total_return"]) - 1,
        }
    result["periods"] = periods
    _artifacts.write_tradable_comparison(
        Path(result["run_dir"]), dates[warmup:], equity[warmup:], markets["tradable"]
    )
    scored_result = replace(
        out.result,
        benchmark_curve=tuple(zip(scored_dates, markets["scored"], strict=True)),
        benchmark_kind="passive_open_to_open_with_dividends"
        if dividends
        else "passive_open_to_open_price_only",
    )
    return replace(out, result=scored_result), markets["full_history"]


def write_diagnostics(
    idea: IdeaSpec,
    bars: list[Bar],
    dividends: list[CorporateAction],
    spec: _runner.RunSpec,
    out: _gauntlet.GauntletOutput,
    identity: RunIdentity,
    home: Path,
    result: dict[str, Any],
    *,
    snapshot: LedgerSnapshot | None = None,
) -> _gauntlet.GauntletOutput:
    rdir = Path(result["run_dir"])
    full, dates, equity = full_sample(bars, dividends, spec)
    out, market = _record_periods(bars, dividends, spec, full, out, result)
    if "no-diagnostics" in result.get("labels", []):
        return cap_sparse_run(out, result)
    # These exact sidecars are reused by write_validation_run's idempotent publication seam.
    write_validation_sidecars(rdir, bars, spec, out, rule_test=True)
    ppy = spec.periods_per_year
    full_period = result["periods"]["full_history"]
    document: dict[str, Any] = {
        "full_sample": {**full_period["strategy"], "basis": "full-sample backtest"},
        "benchmark": {
            **full_period["benchmark"],
            "basis": "buy and hold, full history, " + full_period["price_basis"],
        },
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
        **({"note": VARIANTS_NOTE} if isinstance(idea.rule, OwnerRule) else {}),
    }
    document["variants_evaluated"] = result["variants_evaluated"]
    document["inverted_signal"] = _inverted_control(bars, dividends, spec, full, document)
    document["walk_forward_efficiency"] = _efficiency(out, full, ppy)
    document["price_noise"] = price_noise(
        bars, dividends, spec, identity.run_id, document["full_sample"]["sharpe"]
    )
    returns = to_returns([float(bar.close) for bar in bars])
    weights, costs = surrogate_for(spec).weights_and_costs(returns)
    document["delay"] = d.delay(returns, weights, costs, ppy)
    # One point-in-time ledger read per run: the verdict and the diagnostics count the same rows.
    snapshot = snapshot if snapshot is not None else spine_snapshot(home)
    current = spine_test_key(
        idea.spec_sha256,
        bars[0].symbol,
        bars[0].ts.isoformat(),
        bars[-1].ts.isoformat(),
        ppy,
        store=result.get("store"),
        data_id=result.get("idea_id"),
    )
    document["trials"] = trials(
        home,
        bars[0].symbol,
        out.oos.oos_returns,
        ppy,
        variants,
        idea.rule.family_key,
        snapshot=snapshot,
        current_test=current,
    )
    family = result["deflation"] = document["trials"]["family"]
    # The verdict's prior trials: the family's same-frequency Sharpes and this run's variants (the
    # gauntlet adds this run's own OOS Sharpe); N is the family count recorded above.
    # The verdict deflates by exactly the diagnostics' family: same Sharpes, same count.
    out = _gauntlet.apply_trial_deflation(
        out,
        family_sharpes(snapshot, family["family_id"], ppy, current),
        TrialFamily(
            family["family_id"],
            family["n_trials"],
            family["n_trials_used"],
            family["comparable_trials"],
            family["repeats_not_counted"],
        ),
    )
    out = cap_sparse_run(out, result)
    _evidence_reading(out, document)
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
    return out
