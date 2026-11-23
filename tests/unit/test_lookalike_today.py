"""`alpha lookalike --today`: a forward-use look; compares with history before the boundary only."""

from __future__ import annotations

import json
import math
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
import typer
from typer.testing import CliRunner

import alpha_cli.follow_lookalike as today
from alpha_cli.lookalike_cmds import lookalike
from alpha_cli.spine.reserve import CUTOFF
from alpha_core import Bar

RUNNER = CliRunner()
START = datetime(2023, 6, 1, tzinfo=UTC)


def bars(count: int = 300) -> list[Bar]:
    out = []
    for i in range(count):
        close = 100.0 + 8.0 * math.sin(i / 5.0) + i * 0.05
        out.append(
            Bar(
                symbol="SPY",
                ts=START + timedelta(days=i),
                open=close,
                high=close + 1,
                low=close - 1,
                close=close,
                volume=1000.0,
            )
        )
    return out


@pytest.fixture
def home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("ALPHA_DATA_DIR", str(tmp_path))
    return tmp_path


def app() -> typer.Typer:
    cli = typer.Typer()
    cli.command()(lookalike)
    return cli


def test_it_compares_only_with_bars_before_the_boundary(
    home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    series = bars()
    assert series[-1].ts > CUTOFF > series[0].ts
    monkeypatch.setattr(today, "forward_bars", lambda *a, **k: (series, None))

    out = today.look_today(home, "SPY", last=20, top=5, horizons=(5,))

    assert out["label"] == "forward use: a look at today, not a test"
    assert out["query"]["end"] == series[-1].ts.date().isoformat()
    assert out["matches"], "a periodic series must have lookalikes"
    assert all(m["end"] <= CUTOFF.date().isoformat() for m in out["matches"])


def test_the_command_writes_no_run_and_no_try(home: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(today, "forward_bars", lambda *a, **k: (bars(), None))

    result = RUNNER.invoke(app(), ["--asset", "SPY", "--last", "20", "--today", "--json"])

    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout)["label"] == today.LABEL
    assert not (home / "lookalike").exists()
    assert not (home / "ledger").exists()
    assert [p for p in home.rglob("*") if p.is_file()] == []


def test_the_text_says_forward_use_and_what_was_written(
    home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(today, "forward_bars", lambda *a, **k: (bars(), None))

    result = RUNNER.invoke(app(), ["--asset", "SPY", "--last", "20", "--today"])

    assert "Forward use: a look at today, not a test" in result.stdout
    assert "no run, no result folder, no try" in result.stdout


def test_no_history_before_the_boundary_is_refused(
    home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    late = [
        b.model_copy(update={"ts": datetime(2024, 3, 1, tzinfo=UTC) + timedelta(days=i)})
        for i, b in enumerate(bars(60))
    ]
    monkeypatch.setattr(today, "forward_bars", lambda *a, **k: (late, None))

    result = RUNNER.invoke(app(), ["--asset", "SPY", "--last", "20", "--today"])

    assert result.exit_code != 0
    assert "before the held-back boundary" in result.output


def test_a_symbol_as_an_argument_works_like_the_asset_option(
    home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(today, "forward_bars", lambda *a, **k: (bars(), None))
    by_option = RUNNER.invoke(app(), ["--asset", "SPY", "--last", "20", "--today", "--json"])
    by_argument = RUNNER.invoke(app(), ["--last", "20", "--today", "SPY", "--json"])
    assert by_argument.exit_code == 0, by_argument.output
    assert json.loads(by_argument.stdout) == json.loads(by_option.stdout)


def test_the_symbol_is_needed_and_the_two_ways_must_agree(
    home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(today, "forward_bars", lambda *a, **k: (bars(), None))
    missing = RUNNER.invoke(app(), ["--last", "20", "--today"])
    assert missing.exit_code != 0 and "Name the asset" in missing.output
    clash = RUNNER.invoke(app(), ["QQQ", "--asset", "SPY", "--today"])
    assert clash.exit_code != 0 and "once" in clash.output
