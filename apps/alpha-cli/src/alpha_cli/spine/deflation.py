"""Compose the public Sharpe formulas with a spine-only ledger snapshot."""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
from scipy import stats

from alpha_cli._artifacts import read_manifest
from alpha_cli._artifacts import run_dir as run_dir_for
from alpha_cli.spine.trial_reader import (
    READER_VERSION,
    LedgerSnapshot,
    spine_snapshot,
    trials_for_deflation,
)
from alpha_cli.spine.trial_record import TestKey, TrialRecord, make_test_key, row_test_key
from alpha_core import DataError
from alpha_validation.dsr import expected_max_sharpe, probabilistic_sharpe_ratio
from alpha_validation.metrics import FloatSeq, sharpe_ratio

# Recorded in every gauntlet DSR summary (outside run-id hashing), so a stored verdict names the
# counting rule it used: same-test repeats collapsed, spread floored below FLOOR_BELOW trials,
# sensitivity variants counted in N but kept out of the spread (version 2).
DEFLATION_RULE = "family-dedup-floor-2"
FLOOR_BELOW = 5
_DAILY = frozenset({252, 365})


@dataclass(frozen=True)
class FamilyCount:
    family_id: str
    prior_trials: int
    unknown_rows: int
    ledger_rows: int
    reader_version: int
    repeats: int = 0
    this_run: int = 1


@dataclass(frozen=True)
class TrialFamily:
    """What the gauntlet needs to deflate by a ledger family, and to say how it counted.

    ``family_count`` is N from the family alone; ``count`` is the N used, larger when the wider
    count of same-asset tests of any rule is larger; ``comparable`` counts the distinct family
    trials of the run's bar size with a Sharpe, this run included; ``repeats`` are same-test
    repeats not counted.
    """

    family_id: str
    family_count: int
    count: int
    comparable: int
    repeats: int = 0


def spine_test_key(
    spec_hash: str,
    symbol: str,
    first_ts: str | None,
    last_ts: str | None,
    periods_per_year: int | None,
    *,
    store: str | None,
    data_id: str | None,
) -> TestKey | None:
    """A spine run's test identity, built the way the reader maps its ledger row."""
    if not symbol:
        return None
    bar_size = "1D" if periods_per_year in _DAILY else None
    return make_test_key(
        spec_hash, (symbol,), first_ts, last_ts, bar_size, store=store, data_id=data_id
    )


def _record_key(snapshot: LedgerSnapshot, record: TrialRecord) -> TestKey | None:
    """The record's test key, read from its raw ledger row (the store and data id live there)."""
    row = snapshot.raw_rows.get((record.source_file, record.source_line))
    return row_test_key(row) if row is not None else None


def _distinct_tests(snapshot: LedgerSnapshot, family_id: str) -> tuple[list[TrialRecord], int]:
    """The family's counted trials, earliest of each same test first; and the repeats dropped.

    Rows without a spec hash or asset cannot be matched and each count as their own test.
    """
    kept: list[TrialRecord] = []
    seen: set[TestKey] = set()
    repeats = 0
    for record in snapshot.records:
        if (
            record.family_id != family_id
            or not record.counts_for_deflation
            or {"repeat", "error"}.intersection(record.labels)
        ):
            continue
        key = _record_key(snapshot, record)
        if key is not None and key in seen:
            repeats += 1
            continue
        if key is not None:
            seen.add(key)
        kept.append(record)
    return kept, repeats


def distinct_asset_tests(
    snapshot: LedgerSnapshot, symbol: str | None
) -> tuple[list[tuple[tuple[str, int], dict[str, Any]]], int, set[TestKey]]:
    """The distinct tests on one asset (every asset when ``symbol`` is None): the rows kept, with
    their ledger keys, the rows not counted, and the test keys seen.

    A row is scored when it has a Sharpe and a bar size. Scored rows of one test key count once;
    a row without a key counts as its own test unless it is labelled repeat (same run id).
    """
    seen: set[TestKey] = set()
    kept: list[tuple[tuple[str, int], dict[str, Any]]] = []
    repeats = 0
    for where, row in snapshot.raw_rows.items():
        scored = row.get("oos_sharpe") is not None and bool(row.get("periods_per_year"))
        # A screen try has no Sharpe; it is a try on this asset all the same (never a zero).
        if not (scored or row.get("kind") == "screen_trial"):
            continue
        if not row.get("symbol") or (symbol is not None and row.get("symbol") != symbol):
            continue
        key = row_test_key(row)
        # A keyed row is matched by its key alone, so a labelled repeat whose earlier row has no
        # Sharpe still counts once; a key-less row is a repeat only by its label (same run id).
        if key in seen or (key is None and "repeat" in (row.get("labels") or ())):
            repeats += 1
            continue
        if key is not None:
            seen.add(key)
        kept.append((where, row))
    return kept, repeats, seen


def same_asset_tests(
    snapshot: LedgerSnapshot, symbol: str, current: TestKey | None = None
) -> tuple[int, int, bool]:
    """Distinct scored tests on one asset (any rule), rows not counted, and if ``current`` is in."""
    kept, repeats, seen = distinct_asset_tests(snapshot, symbol)
    return len(kept), repeats, current is not None and current in seen


def count_snapshot(
    snapshot: LedgerSnapshot, rule_kind: str, current: TestKey | None = None
) -> FamilyCount:
    """The reader's family count less same-test repeats; this run counts 0 if it repeats one."""
    family_id = f"spine:{rule_kind}"
    kept, repeats = _distinct_tests(snapshot, family_id)
    repeated = current is not None and any(_record_key(snapshot, r) == current for r in kept)
    this_run = 0 if repeated else 1
    return FamilyCount(
        family_id,
        trials_for_deflation(snapshot, family_id)["family_trials"] - repeats,
        sum(row.source == "spine" for row in snapshot.unknown),
        snapshot.sources[0].rows,
        READER_VERSION,
        repeats + 1 - this_run,
        this_run,
    )


def family_count(home: Path, rule_kind: str) -> FamilyCount:
    return count_snapshot(spine_snapshot(home), rule_kind)


def _same_bar_size(row_periods: object, periods_per_year: int) -> bool:
    """Daily bars match daily bars on either calendar (252 trading or 365 crypto days)."""
    return row_periods == periods_per_year or (row_periods in _DAILY and periods_per_year in _DAILY)


def family_sharpes(
    snapshot: LedgerSnapshot,
    family_id: str,
    periods_per_year: int,
    current: TestKey | None = None,
) -> list[float]:
    """Per-bar Sharpes of the family's distinct tests that use the run's bar size.

    Each row's annual Sharpe is divided by its own periods per year (per-bar units, as the
    package's formulas require). A per-bar Sharpe of another bar size is on another scale (an
    hourly bar's is far smaller than a daily bar's), so those trials still count in N but never
    enter the variance. A same-test repeat adds no second Sharpe, and the earlier test this run
    repeats is left out because this run's own Sharpe stands for it.
    """
    kept, _ = _distinct_tests(snapshot, family_id)
    rows = [
        snapshot.raw_rows[(record.source_file, record.source_line)]
        for record in kept
        if current is None or _record_key(snapshot, record) != current
    ]
    return [
        row["oos_sharpe"] / math.sqrt(row["periods_per_year"])
        for row in rows
        if row.get("oos_sharpe") is not None
        and row.get("periods_per_year")
        and _same_bar_size(row["periods_per_year"], periods_per_year)
    ]


def validation_family(
    home: Path, strategy: str, periods_per_year: int, run_id: str
) -> dict[str, Any]:
    """Family inputs for an ``alpha validate`` run, fixed at the run's first publication.

    Only registered spine rule strategies identify a family. A run already published keeps the
    family it recorded then: the ledger only grows, and re-running an existing run id must
    reproduce its stored verdict, never recount it against today's bigger family.
    """
    run_dir = run_dir_for(home, run_id)
    if (run_dir / "manifest.json").exists():
        recorded = read_manifest(run_dir).get("dsr") or {}
        if not isinstance(recorded.get("family_id"), str):
            return {}
        return {
            "trial_sharpes": [float(value) for value in recorded["prior_sharpes"]],
            "trial_family": TrialFamily(
                recorded["family_id"],
                int(recorded["family_count"]),
                int(recorded["n_trials"]),
                int(recorded["comparable_trials"]),
                int(recorded["repeats"]),
            ),
        }
    rule = {"ma_crossover": "ma_cross", "breakout": "breakout", "ts_momentum": "tsmom"}.get(
        strategy
    )
    if rule is None:
        return {}
    snapshot = spine_snapshot(home)
    count = count_snapshot(snapshot, rule)
    if not any(record.family_id == count.family_id for record in snapshot.records):
        return {}
    sharpes = family_sharpes(snapshot, count.family_id, periods_per_year)
    n = count.prior_trials + count.this_run + count.unknown_rows
    return {
        "trial_sharpes": sharpes,
        "trial_family": TrialFamily(count.family_id, n, n, len(sharpes) + 1, count.repeats),
    }


def sharpe_sampling_variance(returns: FloatSeq) -> float:
    """Sampling variance of the per-bar Sharpe estimate, with skew and kurtosis.

    The standard error behind ``alpha_validation.dsr.probabilistic_sharpe_ratio`` (Mertens;
    Bailey & López de Prado), squared: (1 - skew·SR + (kurt - 1)/4·SR²) / (T - 1), with the same
    biased skew and non-excess kurtosis. The package does not expose it, so it is computed from
    the same inputs here.
    """
    r = np.asarray(returns, dtype=np.float64)
    std = float(np.std(r, ddof=1)) if r.size >= 2 else 0.0
    if r.size < 2 or not np.all(np.isfinite(r)) or std <= 0.0:
        raise DataError("Sharpe sampling variance needs >= 2 finite, varying returns")
    sr = float(np.mean(r)) / std
    skew = float(stats.skew(r, bias=True))
    kurt = float(stats.kurtosis(r, fisher=False, bias=True))
    variance = 1.0 - skew * sr + (kurt - 1.0) / 4.0 * sr * sr
    if variance <= 0.0:
        raise DataError(f"Sharpe standard error is non-positive (variance={variance})")
    return variance / (r.size - 1)


def deflate(
    returns: FloatSeq,
    trial_sharpes: Sequence[float],
    n_trials: int,
    *,
    variance_floor: float = 0.0,
) -> dict[str, Any]:
    """Bailey & López de Prado (2014), via the public expected-max and PSR functions.

    ``variance_floor`` (0 = none) is the least cross-trial variance used; with a floor, one
    available Sharpe is enough because the floor stands for the spread.
    """
    result: dict[str, Any] = {
        "dsr": None,
        "expected_max_sharpe": None,
        "n_trials_used": max(n_trials, len(trial_sharpes)),
        "trial_sharpe_variance": None,
        "reasons": {},
    }
    if len(trial_sharpes) < 2 and variance_floor <= 0.0:
        result["reasons"]["dsr"] = "fewer than two available trial Sharpes"
        return result
    try:
        if not np.all(np.isfinite(trial_sharpes)):
            raise DataError("trial_sharpes must all be finite")
        sample = float(np.var(trial_sharpes, ddof=1)) if len(trial_sharpes) >= 2 else 0.0
        variance = max(sample, variance_floor)
        sr0 = expected_max_sharpe(variance, result["n_trials_used"])
        result.update(trial_sharpe_variance=variance, expected_max_sharpe=sr0)
        result["dsr"] = probabilistic_sharpe_ratio(returns, benchmark_sr=sr0)
    except DataError as exc:
        result["reasons"]["dsr"] = str(exc)
    return result


def family_deflation(
    returns: FloatSeq, prior_sharpes: Sequence[float], family: TrialFamily
) -> dict[str, Any]:
    """The family-deflated Sharpe probability shared by the verdict and the diagnostics.

    The spread is the family's distinct same-bar-size Sharpes plus this run's own; sensitivity
    variants are full-sample figures of neighbouring settings (another basis, strongly
    correlated), so they count in ``family.count`` but never enter the spread. Below
    ``FLOOR_BELOW`` comparable trials the spread is floored at the sampling variance of this
    run's Sharpe estimate.
    """
    floored = family.comparable < FLOOR_BELOW
    try:
        own = sharpe_ratio(np.asarray(returns, dtype=np.float64), periods_per_year=1)
        floor = sharpe_sampling_variance(returns) if floored else 0.0
    except DataError as exc:
        result = deflate(returns, [], family.count)
        result["reasons"]["dsr"] = str(exc)
        return {**result, "spread_floored": floored}
    result = deflate(returns, [*prior_sharpes, own], family.count, variance_floor=floor)
    return {**result, "spread_floored": floored}
