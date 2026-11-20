"""`alpha data pull` freezes first, refuses when it cannot, and reports in JSON. No network."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from pathlib import Path

import polars as pl
import pytest
from typer.testing import CliRunner

from alpha_cli.main import app
from alpha_data.adapters.base import FetchResult

runner = CliRunner()


class _Feed:
    """A provider fake whose next answer the test sets."""

    name = "fake"
    version = "1"
    parser_version = "1"
    close = 10.0
    days = [2, 3, 4]
    poison = False

    def fetch(self, symbol: str, start: date, end: date) -> FetchResult:
        close = [type(self).close] * len(self.days)
        if type(self).poison:
            close[-1] = float("nan")
        frame = pl.DataFrame(
            {
                "ts": [datetime(2026, 11, d, tzinfo=UTC) for d in self.days],
                "open": close,
                "high": [c + 1 for c in close],
                "low": [c - 1 for c in close],
                "close": close,
                "volume": [5.0] * len(self.days),
            }
        )
        return FetchResult(symbol, frame, [])


def _flat(text: str) -> str:
    return " ".join(text.replace("│", " ").split())


def _pull(*extra: str) -> tuple[int, str]:
    args = [
        "data",
        "pull",
        "AAA",
        "--source",
        "fake",
        "--start",
        "2026-11-01",
        "--end",
        "2026-11-30",
    ]
    result = runner.invoke(app, [*args, *extra])
    return result.exit_code, _flat(result.output) if result.exit_code else result.output


@pytest.fixture(autouse=True)
def _offline(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ALPHA_DATA_DIR", str(tmp_path))
    monkeypatch.setattr("alpha_cli.data_cmds._ADAPTERS", {"fake": _Feed})
    _Feed.close, _Feed.days, _Feed.poison = 10.0, [2, 3, 4], False


def test_first_pull_takes_no_snapshot_and_a_second_pull_names_one(tmp_path: Path) -> None:
    code, out = _pull("--json")
    first = json.loads(out)
    assert code == 0 and first["snapshot"] is None and first["bars_added"]["count"] == 3
    _Feed.close, _Feed.days = 12.0, [2, 3, 4, 5]
    code, out = _pull("--json")
    second = json.loads(out)
    snap = second["snapshot"]["id"]
    assert code == 0 and (tmp_path / "snapshots" / snap / "manifest.json").is_file()
    assert second["bars_added"] == {"count": 1, "first": "2026-11-05", "last": "2026-11-05"}
    assert second["bars_revised"]["count"] == 3 and second["bars_revised"]["columns"]
    assert f"snapshot {snap}" in second["notice"]
    assert "12.0" not in out
    verified = runner.invoke(app, ["data", "verify", snap])
    assert verified.exit_code == 0, verified.output


def test_the_plain_output_says_what_was_frozen_and_what_changed() -> None:
    _pull()
    _Feed.close = 11.0
    code, out = _pull()
    assert code == 0 and "froze snapshot pull-" in out and "bars revised: 3" in out
    assert "the provider revised 3 earlier bars" in out


def test_a_repeat_pull_reuses_the_snapshot_and_adds_no_disk(tmp_path: Path) -> None:
    _pull()
    code, out = _pull("--json")
    first = json.loads(out)["snapshot"]
    code, out = _pull("--json")
    again = json.loads(out)["snapshot"]
    assert code == 0 and again == {"id": first["id"], "reused": True}
    assert len(list((tmp_path / "snapshots").iterdir())) == 1


def test_a_bad_bar_stops_the_pull_with_nothing_changed(tmp_path: Path) -> None:
    _pull()
    store = tmp_path / "store"
    held = {p: p.read_bytes() for p in store.rglob("*") if p.is_file()}
    _Feed.poison = True
    code, out = _pull()
    assert code == 2 and "not a finite number" in out
    assert {p: p.read_bytes() for p in store.rglob("*") if p.is_file()} == held
    assert not (tmp_path / "snapshots").exists()


def test_an_older_adapter_pull_is_refused_with_exit_3_and_changes_nothing(tmp_path: Path) -> None:
    _pull()
    store = tmp_path / "store"
    held = {p: p.read_bytes() for p in store.rglob("*") if p.is_file()}
    _Feed.version = "2"
    try:
        code, out = _pull()
    finally:
        _Feed.version = "1"
    assert code == 3 and "could not be frozen first" in out and "Nothing was changed" in out
    assert "no safe path today" in out
    assert {p: p.read_bytes() for p in store.rglob("*") if p.is_file()} == held
    assert not (tmp_path / "snapshots").exists()
