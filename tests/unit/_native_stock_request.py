"""The one canonical synthetic stock request shared by the snapshot and worker suites."""

from __future__ import annotations

from alpha_cli.native_stock_fixture import StockFixtureRequest

REQUEST = StockFixtureRequest("job", "reservation", "owner", "a" * 64, "b" * 64, 5, 2, 2, 1000)
