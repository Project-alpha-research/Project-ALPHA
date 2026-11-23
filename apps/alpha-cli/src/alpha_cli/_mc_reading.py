"""What a Monte Carlo output says about its source run, and how it reads: numbers, no verdict."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime
from pathlib import Path
from typing import Any

import polars as pl
import typer

from alpha_validation import MonteCarloFamilySummaryV1

_DAILY_UNIT = "one daily account return, flat days included; a trade is not kept whole"
#: What each family resamples. The classical families draw single days of the account-return
#: stream, so a multi-day trade is cut into days and its days are reordered (path risk of the
#: day stream, not of whole trades). Kronos replays whole synthetic market paths instead.
RESAMPLING_UNITS: dict[str, dict[str, str]] = {
    "classical": {
        "iid_empirical": f"{_DAILY_UNIT}; days drawn independently with replacement",
        "regime_switching": f"{_DAILY_UNIT}; days drawn within a two-state volatility chain",
        "student_t": f"{_DAILY_UNIT}; days drawn from a Student-t fitted to the daily returns",
    },
    "kronos": {
        "kronos_synthetic": "a whole synthetic market path, replayed through the engine, so "
        "trades are recomputed on each path",
    },
}
_UNIT_SENTENCE = {
    "classical": f"Resampling unit: {_DAILY_UNIT}.",
    "kronos": "Resampling unit: whole synthetic market paths; trades are recomputed on each path.",
}


def built_from(
    run_id: str, source_dir: Path, equity: Sequence[tuple[datetime, float]], command: str
) -> dict[str, Any]:
    """The run and the out-of-sample period the paths were built from, with the counts.

    ``n_trades`` is ``None`` when the source run stored no trades file; it is never zero then.
    """
    trades_file = source_dir / "trades.parquet"
    return {
        "run_id": run_id,
        "period": "out-of-sample only",
        "first_ts": equity[0][0].isoformat(),
        "last_ts": equity[-1][0].isoformat(),
        "n_returns": len(equity) - 1,
        "n_trades": pl.read_parquet(trades_file).height if trades_file.is_file() else None,
        "resampling_unit": RESAMPLING_UNITS[command],
        "unit_sentence": _UNIT_SENTENCE[command],
    }


def built_from_sentence(source: dict[str, Any]) -> str:
    trades = "" if source["n_trades"] is None else f" and {source['n_trades']} trades"
    return (
        f"Built from run {source['run_id']}, out-of-sample days only, "
        f"{source['first_ts'][:10]} to {source['last_ts'][:10]}: "
        f"{source['n_returns']} daily returns{trades}. {source['unit_sentence']}"
    )


def fit_regime_window(requested: int, train_size: int) -> dict[str, Any]:
    """The causal volatility window that fits the source run's training prefix.

    The boundary is the median of the trailing volatilities inside the training prefix. An
    `alpha test` run trains on its warm-up only, often shorter than the requested window: the
    window is then cut to about half the prefix, so the boundary rests on about half the prefix
    (never on one or two readings). The cut is stated, never silent.
    """
    window = min(requested, max(2, (train_size - 1) // 2))
    observations = train_size - window - 1
    note = (
        None
        if window == requested
        else f"The volatility window was shortened from {requested} to {window} sessions, because "
        f"the run trained on only {train_size} bars; the boundary between calm and busy days "
        f"rests on {observations} readings."
    )
    return {
        "requested_window": requested,
        "causal_window": window,
        "threshold_observations": observations,
        "window_note": note,
    }


def classical_report(
    *,
    source: dict[str, Any],
    summaries: Sequence[MonteCarloFamilySummaryV1],
    n_paths: int,
    window_note: str | None,
) -> str:
    regime_caveats = [
        caveat
        for row in summaries
        if row.family == "regime_switching"
        for caveat in row.caveats
        if caveat.startswith(("Causal states:", "One state holds"))
    ]
    rows = "\n".join(
        f"| {row.family} | not estimable: {row.caveats[0]} |"
        if row.status == "not_estimable"
        else f"| {row.family} | {row.terminal_return_q50:.6f} | {row.maximum_drawdown_q95:.6f} | "
        f"{row.ruin_probability.point:.6f} |"
        for row in summaries
    )
    return (
        "# Classical Monte Carlo path-risk report\n\n"
        "Question: how does the out-of-sample account-return stream behave under alternate "
        "sequencing, causal volatility regimes, and a fitted heavy-tailed marginal model?\n\n"
        f"{built_from_sentence(source)} Paths per family: {n_paths}.\n\n"
        + (f"{window_note}\n\n" if window_note else "")
        + "| Family | Median terminal return | 95th percentile max drawdown | Ruin probability |\n"
        "|---|---:|---:|---:|\n"
        f"{rows}\n\n"
        f"Regime states: {' '.join(regime_caveats)}\n\n"
        "Interpretation: these simulations measure path and scenario risk. They do not establish "
        "edge, replace randomized-price null tests, authorize holdout access, or confer execution "
        "authority. Uncertainty for loss and ruin probabilities is reported with Wilson "
        "intervals.\n\n"
        "Assumptions: IID empirical resampling; a two-state first-order Markov chain with "
        "empirical "
        "state emissions and a training-frozen causal volatility boundary; and IID Student-t draws "
        "fitted to OOS log-account-return location, scale, and tail thickness, then mapped back "
        "to valid simple returns.\n"
    )


_SECONDS_PER_PATH = 0.042  # measured on real data: 10000 paths take about 7 minutes


def time_estimate(paths: int) -> str:
    """The sentence printed before the run starts: how long this many paths take."""
    minutes = max(1, round(paths * _SECONDS_PER_PATH / 60))
    unit = "minute" if minutes == 1 else "minutes"
    return (
        f"Running {paths} paths: this takes about {minutes} {unit}. "
        "Use --paths 10000 for a finer result; that takes about 7 minutes."
    )


def echo_family_lines(
    source: dict[str, Any],
    summaries: Sequence[MonteCarloFamilySummaryV1],
    regime_caveats: tuple[str, ...],
    window_note: str | None,
) -> None:
    typer.echo(built_from_sentence(source))
    if window_note:
        typer.echo(window_note)
    for row in summaries:
        if row.status == "not_estimable":
            typer.echo(f"  {row.family}: not estimable; {row.caveats[0]}")
        else:
            typer.echo(
                f"  {row.family}: "
                f"median terminal {row.terminal_return_q50:+.4f} "
                f"(5%-95% {row.terminal_return_q05:+.4f} to {row.terminal_return_q95:+.4f}), "
                f"drawdown median {row.maximum_drawdown_q50:.4f} "
                f"95th {row.maximum_drawdown_q95:.4f}, "
                f"P(loss) {row.loss_probability.point:.3f} "
                f"[{row.loss_probability.lower:.3f}, {row.loss_probability.upper:.3f}], "
                f"P(ruin, drawdown >= 50%) {row.ruin_probability.point:.3f} "
                f"[{row.ruin_probability.lower:.3f}, {row.ruin_probability.upper:.3f}]"
            )
    if len(regime_caveats) > 1:
        typer.echo(f"regime_switching note: {regime_caveats[1]}")


READS = ("observed_oos.parquet", "path_metrics.parquet")  # the stored files the reading needs


def _percent(value: float) -> str:
    return f"{value * 100:+.2f}%"


def _day(text: str) -> str:
    moment = datetime.fromisoformat(text)
    return f"{moment.day} {moment:%B %Y}"


def window_sentence(source: Mapping[str, Any]) -> str:
    """The first and last date of the replayed window, in plain words."""
    return (
        f"The replay covers {source['n_returns']} trading days, from {_day(source['first_ts'])} "
        f"to {_day(source['last_ts'])}."
    )


def _family_reading(
    row: Mapping[str, Any], real_end: float | None, ends: Sequence[float]
) -> list[str]:
    """Where the real run sits among the simulated paths, with units. Numbers, no verdict."""
    if row.get("status") == "not_estimable":
        return [f"{row['family']}: not estimable; {row['caveats'][0]}"]
    loss = row["loss_probability"]["point"]
    lines = [
        f"{row['family']}: median end value {_percent(row['terminal_return_q50'])}; the middle 90% "
        f"of the {row['n_paths']} simulated paths end between "
        f"{_percent(row['terminal_return_q05'])} and {_percent(row['terminal_return_q95'])}. "
        f"The worst fall from a peak has a median of {abs(row['maximum_drawdown_q50']):.1%} and "
        f"is deeper than {abs(row['maximum_drawdown_q95']):.1%} in 5% of paths. "
        f"{loss:.0%} of paths end with a loss."
    ]
    if real_end is not None and ends:
        below = sum(1 for end in ends if end < real_end) / len(ends)
        lines.append(
            f"The real run ended {_percent(real_end)}, above {below:.0%} of the simulated paths."
        )
    return lines


def stored_lines(rdir: Path, manifest: Mapping[str, Any]) -> list[str]:
    """A stored Monte Carlo run in plain words: its window, then each family against the real one."""
    families = manifest.get("families")
    families = families if isinstance(families, list) else [manifest["family"]]
    observed = pl.read_parquet(rdir / "observed_oos.parquet").sort("step")["equity"].to_list()
    real_end = observed[-1] / observed[0] - 1.0 if len(observed) >= 2 else None
    metrics = pl.read_parquet(rdir / "path_metrics.parquet")
    lines = [window_sentence(manifest["built_from"])]
    for row in families:
        ends = metrics.filter(pl.col("family") == row["family"])["terminal_return"].to_list()
        lines += _family_reading(row, real_end, ends)
    return lines


def echo_stored(rdir: Path, manifest: Mapping[str, Any]) -> None:
    for line in stored_lines(rdir, manifest):
        typer.echo(line)
