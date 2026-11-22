"""`alpha forecast eval` holds the reserved period back; `forecast run` is forward use."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import polars as pl
import pytest
from typer.testing import CliRunner

from alpha_cli import _runner, forecast_cmds
from alpha_cli.main import app
from alpha_core import Bar
from alpha_core.reserve import RESERVED_DAY, RESERVED_INSTANT, RESERVED_START
from alpha_data.store import ParquetStore
from tests.fixtures.cli_fixtures import seed_store

runner = CliRunner()
START = date(2020, 1, 1)
CUT_N = (RESERVED_DAY - START).days  # the first bars stamped before the reserved day
EXTRA = 60
SENTENCE = f"Held back {EXTRA} bars from {RESERVED_START} on"
EVAL = ["forecast", "eval", "SPY", "--model", "fake", "--context", "8", "--horizon", "4"]
EVAL += ["--stride", "40", "--samples", "8"]


class Spy:
    """The latest bar each stored-bar read returned."""

    def __init__(self) -> None:
        self.latest: list[datetime] = []


@pytest.fixture
def spy(monkeypatch: pytest.MonkeyPatch) -> Spy:
    seen = Spy()
    load_bars = _runner.load_bars

    def bars(*args: Any, **kwargs: Any) -> tuple[list[Bar], str | None]:
        result = load_bars(*args, **kwargs)
        seen.latest.append(max(bar.ts for bar in result[0]))
        return result

    monkeypatch.setattr(forecast_cmds, "_load_bars", bars)
    return seen


def _plain(home: Path, n: int, *, poisoned: bool) -> None:
    seed_store(home, symbol="SPY", n=n)
    if not poisoned:
        return
    store = ParquetStore(home / "store")
    late = pl.col("ts").dt.date() >= RESERVED_DAY
    frame = store.read_bars("SPY")
    store.write_bars(
        "SPY",
        frame.with_columns(
            [
                pl.when(late).then(pl.col(c) * 1000.0).otherwise(pl.col(c)).alias(c)
                for c in ("open", "high", "low", "close")
            ]
        ),
    )


def _eval(home: Path, monkeypatch: pytest.MonkeyPatch, *extra: str) -> tuple[str, dict[str, Any]]:
    monkeypatch.setenv("ALPHA_DATA_DIR", str(home))
    result = runner.invoke(app, [*EVAL, *extra])
    assert result.exit_code == 0, result.output
    run_id = result.output.split("-> run ")[1].split(":")[0]
    manifest: dict[str, Any] = json.loads(
        (home / "forecast" / run_id / "manifest.json").read_text()
    )
    return result.output, manifest


def _origins(home: Path, manifest: dict[str, Any]) -> pl.DataFrame:
    return pl.read_parquet(home / "forecast" / manifest["run_id"] / "origins.parquet")


def test_a_poisoned_store_scores_like_a_store_cut_at_the_boundary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, spy: Spy
) -> None:
    _plain(tmp_path / "held", CUT_N + EXTRA, poisoned=True)
    _plain(tmp_path / "cut", CUT_N, poisoned=False)
    _, held = _eval(tmp_path / "held", monkeypatch)
    _, plain = _eval(tmp_path / "cut", monkeypatch)
    assert _origins(tmp_path / "held", held).equals(_origins(tmp_path / "cut", plain))
    assert held["summary"] == plain["summary"]
    assert held["origins"] == plain["origins"]


def test_no_bar_on_or_after_the_boundary_is_read_and_the_sentence_is_printed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, spy: Spy
) -> None:
    _plain(tmp_path, CUT_N + EXTRA, poisoned=True)
    output, manifest = _eval(tmp_path, monkeypatch)
    assert spy.latest and max(spy.latest) < RESERVED_INSTANT
    assert SENTENCE in output
    assert manifest["research_cutoff"] == "2023-12-31"
    assert manifest["reserve"] == {"reserved_start": RESERVED_START, "held_back_bars": EXTRA}
    assert "reserved-period-held-back" in manifest["labels"]


def test_a_store_with_no_held_back_bar_keeps_its_manifest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, spy: Spy
) -> None:
    _plain(tmp_path, CUT_N, poisoned=False)
    output, manifest = _eval(tmp_path, monkeypatch)
    assert "Held back" not in output
    assert manifest["research_cutoff"] is None
    assert "reserve" not in manifest and "labels" not in manifest
    # The run id also hashes the code, so it cannot be pinned across commits; the identity payload
    # is the old one when no bar is held back (research_cutoff None, no hold-back record).
    assert max(spy.latest) == datetime(2023, 12, 31, tzinfo=UTC)


def test_an_earlier_user_cutoff_works_and_a_later_one_is_capped(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, spy: Spy
) -> None:
    _plain(tmp_path, CUT_N + EXTRA, poisoned=True)
    output, manifest = _eval(tmp_path, monkeypatch, "--as-of", "2023-06-30")
    assert "Held back" not in output
    assert manifest["research_cutoff"] == "2023-06-30"
    assert max(spy.latest) <= datetime(2023, 6, 30, 23, 59, 59, tzinfo=UTC)
    spy.latest.clear()
    output, manifest = _eval(tmp_path, monkeypatch, "--as-of", "2024-02-01")
    held = (date(2024, 2, 1) - RESERVED_DAY).days + 1
    assert f"Held back {held} bars" in output
    assert manifest["research_cutoff"] == "2023-12-31"
    assert max(spy.latest) < RESERVED_INSTANT


def _sessions(extra: int) -> list[datetime]:
    """Weekday stamps from 2020-01-01: all those before the reserved day, then `extra` more."""
    days = [START + timedelta(days=i) for i in range((RESERVED_DAY - START).days + 4 * extra)]
    weekdays = [d for d in days if d.weekday() < 5]
    before = sum(1 for d in weekdays if d < RESERVED_DAY)
    return [
        datetime.combine(d, datetime.min.time(), tzinfo=UTC) for d in weekdays[: before + extra]
    ]


def test_forecast_run_is_forward_use_and_still_reads_the_latest_bar(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, spy: Spy
) -> None:
    _plain(tmp_path, CUT_N + EXTRA, poisoned=False)
    monkeypatch.setenv("ALPHA_DATA_DIR", str(tmp_path))
    result = runner.invoke(
        app,
        ["forecast", "run", "SPY", "--model", "fake", "--context", "8", "--horizon", "4"]
        + ["--samples", "8"],
    )
    assert result.exit_code == 0, result.output
    assert max(spy.latest) >= RESERVED_INSTANT
    (rdir,) = (p for p in (tmp_path / "forecast").iterdir() if p.is_dir())
    manifest = json.loads((rdir / "manifest.json").read_text())
    assert manifest["research_cutoff"] is None


def test_forecast_run_records_forward_use_and_keeps_its_id(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _plain(tmp_path, CUT_N + EXTRA, poisoned=False)
    monkeypatch.setenv("ALPHA_DATA_DIR", str(tmp_path))
    payloads: list[dict[str, Any]] = []
    identity_for = _runner.run_identity_for

    def spy(payload: dict[str, Any], **kwargs: Any) -> Any:
        payloads.append(dict(payload))
        return identity_for(payload, **kwargs)

    monkeypatch.setattr(_runner, "run_identity_for", spy)
    result = runner.invoke(
        app,
        ["forecast", "run", "SPY", "--model", "fake", "--context", "8", "--horizon", "4"]
        + ["--samples", "8"],
    )
    assert result.exit_code == 0, result.output
    assert "forward use" in result.output
    # The marker is a manifest field only: the run id payload has the keys it had before.
    (payload,) = payloads
    assert "use" not in payload
    (rdir,) = (p for p in (tmp_path / "forecast").iterdir() if p.is_dir())
    manifest_path = rdir / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    assert manifest["use"] == "forward"
    shown = runner.invoke(app, ["report", rdir.name])
    assert shown.exit_code == 0, shown.output
    assert "use: forward (the reserved period is not held back)" in shown.output
    del manifest["use"]
    manifest_path.write_text(json.dumps(manifest))
    old = runner.invoke(app, ["report", rdir.name])
    assert old.exit_code == 0, old.output
    assert "use: not recorded" in old.output


def test_forecast_eval_report_says_what_was_held_back(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _plain(tmp_path, CUT_N + EXTRA, poisoned=True)
    _, manifest = _eval(tmp_path, monkeypatch)
    shown = runner.invoke(app, ["report", manifest["run_id"]])
    assert shown.exit_code == 0, shown.output
    assert SENTENCE in shown.output
