"""DTZ011 is enforced and the Tiingo readiness check uses the UTC date."""

from __future__ import annotations

import tomllib
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from alpha_cli import provider_readiness

ROOT = Path(__file__).resolve().parents[2]


def test_dtz011_is_enabled_in_pyproject() -> None:
    config = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    lint = config["tool"]["ruff"]["lint"]
    selected = set(lint.get("select", [])) | set(lint.get("extend-select", []))
    ignored = set(lint.get("ignore", []))
    enabled = bool(selected & {"DTZ011", "DTZ01", "DTZ", "ALL"})
    assert enabled, "DTZ011 must be selected in [tool.ruff.lint]"
    assert "DTZ011" not in ignored
    assert "DTZ" not in ignored


def test_tiingo_check_does_not_read_local_date() -> None:
    source = (ROOT / "apps/alpha-cli/src/alpha_cli/provider_readiness.py").read_text(
        encoding="utf-8"
    )
    assert "date.today()" not in source


def test_tiingo_check_still_fetches_a_fourteen_day_window(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, date, date]] = []

    class FakeAdapter:
        def __init__(self, **_: Any) -> None:
            pass

        def fetch(self, symbol: str, start: date, end: date) -> Any:
            calls.append((symbol, start, end))
            return SimpleNamespace(bars=SimpleNamespace(height=5))

    monkeypatch.setattr(provider_readiness, "TiingoAdapter", FakeAdapter)
    capabilities, details = provider_readiness._tiingo_check()

    assert capabilities == ("historical_bars", "corporate_actions")
    assert details["row_count"] == 5
    assert len(calls) == 1
    symbol, start, end = calls[0]
    assert symbol == "SPY"
    assert end - start == timedelta(days=14)
    utc_today = datetime.now(UTC).date()
    assert abs((end - utc_today).days) <= 1
