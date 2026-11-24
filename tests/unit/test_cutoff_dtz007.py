"""DTZ007 is on, and the cutoff parser keeps its exact behaviour."""

import tomllib
from datetime import UTC, datetime
from pathlib import Path

import pytest
import typer

from alpha_cli.context_sources_cmds import _cutoff

ROOT = Path(__file__).parents[2]


def test_dtz007_enabled_in_pyproject() -> None:
    config = tomllib.loads((ROOT / "pyproject.toml").read_text())
    lint = config["tool"]["ruff"].get("lint", {})
    selected = [*lint.get("select", []), *lint.get("extend-select", [])]
    ignored = lint.get("ignore", [])
    assert "DTZ007" in selected
    assert "DTZ007" not in ignored


def test_cutoff_date() -> None:
    assert _cutoff("2024-01-26") == datetime(2024, 1, 26, tzinfo=UTC)
    assert _cutoff("2024-01-26").tzinfo is not None


def test_cutoff_minute() -> None:
    assert _cutoff("2024-01-02T00:05") == datetime(2024, 1, 2, 0, 5, tzinfo=UTC)


def test_cutoff_default_is_now_utc() -> None:
    before = datetime.now(UTC)
    value = _cutoff(None)
    assert before <= value <= datetime.now(UTC)


@pytest.mark.parametrize(
    "raw",
    [
        "2024-1-2",
        "2024-02-30",
        "2024-01-02T0:05",
        "2024-01-02 00:05",
        "2024-01-02T00:05:00",
        "not-a-date",
        "",
    ],
)
def test_cutoff_rejects_malformed(raw: str) -> None:
    with pytest.raises(typer.BadParameter, match="expected YYYY-MM-DD"):
        _cutoff(raw)
