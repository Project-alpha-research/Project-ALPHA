"""A rule test's identity is built only from the rows it may read, never from held-back rows.

The stored bar file of a daily store holds rows from 2024-01-01 on, which the project holds back
(`alpha_core.reserve`). A nightly data pull appends or revises those rows. The run id, the test
key and the family of an `alpha test` must not move when that happens, a repeat must stay one
repeat in the trial ledger, and a recheck of a stored run must not report a difference that has
no research cause. A change to a row before the boundary must still move all of them.
"""

from __future__ import annotations

import json
import shutil
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from alpha_cli.spine.deflation import family_count
from alpha_cli.spine.ledger import read_trials
from alpha_cli.spine.recheck import recheck_idea
from alpha_cli.spine.run import run_idea
from alpha_cli.spine.spec import IdeaSpec, load_spec
from alpha_cli.spine.trial_record import row_test_key
from alpha_core import Bar
from alpha_core.reserve import RESERVED_DAY
from alpha_data.store import ParquetStore
from tests.fixtures.forecast_fixtures import store_bars


def _walk(last: date) -> list[Bar]:
    """Weekday bars of a noisy walk from 2023-01-02 up to ``last``."""
    rng = np.random.default_rng(3)
    days = [date(2023, 1, 2) + timedelta(days=i) for i in range(500)]
    days = [d for d in days if d.weekday() < 5]
    close = 100.0 * np.cumprod(1.0 + 0.0004 + rng.normal(0.0, 0.012, len(days)))
    out: list[Bar] = []
    for i, d in enumerate(days):
        prev = float(close[i - 1]) if i else float(close[0])
        c = float(close[i])
        stamp = datetime.combine(d, time.min, tzinfo=UTC)
        out.append(
            Bar(
                symbol="SPY",
                ts=stamp,
                open=round(prev, 2),
                high=round(max(prev, c) * 1.003, 2),
                low=round(min(prev, c) * 0.997, 2),
                close=round(c, 2),
                volume=1_000.0,
            )
        )
    return [bar for bar in out if bar.ts.date() <= last]


SHORT = _walk(date(2024, 1, 31))  # 21 held-back bars
LONG = _walk(date(2024, 3, 29))  # 62 held-back bars
FIRST_HELD = next(i for i, bar in enumerate(SHORT) if bar.ts.date() >= RESERVED_DAY)


def _poke(bar: Bar, factor: float) -> Bar:
    close = bar.close * factor
    return bar.model_copy(update={"close": close, "high": max(bar.high, close)})


def _idea() -> IdeaSpec:
    return load_spec(None, rule="ma_cross", param=["fast=5", "slow=20"], asset=["SPY"])


def _home(root: Path, bars: list[Bar]) -> Path:
    store_bars(root, bars)
    ParquetStore(root / "store").write_provenance(
        "SPY", source="alpaca", adapter_version="1", parser_version="1"
    )
    return root


@dataclass(frozen=True)
class Identity:
    run_id: str
    test_id: str
    key: tuple[Any, ...] | None
    family: str


def _identity(home: Path) -> Identity:
    out = run_idea(_idea(), home=home, quick=True)
    row = out["results"][0]
    assert row["error"] is None, row["error"]
    ledger = read_trials(home)[-1]
    key = row_test_key(ledger)
    return Identity(row["run_id"], out["test_id"], key, f"spine:{ledger['rule']}")


@pytest.fixture(scope="module")
def base(tmp_path_factory: pytest.TempPathFactory) -> Identity:
    return _identity(_home(tmp_path_factory.mktemp("base"), SHORT))


def test_appending_post_boundary_bars_keeps_the_identity(base: Identity, tmp_path: Path) -> None:
    assert _identity(_home(tmp_path, LONG)) == base


def test_revising_a_post_boundary_bar_keeps_the_identity(base: Identity, tmp_path: Path) -> None:
    revised = list(SHORT)
    revised[FIRST_HELD + 3] = _poke(revised[FIRST_HELD + 3], 5.0)
    assert _identity(_home(tmp_path, revised)) == base


def test_a_store_that_gains_its_first_post_boundary_bars_keeps_the_identity(
    tmp_path: Path,
) -> None:
    before = _identity(_home(tmp_path / "a", SHORT[:FIRST_HELD]))
    after = _identity(_home(tmp_path / "b", SHORT))
    assert after == before


def test_revising_a_pre_boundary_bar_changes_the_identity(base: Identity, tmp_path: Path) -> None:
    revised = list(SHORT)
    revised[FIRST_HELD - 5] = _poke(revised[FIRST_HELD - 5], 1.5)
    changed = _identity(_home(tmp_path, revised))
    assert changed.run_id != base.run_id and changed.test_id != base.test_id
    assert changed.key != base.key and changed.family == base.family


def test_the_repeat_is_counted_once_after_a_post_boundary_append(tmp_path: Path) -> None:
    home = _home(tmp_path, SHORT)
    _identity(home)
    store_bars(home, LONG)  # the nightly pull: more held-back bars
    again = run_idea(_idea(), home=home, quick=True)["results"][0]
    rows = read_trials(home)
    assert "repeat" in again["labels"] and again["executed"] is False
    assert len(rows) == 2
    assert rows[1]["run_id"] == rows[0]["run_id"]
    count = family_count(home, "ma_cross")
    assert count.prior_trials == 1  # one distinct test, not two


def _recheck(home: Path) -> dict[str, Any]:
    found: dict[str, Any] = recheck_idea(_idea(), home=home, quick=True)["results"][0]["recheck"]
    return found


def test_recheck_matches_after_the_store_only_gained_post_boundary_bars(tmp_path: Path) -> None:
    home = _home(tmp_path, SHORT)
    run_idea(_idea(), home=home, quick=True)
    store_bars(home, LONG)
    found = _recheck(home)
    assert found["computed"] is True and found["match"] is True, found["differences"]


def test_recheck_matches_a_store_that_had_no_held_back_bar_when_it_was_run(
    tmp_path: Path,
) -> None:
    home = _home(tmp_path, SHORT[:FIRST_HELD])
    run_idea(_idea(), home=home, quick=True)
    store_bars(home, SHORT)
    found = _recheck(home)
    assert found["computed"] is True and found["match"] is True, found["differences"]


def _as_stored_before_the_fix(home: Path) -> None:
    """Rewrite the stored run as the older rule wrote it: whole-file fingerprint, count in id."""
    for manifest in (home / "runs").glob("*/manifest.json"):
        data = json.loads(manifest.read_text())
        for row in data["data_health"]["series"]:
            row["source_fingerprint"] = "0" * 64
        manifest.write_text(json.dumps(data))
    shutil.rmtree(home / "figures", ignore_errors=True)


def test_recheck_of_a_run_stored_with_the_older_fingerprint_rule_is_honest(
    tmp_path: Path,
) -> None:
    """Old stored data-health facts never turn into a difference; the numbers are compared."""
    home = _home(tmp_path, SHORT)
    run_idea(_idea(), home=home, quick=True)
    _as_stored_before_the_fix(home)
    store_bars(home, LONG)
    found = _recheck(home)
    assert found["computed"] is True and found["match"] is True, found["differences"]
    assert "older identity rule" in found["identity_note"]
    assert "numbers are compared" in found["identity_note"]


def test_a_run_stored_with_the_current_rule_gets_no_older_rule_note(tmp_path: Path) -> None:
    home = _home(tmp_path, SHORT)
    run_idea(_idea(), home=home, quick=True)
    assert _recheck(home)["identity_note"] is None
