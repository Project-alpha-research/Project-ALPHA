"""Read, store and invalidate a daily series report through the real CLI."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import polars as pl
import pytest
from typer.testing import CliRunner

from alpha_cli.main import app
from alpha_data.store import ParquetStore


def test_health_command_and_stored_fingerprint(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ALPHA_DATA_DIR", str(tmp_path))
    (tmp_path / "stores.toml").write_text('spot = "archive"')
    store = ParquetStore(tmp_path / "archive" / "store")
    symbol = "BTC/USD"
    bars = pl.DataFrame(
        {
            "ts": [datetime(2024, 1, 2, tzinfo=UTC)],
            "open": [99.0],
            "high": [100.0],
            "low": [90.0],
            "close": [99.0],
            "volume": [0.0],
        }
    )
    path = store.write_bars(symbol, bars)
    store.write_provenance(symbol, source="ccxt", adapter_version="1", parser_version="1")
    args = ["data", "health", symbol + "@spot"]
    runner = CliRunner()
    result = runner.invoke(app, args)
    assert result.exit_code == 0, result.output
    output = result.output.lower()
    groups = [
        "adjustments",
        "timestamps",
        "gaps",
        "survivorship",
        "verdict",
        "what this cannot tell you",
    ]
    assert [output.index(g) for g in groups] == sorted(output.index(g) for g in groups)
    assert "zero volume" in output and "verdict: fail" in output
    sidecar = store.root / "health" / "BTC" / "USD.json"
    saved = json.loads(sidecar.read_bytes())
    assert len(saved["source_fingerprint"]) == 64
    result = runner.invoke(app, [*args, "--stored", "--json"])
    assert result.exit_code == 0 and json.loads(result.output) == saved
    original = path.read_bytes()
    path.write_bytes(original[:-1] + bytes([original[-1] ^ 1]))
    result = runner.invoke(app, [*args, "--stored", "--json"])
    assert result.exit_code == 0
    stale = json.loads(result.output)
    assert stale["status"] == "out of date" and "verdict" not in stale


def test_universe_membership_and_leaver_bytes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ALPHA_DATA_DIR", str(tmp_path))
    store = ParquetStore(tmp_path / "store")
    bars = pl.DataFrame(
        {
            "ts": [datetime(2024, 1, 2, tzinfo=UTC)],
            **{c: [10.0] for c in ("open", "high", "low", "close", "volume")},
        }
    )
    store.write_bars("X", bars)
    store.write_provenance("X", source="test", adapter_version="1", parser_version="1")
    path = tmp_path / "members.csv"
    path.write_text(
        "symbol,effective_from,effective_to,delisting_return,reason\nY,2024-01-01,2024-01-03,,removed\n"
    )
    runner = CliRunner()
    args = ["data", "health", "X", "--json"]

    def run(*opts: str) -> dict[str, object]:
        result = runner.invoke(app, [*args, *opts])
        assert result.exit_code == 0, result.output
        payload = json.loads(result.output)
        assert isinstance(payload, dict)
        return payload

    assert run("--universe", str(path))["verdict"] == "fail"
    store.write_bars("Y", bars)
    assert run("--stored")["status"] == "out of date"
    report = run("--universe", str(path))
    assert report["verdict"] == "warn"  # Stale stock tail, leaver is now present.
    assert run("--stored") == report
    path.write_text("symbol\nX\n")
    assert run("--stored")["status"] == "out of date"
    assert run("--universe", str(path))["verdict"] == "fail"
    (store.root / "provenance" / "X.json").write_bytes(b"{")
    assert run("--stored")["status"] == "out of date"
