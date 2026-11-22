"""A quick screen's identity and tries come only from rows before the reserved day (2024-01-01).

A data pull that appends or revises later rows must not make the same screen count again. A
change to a row before the boundary must. The held-back count stays a displayed fact of the result.
"""

from __future__ import annotations

import shutil
from datetime import date
from pathlib import Path
from typing import Any

import polars as pl
import pytest

from alpha_cli import _crypto_panel
from alpha_cli import _hypothesis_scan as scan
from alpha_cli.spine.ledger import read_trials
from alpha_cli.spine.trial_record import row_test_key
from alpha_data.store import ParquetStore
from tests.unit.test_reserve_scan_and_archive import LONG, NAMES, SHORT, _crypto_home, _equity_home

REQUEST: dict[str, Any] = {
    "lane": "equity",
    "symbols": NAMES,
    "universe": None,
    "snapshot": "frozen",
    "as_of": "2024-03-01",
    "signals": ["rev_1m"],
    "horizons": [1, 5],
    "min_names": 5,
    "quantiles": 5,
    "cost_bps": 0.0,
    "category": "linear",
}
CRYPTO = {
    **REQUEST,
    "lane": "crypto",
    "symbols": ["AAAUSDT", "BBBUSDT", "CCCUSDT"],
    "snapshot": None,
    "signals": ["mom_30d"],
    "as_of": "2024-02-20",
    "min_names": 3,
    "quantiles": 3,
}


def _tries(home: Path) -> int:
    """Distinct counted tries; a repeat adds a ledger row that is labelled and not counted."""
    rows = [row for row in read_trials(home) if row["kind"] == "screen_trial"]
    return len({row_test_key(row) for row in rows})


def _rebuild(home: Path, n: int, *, poisoned: bool) -> None:
    shutil.rmtree(home / "store")
    shutil.rmtree(home / "snapshots")
    _equity_home(home, n, poisoned=poisoned)


def test_appending_and_revising_held_back_bars_keeps_the_screen_and_its_tries(
    tmp_path: Path,
) -> None:
    home = _equity_home(tmp_path, SHORT, poisoned=False)
    first = scan.run_hypotheses(home, REQUEST)
    assert first["counted"]["tries_added"] == 10 and "reserve" not in first
    _rebuild(home, LONG, poisoned=False)  # a pull appends held-back bars
    appended = scan.run_hypotheses(home, REQUEST)
    _rebuild(home, LONG, poisoned=True)  # a pull revises held-back prices and adds actions
    revised = scan.run_hypotheses(home, REQUEST)
    for again in (appended, revised):
        assert again["scan_id"] == first["scan_id"]
        assert again["counted"]["tries_added"] == 0
    assert _tries(home) == 10
    assert revised["reserve"]["held_back_bars"] > 0  # still shown, but not part of the identity


def test_revising_a_bar_before_the_boundary_makes_a_new_screen(tmp_path: Path) -> None:
    home = _equity_home(tmp_path, LONG, poisoned=False)
    first = scan.run_hypotheses(home, REQUEST)
    store = ParquetStore(home / "store")
    early = pl.col("ts").dt.date() == date(2023, 6, 1)
    prices = ("open", "high", "low", "close")
    revised = [pl.when(early).then(pl.col(c) * 1.01).otherwise(pl.col(c)).alias(c) for c in prices]
    store.write_bars("AAA", store.read_bars("AAA").with_columns(revised))
    shutil.rmtree(home / "snapshots")
    _equity_home_snapshot(home)
    second = scan.run_hypotheses(home, REQUEST)
    assert second["scan_id"] != first["scan_id"]
    assert second["counted"]["tries_added"] == 10 and _tries(home) == 20


def _equity_home_snapshot(home: Path) -> None:
    from datetime import UTC, datetime

    from alpha_data.snapshot import create_snapshot

    create_snapshot(
        ParquetStore(home / "store"),
        home / "snapshots",
        "frozen",
        NAMES,
        source="alpaca",
        adapter_version="1",
        parser_version="1",
        created_at=datetime(2025, 1, 1, tzinfo=UTC),
    )


def test_crypto_screen_ignores_a_later_pull_of_held_back_rows(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = _crypto_home(tmp_path, date(2023, 12, 31))
    monkeypatch.setattr(_crypto_panel, "bulk_store", lambda _: store)
    first = scan.run_hypotheses(tmp_path, CRYPTO)
    assert first["counted"]["tries_added"] == 6 and "reserve" not in first
    _crypto_home(tmp_path, date(2024, 2, 27))  # new manifests that hold rows after the boundary
    again = scan.run_hypotheses(tmp_path, CRYPTO)
    assert again["scan_id"] == first["scan_id"]
    assert again["counted"]["tries_added"] == 0 and _tries(tmp_path) == 6
    assert again["reserve"]["held_back_rows"] > 0
