"""The plain-words reading of a stored ML run (`alpha ml run`), and its fold table.

A model run stores no rule-test reading. This module builds the reading from the stored manifest
and files only: the split sentence, assets, model, costs, the out-of-sample Sharpe against
buy-and-hold of the same basket over the same days, and the try count. It states numbers in
context. It gives no verdict, no grade and no advice.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import numpy as np

from alpha_cli.ml_split import split_sentence
from alpha_cli.spine import reserve

COMMAND = "ml_replay"
MODEL = "lightgbm on the alpha158 features (Qlib)"
FOLD_HEADER = "FOLD\tTRAIN\tTEST"


def is_ml_manifest(manifest: Mapping[str, Any]) -> bool:
    return manifest.get("command") == COMMAND


def read_folds(rdir: Path) -> list[dict[str, str]]:
    """The folds stored with the run, as plain days."""
    import polars as pl

    frame = pl.read_parquet(rdir / "folds.parquet").sort("fold")
    return [
        {
            name: str(row[name])[:10]
            for name in ("train_start", "train_end", "test_start", "test_end")
        }
        for row in frame.iter_rows(named=True)
    ]


def fold_table(folds: Sequence[Mapping[str, str]]) -> list[str]:
    """One line per refit: its training days and its test days."""
    return [
        FOLD_HEADER,
        *(
            f"{number}\t{fold['train_start']} to {fold['train_end']}"
            f"\t{fold['test_start']} to {fold['test_end']}"
            for number, fold in enumerate(folds, start=1)
        ),
    ]


def _sharpe(values: Any, periods_per_year: int) -> float | None:
    from alpha_validation import sharpe_ratio

    array = np.asarray(values, dtype=np.float64)
    if array.size < 2 or not np.isfinite(array).all() or float(np.std(array, ddof=1)) == 0.0:
        return None
    return float(sharpe_ratio(array, periods_per_year=periods_per_year))


def benchmark_sharpe(rdir: Path, periods_per_year: int) -> float | None:
    """Sharpe of buy-and-hold of the same basket over the same days, from the stored periods."""
    import polars as pl

    column = pl.read_parquet(rdir / "ml_periods.parquet", columns=["benchmark_return"])
    return _sharpe(column["benchmark_return"].to_numpy(), periods_per_year)


def _number(value: float | None, reason: str) -> str:
    return f"{value:.2f}" if value is not None else f"not computed ({reason})"


def tries_sentence(home: Path) -> str:
    from alpha_cli.spine.ledger import read_trials

    count = sum(
        1
        for row in read_trials(home)
        if row.get("kind") == "ml_run" and "repeat" not in (row.get("labels") or ())
    )
    plural = "try" if count == 1 else "tries"
    return f"Tries counted in family qlib so far: {count} {plural}."


def ml_reading(home: Path, rdir: Path, manifest: Mapping[str, Any]) -> dict[str, Any]:
    """The reading of one stored ML run: a sentence, its numbers, and the fold table."""
    folds = read_folds(rdir)
    ppy = int(manifest["periods_per_year"])
    sharpe = (manifest.get("metrics") or {}).get("sharpe")
    sharpe = (
        float(sharpe) if isinstance(sharpe, int | float) and not isinstance(sharpe, bool) else None
    )
    held = benchmark_sharpe(rdir, ppy)
    costs = manifest["costs"]
    universe = list(manifest["universe"])
    reason = "the returns did not vary"
    lines = [
        split_sentence(folds),
        f"Assets: {len(universe)} assets ({', '.join(universe)}).",
        f"Model: {MODEL}.",
        f"Costs: {costs['fee_bps']} bp fee and {costs['slippage_bps']} bp slippage per trade.",
        f"Out-of-sample Sharpe {_number(sharpe, reason)}; buy-and-hold of the same basket over "
        f"the same days {_number(held, reason)}.",
        tries_sentence(home),
    ]
    block = manifest.get("reserve")
    if isinstance(block, dict):
        lines.append(reserve.describe(block))
    lines.append(str(manifest["label"]) + ".")
    return {
        "kind": "ml_run",
        "sentence": "\n".join(lines),
        "assets": universe,
        "model": MODEL,
        "costs": costs,
        "out_of_sample_sharpe": sharpe,
        "buy_and_hold_sharpe": held,
        "folds": folds,
    }


def ml_facts(run_id: str, reading: Mapping[str, Any]) -> list[dict[str, Any]]:
    """The two headline numbers as facts, each with its basis."""
    basis = "out-of-sample replay with costs, one return per test day"
    return [
        {
            "metric": metric,
            "value": reading[key],
            "run_id": run_id,
            "basis": basis,
            "source": "manifest.json:metrics" if key == "out_of_sample_sharpe" else "ml_periods",
            "labels": [],
            "reason": None if reading[key] is not None else "the returns did not vary",
        }
        for metric, key in (
            ("out_of_sample_sharpe", "out_of_sample_sharpe"),
            ("buy_and_hold_sharpe", "buy_and_hold_sharpe"),
        )
    ]


def run_text(
    result: Mapping[str, Any], reading_text: str, folds: Sequence[Mapping[str, str]]
) -> str:
    """What `alpha ml run` prints: the reading, the fold table, then the try sentence."""
    return "\n".join(
        [
            f"Run {result['run_id']}.",
            reading_text,
            *fold_table(folds),
            str(result["tries_sentence"]),
        ]
    )
