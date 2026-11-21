"""Setup find, study, trade and recheck with a context series as a condition (synthetic data)."""

from __future__ import annotations

import json
from collections.abc import Sequence
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import numpy as np
import polars as pl
import pytest

from alpha_cli import setup_cmds
from alpha_cli.spine import setup_find
from alpha_cli.spine.errors import SpineError
from alpha_cli.spine.setup_recheck import recheck_study, recheck_trade
from alpha_cli.spine.setup_study import run_study
from alpha_cli.spine.setup_trade import run_trade
from alpha_core.reserve import RESERVED_DAY
from alpha_data.context import cftc_cot
from alpha_data.store import ParquetStore
from tests.unit._context_attach_support import CODE, cot_rows, store_cot

START = date(2020, 1, 1)
SPEC = """[setup]
name = "Synthetic positioning"
idea = "What follows extreme positioning"
timeframe = "1D"
assets = ["SPY"]
event = "volume == 1"
[context]
pos = "cot_nc_net_oi@13874A"
[filters]
extreme = "pos > 0.5"
[exit]
time_bars = 10
[study]
horizons = [1, 5]
primary = 5
"""


@pytest.fixture(autouse=True)
def _no_sheets(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(setup_cmds, "draw_sheet", lambda rows, **kw: b"png")


def seed_bars(home: Path, days: int = 1500, symbol: str = "SPY", start: date = START) -> None:
    """Calendar-day bars from `start`; an event bar every 15 days."""
    rng = np.random.default_rng(7)
    close = 100.0 * np.cumprod(1.0 + rng.normal(0.0004, 0.01, days))
    frame = pl.DataFrame(
        {
            "ts": [
                datetime.combine(start + timedelta(days=i), datetime.min.time(), UTC)
                for i in range(days)
            ],
            "open": close,
            "high": close * 1.01,
            "low": close * 0.99,
            "close": close,
            "volume": [1.0 if i % 15 == 0 else 0.0 for i in range(days)],
        }
    )
    store = ParquetStore(home / "store")
    store.write_bars(symbol, frame)
    store.write_provenance(symbol, source="alpaca", adapter_version="1", parser_version="1")


def weeks(first: date, count: int, skip: Sequence[int] = ()) -> list[dict[str, Any]]:
    """Weekly reports: value 0.7 for two weeks of every six, otherwise 0.3."""
    rows = []
    for n in range(count):
        if n in skip:
            continue
        rows.append(dict(report_date=first + timedelta(weeks=n), nl=700 if n % 6 < 2 else 300))
    return rows


def seed(
    home: Path, first: date = date(2020, 3, 3), count: int = 200, skip: Sequence[int] = ()
) -> None:
    seed_bars(home)
    store_cot(home, cot_rows(weeks(first, count, skip)))


def spec_path(home: Path, text: str = SPEC) -> Path:
    path = home / "spec.toml"
    path.write_text(text)
    return path


def find(home: Path, text: str = SPEC) -> dict[str, Any]:
    return setup_cmds.run_find(spec_path(home, text), home=home)


def test_the_counts_are_honest_and_before_the_reserved_day(tmp_path: Path) -> None:
    seed(tmp_path, skip=range(60, 64))  # a four-week gap: values older than 17 days are stale
    result = find(tmp_path)
    asset = result["assets"][0]
    info = asset["context"]
    assert info["series"] == {"pos": "cot_nc_net_oi@13874A"}
    assert info["recipe"] == "context-derived-v1"
    assert info["span"]["first"] >= "2020-03-06" and info["span"]["last"] < str(RESERVED_DAY)
    count = info["conditions"]["filter:extreme"]
    assert 0 < count["spells"] < count["true_bars"]  # weekly values repeat on daily bars
    assert info["null_by_reason"]["pos"]["not-yet-known"] > 0
    assert info["null_by_reason"]["pos"]["stale"] > 0
    assert asset["rejected_by_reason"].get("context-stale", 0) > 0
    assert "short-context-history" not in result["labels"]
    assert "reserved-period-held-back" in result["labels"]
    assert "The condition data covers 2020-03 to 2023-12" in setup_cmds._text(result)
    candidates = pl.read_parquet(Path(result["folder"]) / "candidates.parquet")
    assert max(candidates["event_ts"].to_list()) < datetime.combine(
        RESERVED_DAY, datetime.min.time(), UTC
    )


def test_a_short_context_history_is_labelled_in_plain_words(tmp_path: Path) -> None:
    seed(tmp_path, first=date(2022, 6, 7), count=80)
    result = find(tmp_path)
    assert "short-context-history" in result["labels"]
    assert "a short history" in setup_cmds._text(result)
    assert "clear of chance" not in setup_cmds._text(result)


def test_the_same_find_twice_has_one_identity_and_no_redraw(tmp_path: Path) -> None:
    seed(tmp_path)
    first, second = find(tmp_path), find(tmp_path)
    assert first["find_id"] == second["find_id"]
    assert first["executed"] is True and second["executed"] is False
    assert second["totals"] == first["totals"]


def test_rows_after_the_reserve_do_not_change_the_identity_or_the_reading(tmp_path: Path) -> None:
    seed(tmp_path, count=215)  # reports already run past 2023-12 into 2024
    before = find(tmp_path)
    more = cot_rows(weeks(date(2020, 3, 3), 260))
    store_cot(tmp_path, more)  # same rows plus later ones, as a weekly pull would add
    after = find(tmp_path)
    assert after["find_id"] == before["find_id"]
    assert (
        after["assets"][0]["context"]["used_rows_sha256"]
        == before["assets"][0]["context"]["used_rows_sha256"]
    )
    assert after["totals"] == before["totals"]


def test_nothing_after_the_boundary_is_read(tmp_path: Path) -> None:
    seed(tmp_path)
    rows = weeks(date(2020, 3, 3), 200)
    loud = [dict(r, nl=900 if r["report_date"] >= RESERVED_DAY else r["nl"]) for r in rows]
    other = tmp_path / "other"
    seed_bars(other)
    store_cot(other, cot_rows(loud))
    one, two = find(tmp_path), find(other, SPEC)
    assert (
        one["assets"][0]["context"]["used_rows_sha256"]
        == two["assets"][0]["context"]["used_rows_sha256"]
    )
    assert one["find_id"] == two["find_id"]
    assert one["assets"][0]["context"]["span"]["last"] < str(RESERVED_DAY)


def test_study_and_trade_carry_the_context_and_recheck_matches(tmp_path: Path) -> None:
    seed(tmp_path)
    found = find(tmp_path)
    study = run_study(found["find_id"], home=tmp_path)
    assert study["context"]["SPY"]["conditions"]["filter:extreme"]["spells"] > 0
    assert "The condition data covers" in study["reading"]
    assert "clear of chance" not in study["reading"].replace("not clear of chance", "")
    again = recheck_study(found["find_id"], home=tmp_path)["recheck"]
    assert again["match"] is True
    trade = run_trade(found["find_id"], home=tmp_path)
    assert "The condition data covers" in trade["reading"]
    assert recheck_trade(found["find_id"], home=tmp_path)["recheck"]["match"] is True
    assert run_study(found["find_id"], home=tmp_path)["executed"] is False


def test_a_changed_table_that_changes_used_rows_is_changed_data(tmp_path: Path) -> None:
    seed(tmp_path)
    found = find(tmp_path)
    table = cftc_cot.table_path(tmp_path, CODE)
    table.unlink()
    table.with_suffix(".json").unlink()
    store_cot(tmp_path, cot_rows(weeks(date(2020, 3, 3), 200, skip=[40])))
    with pytest.raises(SpineError) as caught:
        run_study(found["find_id"], home=tmp_path)
    assert caught.value.payload["code"] == "DATA_CHANGED_SINCE_FIND"
    with pytest.raises(SpineError) as again:
        recheck_study(found["find_id"], home=tmp_path)
    assert again.value.payload["code"] == "DATA_CHANGED_SINCE_FIND"


def test_the_context_is_a_new_test_key_in_the_same_family(tmp_path: Path) -> None:
    seed(tmp_path)
    plain = SPEC.replace('[context]\npos = "cot_nc_net_oi@13874A"\n', "").replace(
        "pos > 0.5", "close > 0"
    )
    one, two = find(tmp_path, plain), find(tmp_path)
    assert one["find_id"] != two["find_id"]
    ids = [run_study(f["find_id"], home=tmp_path) for f in (one, two)]
    assert ids[0]["family"]["family_id"] == ids[1]["family"]["family_id"]
    assert ids[1]["family"]["studies"] == 2
    for level in ("0.4", "0.6", "0.65"):  # each threshold tried is one more test
        last = run_study(find(tmp_path, SPEC.replace("0.5", level))["find_id"], home=tmp_path)
    assert last["family"]["studies"] == 5


def test_an_unknown_series_or_missing_table_fails_with_a_plain_error(tmp_path: Path) -> None:
    seed(tmp_path)
    with pytest.raises(SpineError) as bad:
        find(tmp_path, SPEC.replace("cot_nc_net_oi", "nope"))
    assert bad.value.payload["code"] == "SPEC_INVALID"
    with pytest.raises(SpineError) as missing:
        find(tmp_path, SPEC.replace("13874A", "999999"))
    assert missing.value.payload["code"] == "FIND_FAILED"


def test_a_spec_without_context_gets_no_context_keys(tmp_path: Path) -> None:
    seed_bars(tmp_path)
    plain = SPEC.replace('[context]\npos = "cot_nc_net_oi@13874A"\n', "").replace(
        "pos > 0.5", "close > 0"
    )
    result = find(tmp_path, plain)
    manifest = json.loads((Path(result["folder"]) / "manifest.json").read_text())
    assert "context" not in manifest["assets"][0]
    assert "context_fingerprint" not in manifest["assets"][0]
    assert setup_find.source_keys(manifest["assets"]) == [
        f"SPY={manifest['assets'][0]['source_fingerprint']}"
    ]


def test_random_controls_use_each_asset_own_context_span(tmp_path: Path) -> None:
    """Controls may start and end only where the events could: the asset's own context span."""
    seed_bars(tmp_path)
    seed_bars(tmp_path, days=900, symbol="QQQ", start=date(2021, 1, 1))
    store_cot(tmp_path, cot_rows(weeks(date(2020, 3, 3), 60)))  # stops in 2021, bars run on
    found = find(tmp_path, SPEC.replace('assets = ["SPY"]', 'assets = ["SPY", "QQQ"]'))
    _, manifest, spec = setup_find.load_find(tmp_path, found["find_id"])
    bars, spans = setup_find.study_inputs(tmp_path, manifest, spec)
    for asset in manifest["assets"]:
        span, (start, stop) = asset["context"]["span"], spans[asset["asset"]]
        series = bars[asset["asset"]]
        assert series[start].ts.date().isoformat() == span["first"]
        assert series[stop - 1].ts.date().isoformat() == span["last"]
        assert stop < len(series)
    assert spans["QQQ"][0] == 0  # QQQ bars start after the context: no other asset's start


def test_null_counts_and_valued_bars_add_up_to_the_bar_count(tmp_path: Path) -> None:
    seed(tmp_path, skip=range(60, 64))
    info = find(tmp_path)["assets"][0]["context"]
    assert sum(info["null_by_reason"]["pos"].values()) + info["with_value"]["pos"] == info["bars"]
