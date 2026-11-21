"""`alpha options derived`: plain readings from stored chains, null reasons, JSON."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

from typer.testing import CliRunner

from alpha_cli.main import app
from alpha_data.options import OptionsStore, PricedModel, SyntheticAdapter, VolSurface

RUNNER = CliRunner()
START = date(2023, 3, 1)


def _home(tmp_path: Path, days: int = 3) -> Path:
    store = OptionsStore(tmp_path)
    adapter = SyntheticAdapter(seed=2, surface=VolSurface(), priced=PricedModel(0.0, 0.0))
    for i in range(days):
        store.write(
            adapter.chain("AAA", START + timedelta(days=i)),
            fetched_at=datetime(2030, 1, 1, tzinfo=UTC),
            adapter_version="t",
        )
    return tmp_path


def _run(home: Path, *args: str) -> tuple[int, str]:
    result = RUNNER.invoke(
        app, ["options", "derived", "AAA", *args], env={"ALPHA_DATA_DIR": str(home)}
    )
    return result.exit_code, result.output


def test_json_rows_carry_value_known_from_and_reason(tmp_path: Path) -> None:
    code, out = _run(_home(tmp_path), "--series", "iv30", "--series", "iv_rank_252", "--json")
    assert code == 0
    data = json.loads(out)
    iv = data["series"]["iv30"]
    assert len(iv) == 3 and all(r["value"] is not None for r in iv)
    assert iv[0]["known_from"].startswith("2023-03-01T21:00")
    assert {r["reason"] for r in data["series"]["iv_rank_252"]} == {"warm_up_252"}
    assert data["held_back"] == 0 and "not verdicts" in data["reading"]


def test_plain_text_has_hints_coverage_and_a_null_reason(tmp_path: Path) -> None:
    code, out = _run(_home(tmp_path), "--rows", "2")
    assert code == 0
    assert "iv30: at-the-money implied volatility" in out
    assert "skew_25d: 25-delta put" in out and "term_slope:" in out
    assert "Coverage iv30: 3 of 3 sessions" in out
    assert "null (fewer than 252 sessions stored)" in out
    assert "no realized volatility stored" in out  # no bars stored in this home


def test_unknown_underlying_and_series_fail_loud(tmp_path: Path) -> None:
    code, out = _run(tmp_path)
    assert code != 0 and "no stored options" in out
    code, out = _run(_home(tmp_path / "h"), "--series", "bogus")
    assert code != 0 and "unknown series" in out


def test_realized_vol_is_log_returns_annualised_on_the_last_22_closes(tmp_path: Path) -> None:
    import math
    import statistics

    import pytest

    from alpha_cli.options_cmds import _realized
    from alpha_data.store import ParquetStore
    from alpha_data.timeframe import DAILY, store_dir
    from tests.fixtures.cli_fixtures import seed_store

    seed_store(tmp_path, symbol="AAA", n=60)
    bars = ParquetStore(store_dir(tmp_path, DAILY)).read_bars("AAA")
    closes: list[float] = bars["close"].to_list()
    days: list[datetime] = bars["ts"].to_list()
    points = _realized("AAA", tmp_path)
    last = days[-1].date()
    window = closes[-22:]
    logs = [math.log(b / a) for a, b in zip(window, window[1:], strict=False)]
    expected = statistics.stdev(logs) * math.sqrt(252.0)  # hand-written: 21 log returns, ddof=1
    assert points[last].value == pytest.approx(expected, rel=1e-9, abs=1e-12)
    assert points[last].known_from == datetime.combine(
        last + timedelta(days=1), datetime.min.time(), UTC
    )
    assert days[20].date() not in points  # fewer than 22 closes: no value
    assert _realized("NOPE", tmp_path) == {}


def test_every_series_has_a_hint_and_reason_counts_add_up(tmp_path: Path) -> None:
    from alpha_data.options.derived_params import SERIES

    code, out = _run(_home(tmp_path), "--rows", "1")
    assert code == 0
    for name in SERIES:
        assert f"{name}  {name}: " in out
    assert "Coverage iv_rank_252: 0 of 3 sessions" in out and "warm_up_252 3" in out
    code, raw = _run(_home(tmp_path / "j"), "--rows", "1", "--json")
    data = json.loads(raw)
    for name in SERIES:
        cov = data["coverage"][name]
        assert cov["sessions"] == 3
        assert cov["with_value"] + sum(cov["null_by_reason"].values()) == cov["sessions"]
