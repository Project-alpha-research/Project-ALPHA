"""Rule tests and setups read only bars dated before the reserved day, and say so."""

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import polars as pl
import pytest

from alpha_cli import _runner, results_cmds, setup_cmds
from alpha_cli.spine import reserve, setup_study, setup_trade
from alpha_cli.spine.errors import SpineError
from alpha_cli.spine.ledger import read_trials
from alpha_cli.spine.run import run_idea
from alpha_cli.spine.spec import load_spec
from alpha_cli.toolbox import inputs
from alpha_core import Bar
from alpha_core.corporate import ActionType, CorporateAction
from alpha_core.reserve import RESERVED_DAY
from alpha_data.store import ParquetStore
from tests.fixtures.cli_fixtures import seed_store

HELD_BACK_LABEL = "reserved-period-held-back"
SEEN_LABEL = "reserved-period-seen"
# 2020-01-01 plus 1,600 daily bars ends 2024-05-19; the first 1,461 bars are dated before 2024.
LONG, SHORT = 1600, 1461
EXPECTED_HELD_BACK = LONG - SHORT
SYMBOLS = ["SPY", "BTC/USD"]


@dataclass
class Spy:
    """The latest bar timestamp each loader call returned."""

    latest: list[datetime] = field(default_factory=list)
    dividends: list[int] = field(default_factory=list)

    def reset(self) -> None:
        self.latest.clear()
        self.dividends.clear()


@pytest.fixture
def spy(monkeypatch: pytest.MonkeyPatch) -> Spy:
    seen = Spy()
    load_bars = _runner.load_bars
    load_dividends = _runner.load_dividends

    def bars(*args: Any, **kwargs: Any) -> tuple[list[Bar], str | None]:
        result = load_bars(*args, **kwargs)
        seen.latest.append(max(bar.ts for bar in result[0]))
        return result

    def dividends(*args: Any, **kwargs: Any) -> list[Any]:
        result: list[Any] = load_dividends(*args, **kwargs)
        seen.dividends.append(len(result))
        return result

    monkeypatch.setattr(_runner, "load_bars", bars)
    monkeypatch.setattr(_runner, "load_dividends", dividends)
    return seen


def _store(home: Path, symbol: str, n: int, *, poison: bool, events: bool = False) -> ParquetStore:
    seed_store(home, symbol=symbol, n=n)
    store = ParquetStore(home / "store")
    store.write_provenance(symbol, source="alpaca", adapter_version="1", parser_version="1")
    frame = store.read_bars(symbol)
    # Events sit every 40 bars from bar 100; some of them fall in the held-back years.
    flags = [1.0 if i >= 100 and i % 40 == 0 else 0.0 for i in range(frame.height)]
    frame = frame.with_columns(pl.Series("volume", flags if events else frame["volume"].to_list()))
    if poison:
        late = pl.col("ts").dt.date() >= RESERVED_DAY
        frame = frame.with_columns(
            [
                pl.when(late).then(pl.col(name) * 1000.0).otherwise(pl.col(name)).alias(name)
                for name in ("open", "high", "low", "close")
            ]
        )
    store.write_bars(symbol, frame)
    return store


def _idea(symbol: str) -> Any:
    return load_spec(None, rule="ma_cross", param=["fast=5", "slow=20"], asset=[symbol])


def _spec(home: Path, symbol: str) -> Path:
    path = home / "spec.toml"
    path.write_text(
        '[setup]\nname="Held back"\nidea="Inspect matches"\ntimeframe="1D"\n'
        f'assets=["{symbol}"]\nevent="volume == 1"\n[reference]\nbase="low"\n'
        '[study]\nhorizons=[1,5]\nprimary=5\n[exit]\ntime_bars=2\nstop="5 %"\ntarget="10 %"\n'
    )
    return path


def _assert_before_reserve(spy: Spy) -> None:
    assert spy.latest, "the loader was never called"
    assert all(ts.date() < RESERVED_DAY for ts in spy.latest), spy.latest


@pytest.mark.parametrize("symbol", SYMBOLS)
def test_rule_test_and_tool_read_no_held_back_bar(
    tmp_path: Path,
    spy: Spy,
    symbol: str,
    capsys: pytest.CaptureFixture[str],
) -> None:
    home, cut = tmp_path / "poisoned", tmp_path / "cut"
    _store(home, symbol, LONG, poison=True)
    _store(cut, symbol, SHORT, poison=False)
    out = run_idea(_idea(symbol), home=home, quick=True)["results"][0]
    assert out["error"] is None, out
    _assert_before_reserve(spy)
    printed = capsys.readouterr().out
    sentence = (
        f"Held back {EXPECTED_HELD_BACK} bars from 2024-01-01 on; they are kept for the "
        "owner's confirmation of an idea, so this test did not use them."
    )
    assert printed.count(sentence) == 1
    assert HELD_BACK_LABEL in out["labels"]
    row = read_trials(home)[-1]
    assert datetime.fromisoformat(row["last_ts"]).date() < RESERVED_DAY
    assert HELD_BACK_LABEL in row["labels"]
    manifest = json.loads((Path(out["run_dir"]) / "manifest.json").read_text())
    assert manifest["research_cutoff"] == "2023-12-31"
    assert manifest["spine"]["reserve"] == {
        "reserved_start": "2024-01-01",
        "held_back_bars": EXPECTED_HELD_BACK,
    }
    reference = run_idea(_idea(symbol), home=cut, quick=True)["results"][0]
    assert reference["error"] is None, reference
    assert out["run_id"] != reference["run_id"]  # the cut-off is part of the run identity
    for key in ("oos_sharpe", "dsr", "verdict", "resized_entries", "n_bars"):
        assert out.get(key) == pytest.approx(reference.get(key), rel=1e-9, abs=1e-12) or (
            out.get(key) == reference.get(key)
        )
    other = json.loads((Path(reference["run_dir"]) / "manifest.json").read_text())
    assert manifest["source_fingerprint"] == other["source_fingerprint"]
    assert "reserve" not in other["spine"] and other["research_cutoff"] is None
    spy.reset()
    series = inputs.load_run(home, inputs.resolve(home, out["run_id"]))
    _assert_before_reserve(spy)
    assert series.dates[-1].date() < RESERVED_DAY
    assert spy.dividends  # dividends were read through the same cut-off path


@pytest.mark.parametrize("symbol", SYMBOLS)
def test_setups_read_no_held_back_bar(
    tmp_path: Path,
    spy: Spy,
    symbol: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(setup_cmds, "draw_sheet", lambda *a, **kw: b"png")
    home, cut = tmp_path / "poisoned", tmp_path / "cut"
    _store(home, symbol, LONG, poison=True, events=True)
    _store(cut, symbol, SHORT, poison=False, events=True)
    found = setup_cmds.run_find(_spec(home, symbol), home=home)
    _assert_before_reserve(spy)
    spy.reset()
    study = setup_study.run_study(found["find_id"], home=home)
    _assert_before_reserve(spy)
    spy.reset()
    trade = setup_trade.run_trade(found["find_id"], home=home)
    _assert_before_reserve(spy)
    for output in (found, study, trade):
        assert HELD_BACK_LABEL in output["labels"]
    for output in (study, trade):
        assert str(EXPECTED_HELD_BACK) in output["reserve_sentence"]
        assert output["reserve_sentence"] == reserve.sentence(EXPECTED_HELD_BACK)
    manifest = json.loads((Path(found["folder"]) / "manifest.json").read_text())
    assert manifest["reserve"] == {
        "reserved_start": "2024-01-01",
        "held_back_bars": EXPECTED_HELD_BACK,
    }
    for asset in manifest["assets"]:
        assert datetime.fromisoformat(asset["last_bar"]).date() < RESERVED_DAY
    rows = [r for r in read_trials(home) if r["kind"].startswith("setup_")]
    assert len(rows) == 3 and all(HELD_BACK_LABEL in r["labels"] for r in rows[1:])
    reference = setup_cmds.run_find(_spec(cut, symbol), home=cut)
    assert reference["find_id"] == found["find_id"]
    assert reference["totals"] == found["totals"]
    assert HELD_BACK_LABEL not in reference["labels"]
    same = setup_study.run_study(reference["find_id"], home=cut)
    assert same["horizons"]["5"]["pooled"]["mean"] == pytest.approx(
        study["horizons"]["5"]["pooled"]["mean"], rel=1e-9, abs=1e-12
    )
    assert "reserve_sentence" not in same


def _old_find(home: Path, symbol: str = "SPY") -> dict[str, Any]:
    _store(home, symbol, SHORT, poison=False, events=True)
    return setup_cmds.run_find(_spec(home, symbol), home=home)


@pytest.mark.parametrize("command", ["study", "trade"])
def test_old_find_that_saw_the_period_is_refused_before_any_bar_loads(
    tmp_path: Path, spy: Spy, monkeypatch: pytest.MonkeyPatch, command: str
) -> None:
    monkeypatch.setattr(setup_cmds, "draw_sheet", lambda *a, **kw: b"png")
    found = _old_find(tmp_path)
    path = Path(found["folder"]) / "manifest.json"
    manifest = json.loads(path.read_text())
    assert "reserve" not in manifest
    manifest["assets"][0]["last_bar"] = "2024-02-01T00:00:00+00:00"
    path.write_text(json.dumps(manifest))
    spy.reset()
    run: Callable[..., Any] = setup_study.run_study if command == "study" else setup_trade.run_trade
    with pytest.raises(SpineError) as caught:
        run(found["find_id"], home=tmp_path)
    assert caught.value.payload["code"] == "RESERVED_PERIOD_SEEN"
    assert str(caught.value) == "This find used data from 2024-01-01 on, which is now held back."
    assert caught.value.payload["next"] == (
        "Run alpha setup find again; the new find holds that data back."
    )
    assert spy.latest == []
    assert [r["kind"] for r in read_trials(tmp_path)] == ["setup_find"]


def test_find_with_no_held_back_bars_is_byte_identical(
    tmp_path: Path, spy: Spy, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(setup_cmds, "draw_sheet", lambda *a, **kw: b"png")
    found = _old_find(tmp_path)
    manifest = json.loads((Path(found["folder"]) / "manifest.json").read_text())
    assert "reserve" not in manifest and HELD_BACK_LABEL not in manifest["labels"]
    study = setup_study.run_study(found["find_id"], home=tmp_path)
    assert "reserve_sentence" not in study and HELD_BACK_LABEL not in study["labels"]
    out = run_idea(_idea("SPY"), home=tmp_path, quick=True)["results"][0]
    assert out["error"] is None, out
    stored = json.loads((Path(out["run_dir"]) / "manifest.json").read_text())
    assert stored["research_cutoff"] is None
    assert "reserve" not in stored["spine"]
    assert HELD_BACK_LABEL not in stored["spine"]["labels"]
    assert "reserve" not in read_trials(tmp_path)[-1]
    assert reserve.held_back_count_for(tmp_path, "SPY") == 0


def test_held_back_count_reads_timestamps_only(tmp_path: Path) -> None:
    _store(tmp_path, "SPY", LONG, poison=False)
    assert reserve.held_back_count_for(tmp_path, "SPY") == EXPECTED_HELD_BACK
    assert reserve.record(5) == {"reserved_start": "2024-01-01", "held_back_bars": 5}


def test_older_run_that_saw_the_period_is_labelled_when_read(tmp_path: Path) -> None:
    _store(tmp_path, "SPY", SHORT, poison=False)
    out = run_idea(_idea("SPY"), home=tmp_path, quick=True)["results"][0]
    assert out["error"] is None, out
    path = Path(out["run_dir"]) / "manifest.json"
    manifest = json.loads(path.read_text())
    assert SEEN_LABEL not in results_cmds._show(tmp_path, out["run_id"])["labels"]
    manifest["spine"]["data_period"]["last_ts"] = "2024-02-01T00:00:00+00:00"
    path.write_text(json.dumps(manifest))
    shown = results_cmds._show(tmp_path, out["run_id"])
    assert SEEN_LABEL in shown["labels"]
    assert shown["reserve_sentence"] == reserve.SEEN_SENTENCE
    assert reserve.seen("2024-02-01T00:00:00+00:00", manifest)
    manifest["spine"]["reserve"] = reserve.record(3)
    assert not reserve.seen("2024-02-01T00:00:00+00:00", manifest)
    assert not reserve.seen(datetime(2023, 12, 31, tzinfo=UTC), {})


def _boundary_store(home: Path) -> None:
    """Events on the last kept bar, two and four bars before it, and one complete event."""
    store = _store(home, "SPY", LONG, poison=True)
    frame = store.read_bars("SPY")
    events = {date(2023, 6, 1), date(2023, 12, 27), date(2023, 12, 29), date(2023, 12, 31)}
    flags = [1.0 if ts.date() in events else 0.0 for ts in frame["ts"]]
    store.write_bars("SPY", frame.with_columns(pl.Series("volume", flags)))


def test_boundary_last_kept_bar_has_no_fill_open_trade_is_marked_and_horizon_is_pending(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(setup_cmds, "draw_sheet", lambda *a, **kw: b"png")
    _boundary_store(tmp_path)
    spec = _spec(tmp_path, "SPY")
    # A ten-bar hold with wide exits: the 2023-12-28 entry is still open on the last kept bar.
    spec.write_text(
        spec.read_text().replace(
            'time_bars=2\nstop="5 %"\ntarget="10 %"', 'time_bars=10\nstop="50 %"\ntarget="90 %"'
        )
    )
    found = setup_cmds.run_find(spec, home=tmp_path)
    candidates = pl.read_parquet(Path(found["folder"]) / "candidates.parquet")
    last = candidates.filter(pl.col("event_ts").dt.date() == date(2023, 12, 31))
    assert last["reason"].to_list() == ["no-next-bar"]  # no t+1 bar: no entry
    study = setup_study.run_study(found["find_id"], home=tmp_path)
    outcomes = pl.read_parquet(Path(study["folder"]) / "outcomes.parquet")
    late = outcomes.filter(pl.col("entry_ts").dt.date() == date(2023, 12, 28))
    assert late.filter(pl.col("horizon") == 5)["complete"].to_list() == [False]
    assert late.filter(pl.col("horizon") == 5)["net_return"].to_list() == [None]
    assert outcomes.filter(pl.col("entry_ts").dt.date() == date(2023, 6, 2))["complete"].all()
    trade = setup_trade.run_trade(found["find_id"], home=tmp_path)
    trades = pl.read_parquet(Path(trade["folder"]) / "trades.parquet")
    kept = ParquetStore(tmp_path / "store").read_bars("SPY")
    last_close = kept.filter(pl.col("ts").dt.date() == date(2023, 12, 31))["close"].item()
    open_at_end = trades.filter(pl.col("reason") == "open-at-end")
    assert open_at_end.height >= 1
    assert open_at_end["exit_price"].to_list() == [last_close] * open_at_end.height
    assert (trades["exit_ts"].dt.date() < RESERVED_DAY).all()
    out = run_idea(_idea("SPY"), home=tmp_path, quick=True)["results"][0]
    run_dir = Path(out["run_dir"])
    fills = pl.read_parquet(run_dir / "fills.parquet")
    orders = pl.read_parquet(run_dir / "orders.parquet")
    assert (fills["ts"].dt.date() < RESERVED_DAY).all()
    on_last = orders.filter(pl.col("ts").dt.date() >= date(2023, 12, 31))
    assert on_last["filled_quantity"].sum() == 0  # a decision on the last kept close never fills


def test_point_in_time_action_known_only_in_the_reserved_period_is_not_applied(
    tmp_path: Path,
) -> None:
    """A store that ends before 2024 changes only if it records a split dated in 2024 or later."""
    seed_store(tmp_path, symbol="SPY", n=700)
    store = ParquetStore(tmp_path / "store")
    split = CorporateAction(
        symbol="SPY", action_type=ActionType.SPLIT, ex_date=date(2024, 2, 15), ratio=4.0
    )
    before, _ = _runner.load_bars("SPY", data_dir=tmp_path, as_of=reserve.CUTOFF)
    store.write_actions("SPY", [split])
    after, _ = _runner.load_bars("SPY", data_dir=tmp_path, as_of=reserve.CUTOFF)
    unbounded, _ = _runner.load_bars("SPY", data_dir=tmp_path)
    assert [b.close for b in after] == [b.close for b in before]
    assert unbounded[0].close == pytest.approx(before[0].close / 4.0, rel=1e-9)


def test_held_back_rerun_of_an_old_test_is_one_more_trial_in_the_same_family(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, spy: Spy
) -> None:
    _store(tmp_path, "SPY", LONG, poison=False)
    with monkeypatch.context() as old:  # how a run looked before the hold-back existed
        old.setattr(reserve, "held_back_count", lambda resolved: 0)
        old.setattr(reserve, "CUTOFF", datetime(2999, 1, 1, tzinfo=UTC))
        first = run_idea(_idea("SPY"), home=tmp_path, quick=True)["results"][0]
    assert spy.latest[-1].date() >= RESERVED_DAY
    old_manifest = (Path(first["run_dir"]) / "manifest.json").read_bytes()
    assert SEEN_LABEL in results_cmds._show(tmp_path, first["run_id"])["labels"]
    second = run_idea(_idea("SPY"), home=tmp_path, quick=True)["results"][0]
    rows = read_trials(tmp_path)
    assert [r["kind"] for r in rows] == ["rule_test", "rule_test"]
    assert [r["total_trials"] for r in rows] == [1, 2]
    assert rows[0]["last_ts"] > rows[1]["last_ts"]
    assert first["run_id"] != second["run_id"]
    assert (Path(first["run_dir"]) / "manifest.json").read_bytes() == old_manifest
