"""Preregistered human rule families through the shared exploratory trial ledger.

Optional instrument defaults: zero fee, 5 bps slippage, 252 periods/year, CASH
(or MARGIN for slash pairs). Every applied default is disclosed in warnings.
Equity uses the engine's pre-fill opening bid marks, including its terminal resample.
"""

from __future__ import annotations

import argparse
import copy
import fcntl
import json
import math
import os
import re
from datetime import UTC, date, datetime
from decimal import ROUND_FLOOR, Decimal
from pathlib import Path
from typing import TYPE_CHECKING, Any

import numpy as np
import polars as pl

from alpha_cli import _runner
from alpha_cli.rdagent_exposure import label_for, read_entries
from alpha_cli.rdagent_factor_eval import (
    AUTHORITY,
    LABEL,
    RESERVED_START,
    _read_ledger,
    canonical,
    exclusive,
    outside_git,
    sha,
)
from alpha_core import Bar, CorporateAction, DataError
from alpha_validation.bootstrap import block_bootstrap_ci
from alpha_validation.proportion import autocorrelation_effective_size, benjamini_hochberg

if TYPE_CHECKING:
    from alpha_backtest.results import BacktestResult

STUDY_AS_OF = "2023-12-31"
HISTORY = 251


class ReservedDataError(DataError):
    """Data dated on or after the reserved start reached the study: never a trial outcome."""


def classify(mean: float, q: float) -> str:
    if q >= 0.10 or mean == 0:
        return "INSUFFICIENT"
    return "SUPPORT" if mean > 0 else "CONTRADICTION"


def family_verdict(outcomes: list[str]) -> str:
    support, contradiction = "SUPPORT" in outcomes, "CONTRADICTION" in outcomes
    if support and contradiction:
        return "mixed"
    if support:
        return "support within scope"
    return "contradiction" if contradiction else "insufficient evidence"


def _settings(spec: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    settings = copy.deepcopy(spec["instruments"])
    warnings = []
    if spec.get("schema") != "AlphaTrendFamilySpecV1":
        warnings.append(f"unknown schema: {spec.get('schema')}")
    if spec.get("written_before_any_result") is not True:
        warnings.append("written_before_any_result is not true")
    for symbol, config in sorted(settings.items()):
        cost = config.setdefault("cost", {})
        for target, key, default in (
            (cost, "fee_bps", 0.0),
            (cost, "slippage_bps", 5.0),
            (config, "periods_per_year", 252),
            (config, "account", "MARGIN" if "/" in symbol else "CASH"),
        ):
            if key not in target:
                target[key] = default
                warnings.append(f"{symbol}: default {key}={default}")
    return settings, warnings


def _rule(spec: dict[str, Any], n: int) -> dict[str, Any]:
    rule: dict[str, Any] = copy.deepcopy(spec["rule"]["rule_spec_template"])
    rule.update(name=f"own-trend-{n}", history=HISTORY)
    for condition in rule["long_when"] + rule["short_when"]:
        for side in ("left", "right"):
            if condition[side].get("lag") == "N":
                condition[side]["lag"] = n
    return rule


def _load(
    symbol: str, config: dict[str, Any], data: Path, inputs: dict[str, Any]
) -> tuple[list[Bar], list[CorporateAction]]:
    match = re.match(r"^data/snapshots/([A-Za-z0-9._-]+)", config["source"])
    if match is None:
        raise DataError(f"invalid snapshot source for {symbol}: {config['source']}")
    snapshot_id = match[1]
    inputs["snapshot_id"] = snapshot_id
    as_of = _runner.parse_as_of(STUDY_AS_OF)
    bars, _ = _runner.load_bars(symbol, data_dir=data, snapshot_id=snapshot_id, as_of=as_of)
    dividends = _runner.load_dividends(symbol, data_dir=data, snapshot_id=snapshot_id, as_of=as_of)
    cutoff = date.fromisoformat(RESERVED_START)
    if any(b.ts.date() >= cutoff for b in bars) or any(
        d.ex_date >= cutoff or d.knowledge_time >= cutoff for d in dividends
    ):
        # A leak is an integrity failure: abort the whole run before the ledger is touched.
        raise ReservedDataError("point-in-time loader returned reserved bars or dividends")
    # A dividend that went ex in 2023 but is paid in 2024 is known in 2023 and stays; the engine
    # never credits a pay date after the last scored session.
    manifest_bytes = (data / "snapshots" / snapshot_id / "manifest.json").read_bytes()
    manifest = json.loads(manifest_bytes)
    inputs.update(
        snapshot_manifest_sha256=sha(manifest_bytes),
        bars_sha256=manifest["symbols"][symbol]["bars_sha256"],
        first_bar=bars[0].ts.isoformat(),
        last_bar=bars[-1].ts.isoformat(),
        number_of_sessions=len(bars),
    )
    if len(bars) < HISTORY + 3:
        raise DataError(f"need at least {HISTORY + 3} bars, got {len(bars)}")
    return bars, dividends


def _books(
    bars: list[Bar],
    dividends: list[CorporateAction],
    config: dict[str, Any],
    rule: dict[str, Any],
    cash: float,
) -> tuple[dict[str, BacktestResult], float, dict[datetime, float]]:
    from nautilus_trader.model.data import QuoteTick
    from nautilus_trader.model.enums import AccountType

    from alpha_backtest.engine import run_backtest
    from alpha_backtest.feed import daily_bar_type, to_execution_feed
    from alpha_backtest.instruments import instrument_for
    from alpha_strategies.rule_strategy import RuleStrategy
    from alpha_strategies.rules import parse_rule_spec

    instrument = instrument_for(bars[0].symbol)
    increment = Decimal(str(instrument.size_increment))
    units = float(
        (Decimal(1000000) / Decimal(str(bars[HISTORY].open)) / increment).to_integral_value(
            rounding=ROUND_FLOOR
        )
        * increment
    )
    bar_type = daily_bar_type(bars[0].symbol)
    feed = to_execution_feed(
        bars,
        bar_type,
        price_precision=instrument.price_precision,
        slippage_bps=config["cost"]["slippage_bps"],
    )
    marks = {
        datetime.fromtimestamp(item.ts_event / 1e9, tz=UTC): float(item.bid_price)
        for item in feed
        if isinstance(item, QuoteTick)
    }
    hold = {
        "version": 1,
        "name": "hold",
        "history": HISTORY,
        "short_when": [],
        "long_when": [{"left": {"source": "close"}, "op": ">", "right": {"value": 0}}],
    }
    account = config["account"].split(",", 1)[0].strip()
    if account not in {"CASH", "MARGIN"}:
        raise DataError(f"invalid account: {account}")
    books = {}
    for name, rules in (("trend", rule), ("hold", hold)):
        strategy = RuleStrategy(
            instrument_id=instrument.id,
            bar_type=bar_type,
            spec=parse_rule_spec(rules),
            fixed_quantity=units,
            fixed_entry_once=name == "hold",
            allow_short=False,
            rebalance_every=1,
            periods_per_year=config["periods_per_year"],
            capital=cash,
        )
        result = run_backtest(
            instrument,
            feed,
            strategy,
            starting_cash=cash,
            account_type=AccountType[account],
            leverage=1,
            fee_bps=config["cost"]["fee_bps"],
            dividends=dividends,
        )
        if (
            result.rejected
            or result.execution_rejections
            or any(order.status in {"DENIED", "REJECTED"} for order in result.order_trace)
        ):
            raise DataError(f"{name}: rejected order")
        books[name] = result
    return books, units, marks


def _dividend_curve(
    timestamps: list[datetime], fills: Any, dividends: list[CorporateAction]
) -> np.ndarray:
    credits = np.zeros(len(timestamps))
    for dividend in dividends:
        shares = sum(
            (1 if f.side == "BUY" else -1) * f.quantity
            for f in fills
            if f.ts.date() < dividend.ex_date
        )
        pay = dividend.pay_date or dividend.ex_date
        for i, ts in enumerate(timestamps):
            if ts.date() >= pay:
                credits[i] += shares * float(dividend.amount or 0)
    return credits


def _series(
    books: dict[str, BacktestResult],
    bars: list[Bar],
    dividends: list[CorporateAction],
    units: float,
    marks: dict[datetime, float],
    config: dict[str, Any],
    cash: float,
) -> tuple[pl.DataFrame, dict[str, Any]]:
    curves = {name: dict(book.equity_curve) for name, book in books.items()}
    ts = sorted(set(curves["trend"]) & set(curves["hold"]))
    ts = [t for t in ts if bars[HISTORY].ts <= t and t.date().isoformat() <= STUDY_AS_OF]
    if ts != [b.ts for b in bars[HISTORY:]]:
        raise DataError("equity timestamps do not cover every scored session")
    hold = books["hold"].fill_trace
    if len(hold) != 1 or hold[0].ts != ts[0] or hold[0].side != "BUY" or hold[0].quantity != units:
        raise DataError("hold book must enter exactly once at the first scored open")
    position_value = units * np.array([marks[t] for t in ts])
    credits = {
        name: _dividend_curve(ts, book.fill_trace, dividends) for name, book in books.items()
    }
    hold_equity = np.array([curves["hold"][t] for t in ts])
    reconstructed = (
        cash
        + position_value
        - units * hold[0].price * (1 + config["cost"]["fee_bps"] / 10000)
        + credits["hold"]
    )
    reconstructed[0] = cash  # first opening sample precedes the entry
    if not np.allclose(hold_equity, reconstructed, rtol=0, atol=0.021):
        raise DataError("hold equity does not reconcile to opening bid marks (2-cent rounding)")
    trend_equity = np.array([curves["trend"][t] for t in ts])
    trend_returns, hold_returns = (
        np.diff(trend_equity) / position_value[:-1],
        np.diff(hold_equity) / position_value[:-1],
    )
    in_market = [
        sum(
            (1 if f.side == "BUY" else -1) * f.quantity
            for f in books["trend"].fill_trace
            if f.ts <= t
        )
        > 0
        for t in ts
    ]
    frame = pl.DataFrame(
        {
            "ts": ts,
            "trend_equity": trend_equity,
            "hold_equity": hold_equity,
            "position_value": position_value,
            "in_market": in_market,
            "e": [None, *(trend_returns - hold_returns)],
            "r_trend": [None, *trend_returns],
            "r_hold": [None, *hold_returns],
        }
    )
    details = {name: {"dividends_credited": float(credit[-1])} for name, credit in credits.items()}
    return frame, details


def _descriptive(returns: np.ndarray, ppy: int) -> dict[str, Any]:
    mean, sd = float(np.mean(returns)), float(np.std(returns, ddof=1))
    wealth = np.r_[1.0, np.cumprod(1 + returns)]
    return {
        "annualised_mean": mean * ppy,
        "volatility": sd * math.sqrt(ppy),
        "sharpe": mean / sd * math.sqrt(ppy) if sd > 0 else None,
        "max_drawdown": float(np.min(wealth / np.maximum.accumulate(wealth) - 1)),
    }


def _measures(
    frame: pl.DataFrame,
    books: dict[str, BacktestResult],
    details: dict[str, Any],
    bars: list[Bar],
    config: dict[str, Any],
    seed: int,
) -> dict[str, Any]:
    from nautilus_trader.model.objects import Money

    from alpha_backtest.instruments import instrument_for

    currency = instrument_for(bars[0].symbol).quote_currency
    e = frame["e"].drop_nulls().to_numpy()
    ppy = config["periods_per_year"]
    if not isinstance(ppy, int) or ppy <= 0:
        raise DataError("periods_per_year must be a positive integer")
    mean, sd = float(np.mean(e)), float(np.std(e, ddof=1))
    n_eff = autocorrelation_effective_size(e)
    se = sd / math.sqrt(n_eff)
    z = mean / se
    ci = block_bootstrap_ci(e, lambda x: float(np.mean(x)), n_resamples=2000, seed=seed)
    metrics = {
        "annualised_excess": mean * ppy,
        "mean": mean,
        "sd": sd,
        "n": len(e),
        "n_eff": n_eff,
        "z": z,
        "p": math.erfc(abs(z) / math.sqrt(2)),
        "se_annual": se * ppy,
        "mde_80_annual": 2.8 * se * ppy,
        "ci_95_annual": {"lower": ci.lower * ppy, "upper": ci.upper * ppy},
        "time_in_market": float(np.mean(frame["in_market"].to_numpy())),
    }
    opens = {b.ts: b.open for b in bars}
    years, mean_v = len(e) / ppy, float(np.mean(frame["position_value"].to_numpy()))
    for name, book in books.items():
        traded = sum(f.quantity * f.price for f in book.fill_trace)
        fees = sum(
            Money(f.quantity * f.price * (config["cost"]["fee_bps"] / 10000), currency).as_double()
            for f in book.fill_trace
        )
        slippage = sum(
            f.quantity * (f.price - opens[f.ts]) * (1 if f.side == "BUY" else -1)
            for f in book.fill_trace
        )
        metrics[name] = {
            **_descriptive(frame[f"r_{name}"].drop_nulls().to_numpy(), ppy),
            **details[name],
            "round_trips_per_year": len(book.trades) / years,
            "annual_turnover": traded / mean_v / years,
            "annual_cost": (fees + slippage) / mean_v / years,
            "trade_count": len(book.fill_trace),
        }
    return metrics


def _trial(
    spec: dict[str, Any],
    digest: str,
    symbol: str,
    n: int,
    config: dict[str, Any],
    data: Path,
    folder: Path,
) -> dict[str, Any]:
    row: dict[str, Any] = {
        "schema": "AlphaRuleTrialResultV1",
        "family_id": spec["family_id"],
        "spec_sha256": digest,
        "instrument": symbol,
        "lookback_N": n,
        "units": None,
        "data_inputs": {},
        "measures": {},
        "p": 1.0,
        "q": 1.0,
        "outcome": "INVALID",
        "rule_spec": {},
    }
    try:
        row["rule_spec"] = _rule(spec, n)
        bars, dividends = _load(symbol, config, data, row["data_inputs"])
        cash = spec["sizing"]["starting_cash"]
        books, units, marks = _books(bars, dividends, config, row["rule_spec"], cash)
        row["units"] = units
        frame, details = _series(books, bars, dividends, units, marks, config, cash)
        seed = int(sha((digest + symbol + str(n)).encode())[:8], 16)
        row["measures"] = _measures(frame, books, details, bars, config, seed)
        row.update(p=row["measures"]["p"], outcome="INSUFFICIENT")
    except ReservedDataError:
        raise
    except Exception as error:  # A failed declared trial still counts; its error is evidence.
        row["error"] = f"{type(error).__name__}: {error}"
        return row
    frame.write_parquet(folder / "series.parquet")
    row["data_inputs"]["scored_start"] = frame["ts"][0].date().isoformat()
    for name, book in books.items():
        (folder / name).mkdir()
        pl.DataFrame(
            [
                {"book": name, "ts": f.ts, "side": f.side, "quantity": f.quantity, "price": f.price}
                for f in book.fill_trace
            ],
            schema={
                "book": pl.String,
                "ts": pl.Datetime("us", "UTC"),
                "side": pl.String,
                "quantity": pl.Float64,
                "price": pl.Float64,
            },
        ).write_parquet(folder / name / "fills.parquet")
    return row


def _ledger_row(
    trial: dict[str, Any],
    spec: dict[str, Any],
    run_dir: Path,
    index: int,
    total: int,
    warnings: list[str],
    entries: Any,
) -> dict[str, Any]:
    symbol, n = trial["instrument"], trial["lookback_N"]
    inputs = trial["data_inputs"]
    relative = f"trials/{symbol.replace('/', '-')}-N{n}/trial.json"
    row = {
        "schema": "AlphaRuleTrialV1",
        "trial_index": index,
        "name": f"own_trend_{n}d_{symbol.replace('/', '-')}",
        "plain_name": f"Hold {symbol} only while its {n}-day trend is up",
        "code_sha256": sha(
            canonical({k: trial[k] for k in ("family_id", "instrument", "rule_spec")})
        ),
        "run_id": run_dir.name,
        "iteration": 0,
        "panel_sha256": inputs.get("bars_sha256"),
        "windows": {
            "history_start": (inputs.get("first_bar") or "")[:10] or None,
            "scored_start": inputs.get("scored_start"),
            "scored_end": (inputs.get("last_bar") or "")[:10] or None,
            "exploration_end": STUDY_AS_OF,
            "reserved_start": RESERVED_START,
        },
        "family_id": spec["family_id"],
        "family_size": len(spec["instruments"]) * len(spec["lookbacks_N"]),
        "total_trials": total,
        "stage": "replay",
        "status": trial["outcome"],
        "p": trial["p"],
        "q": trial["q"],
        "screen": {},
        "replay": trial["measures"],
        "instruments": [symbol],
        "evidence": {"trial": relative, "sha256": sha((run_dir / relative).read_bytes())},
        "label": LABEL,
        "survivorship": [d for d in spec.get("disclosures", []) if "survivorship" in d.lower()],
        "authority": AUTHORITY,
        "warnings": warnings,
    }
    if "error" in trial:
        row["replay"] = {**row["replay"], "error": trial["error"]}
    row["exposure"] = label_for(row, entries)
    return row


def _publish(
    spec: dict[str, Any],
    trials: list[dict[str, Any]],
    warnings: list[str],
    run_dir: Path,
    ledger: Path,
) -> tuple[dict[str, Any], list[int]]:
    qvalues = benjamini_hochberg([t["p"] for t in trials], alpha=0.10).qvalues
    for trial, q in zip(trials, qvalues, strict=True):
        trial["q"] = float(q)
        if trial["outcome"] != "INVALID":
            trial["outcome"] = classify(trial["measures"]["mean"], float(q))
        path = (
            run_dir
            / "trials"
            / f"{trial['instrument'].replace('/', '-')}-N{trial['lookback_N']}"
            / "trial.json"
        )
        exclusive(path, canonical(trial))
    with Path(str(ledger) + ".lock").open("a+b") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        history, entries = _read_ledger(ledger), read_entries(ledger)
        total = len(history) + len(trials)
        rows = [
            _ledger_row(t, spec, run_dir, len(history) + i, total, warnings, entries)
            for i, t in enumerate(trials, 1)
        ]
        outcomes = [t["outcome"] for t in trials]
        family = {
            "schema": "AlphaRuleFamilyResultV1",
            "family_id": spec["family_id"],
            "spec_sha256": sha((run_dir / "spec.json").read_bytes()),
            "trials": trials,
            "qvalues": [float(q) for q in qvalues],
            "verdict": family_verdict(outcomes),
            "counts": {
                s: outcomes.count(s)
                for s in ("SUPPORT", "CONTRADICTION", "INSUFFICIENT", "INVALID")
            },
            "positive_mean_count": sum(t["measures"].get("mean", 0) > 0 for t in trials),
            "family_size": len(trials),
            "ledger_trials_all_families": total,
            "disclosures": spec.get("disclosures", []),
            "warnings": warnings,
            "label": LABEL,
            "authority": AUTHORITY,
        }
        exclusive(run_dir / "family-result.json", canonical(family))
        block = b"".join(canonical(row) for row in rows)
        with ledger.open("ab", buffering=0) as stream:
            if stream.write(block) != len(block):
                raise DataError("short trial ledger write")
            os.fsync(stream.fileno())
    return family, [row["trial_index"] for row in rows]


def _check_location(path: Path) -> None:
    # Inspect the nearest existing ancestor without creating output on an integrity refusal.
    for probe in (path.absolute(), path.resolve()):
        while not probe.parent.exists():
            probe = probe.parent
        outside_git(probe)


def run_family(
    spec_path: Path, spec_sha256: str, data_dir: Path, run_dir: Path, ledger: Path
) -> dict[str, Any]:
    raw = spec_path.read_bytes()
    run_dir, ledger = run_dir.absolute(), ledger.absolute()
    if sha(raw) != spec_sha256:
        raise DataError("spec sha256 mismatch")
    if run_dir.exists() or run_dir.is_symlink():
        raise DataError("run directory already exists")
    for path in (run_dir, ledger):
        _check_location(path)
    spec = json.loads(raw)
    settings, warnings = _settings(spec)
    started = datetime.now(UTC).isoformat()
    run_dir.mkdir(parents=True)
    ledger.parent.mkdir(parents=True, exist_ok=True)
    exclusive(run_dir / "spec.json", raw)
    exclusive(run_dir / "spec.sha256", (spec_sha256 + "\n").encode())
    trials = []
    for symbol, config in sorted(settings.items()):
        for n in spec["lookbacks_N"]:
            folder = run_dir / "trials" / f"{symbol.replace('/', '-')}-N{n}"
            folder.mkdir(parents=True)
            trials.append(_trial(spec, spec_sha256, symbol, n, config, data_dir, folder))
    family, indices = _publish(spec, trials, warnings, run_dir, ledger)
    module = Path(__file__).resolve()
    lock = module.parents[4] / "uv.lock"
    exclusive(
        run_dir / "receipt.json",
        canonical(
            {
                "spec_sha256": spec_sha256,
                "code_fingerprint": sha(module.read_bytes() + lock.read_bytes()),
                "started_at": started,
                "ended_at": datetime.now(UTC).isoformat(),
                "ledger_trial_indices": indices,
            }
        ),
    )
    return family


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    run = sub.add_parser("run")
    for name in ("spec", "data-dir", "run-dir", "ledger"):
        run.add_argument(f"--{name}", type=Path, required=True)
    run.add_argument("--spec-sha256", required=True)
    args = parser.parse_args()
    run_family(args.spec, args.spec_sha256, args.data_dir, args.run_dir, args.ledger)


if __name__ == "__main__":
    main()
