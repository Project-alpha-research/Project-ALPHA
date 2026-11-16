"""Compose the public Sharpe formulas with a spine-only ledger snapshot."""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from alpha_cli.spine.errors import SpineError
from alpha_cli.spine.trial_reader import (
    READER_VERSION,
    LedgerSnapshot,
    LedgerSource,
    read_ledgers,
    trials_for_deflation,
)
from alpha_core import DataError
from alpha_validation.dsr import expected_max_sharpe, probabilistic_sharpe_ratio
from alpha_validation.metrics import FloatSeq


@dataclass(frozen=True)
class FamilyCount:
    family_id: str
    prior_trials: int
    unknown_rows: int
    ledger_rows: int
    reader_version: int


def spine_snapshot(home: Path) -> LedgerSnapshot:
    path = (home / "ledger/trials.jsonl").resolve()
    try:
        return read_ledgers([LedgerSource("spine", str(path))])
    except OSError as exc:
        raise SpineError(
            "LEDGER_UNREADABLE",
            f"Cannot read the trial ledger {path}: {exc}",
            "Fix the file's permissions; never edit or delete ledger rows.",
        ) from exc


def count_snapshot(snapshot: LedgerSnapshot, rule_kind: str) -> FamilyCount:
    family_id = f"spine:{rule_kind}"
    return FamilyCount(
        family_id,
        trials_for_deflation(snapshot, family_id)["family_trials"],
        sum(row.source == "spine" for row in snapshot.unknown),
        snapshot.sources[0].rows,
        READER_VERSION,
    )


def family_count(home: Path, rule_kind: str) -> FamilyCount:
    return count_snapshot(spine_snapshot(home), rule_kind)


def family_sharpes(snapshot: LedgerSnapshot, family_id: str) -> list[float]:
    rows = [
        snapshot.raw_rows[(record.source_file, record.source_line)]
        for record in snapshot.records
        if record.family_id == family_id
        and record.counts_for_deflation
        and not {"repeat", "error"}.intersection(record.labels)
    ]
    return [
        row["oos_sharpe"] / math.sqrt(row["periods_per_year"])
        for row in rows
        if row.get("oos_sharpe") is not None and row.get("periods_per_year")
    ]


def validation_family(home: Path, strategy: str) -> dict[str, Any]:
    """Only registered spine rule strategies can identify a validate run's family."""
    rule = {"ma_crossover": "ma_cross", "breakout": "breakout", "ts_momentum": "tsmom"}.get(
        strategy
    )
    if rule is None:
        return {}
    snapshot = spine_snapshot(home)
    count = count_snapshot(snapshot, rule)
    if not any(record.family_id == count.family_id for record in snapshot.records):
        return {}
    return {
        "trial_sharpes": family_sharpes(snapshot, count.family_id),
        "trial_family": count.family_id,
        "trial_count": count.prior_trials + 1 + count.unknown_rows,
    }


def deflate(returns: FloatSeq, trial_sharpes: Sequence[float], n_trials: int) -> dict[str, Any]:
    """Bailey & López de Prado (2014), via the public expected-max and PSR functions."""
    result: dict[str, Any] = {
        "dsr": None,
        "expected_max_sharpe": None,
        "n_trials_used": max(n_trials, len(trial_sharpes)),
        "trial_sharpe_variance": None,
        "reasons": {},
    }
    if len(trial_sharpes) < 2:
        result["reasons"]["dsr"] = "fewer than two available trial Sharpes"
        return result
    try:
        if not np.all(np.isfinite(trial_sharpes)):
            raise DataError("trial_sharpes must all be finite")
        variance = float(np.var(trial_sharpes, ddof=1))
        sr0 = expected_max_sharpe(variance, result["n_trials_used"])
        result.update(trial_sharpe_variance=variance, expected_max_sharpe=sr0)
        result["dsr"] = probabilistic_sharpe_ratio(returns, benchmark_sr=sr0)
    except DataError as exc:
        result["reasons"]["dsr"] = str(exc)
    return result
