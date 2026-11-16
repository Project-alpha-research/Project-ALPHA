"""Offline commands, including poisoned future rows at fixed cutoffs."""

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import polars as pl
import pytest
from typer.testing import CliRunner

from alpha_cli.context_cmds import context_app
from alpha_data.context.binance_bulk import map_binance_csv
from alpha_data.context.edgar import map_submission_arrays
from alpha_data.context.events import FILINGS_SCHEMA, FUNDING_SCHEMA, METRICS_SCHEMA, store_events

FIX = Path(__file__).parents[1] / "fixtures/context"
NOW = datetime(2024, 2, 1, tzinfo=UTC)


def seed(path: Path) -> None:
    root = path / "context/edgar"
    root.mkdir(parents=True)
    (root / "company_tickers.json").write_bytes((FIX / "edgar/company_tickers.json").read_bytes())
    raw = json.loads((FIX / "edgar/submissions_CIK0000000001.json").read_text())
    rows = [r for r in map_submission_arrays(raw["filings"]["recent"]) if "rejected" not in r]
    df = pl.DataFrame(
        [{"cik": "0000000001", "ticker": "TEST", **r} for r in rows], schema=FILINGS_SCHEMA
    )
    store_events(
        root / "0000000001/filings.parquet",
        df,
        {"source": "edgar", "fetched_at": NOW.isoformat()},
        schema=FILINGS_SCHEMA,
    )
    for kind, filename, schema in [
        ("funding", "funding_2024-01.csv", FUNDING_SCHEMA),
        ("metrics", "metrics_2024-01-02.csv", METRICS_SCHEMA),
    ]:
        df = map_binance_csv(kind, (FIX / "binance" / filename).read_bytes()).with_columns(
            pl.lit("BTCUSDT").alias("symbol")
        )
        store_events(
            path / f"context/binance/um/{kind}/BTCUSDT.parquet",
            df,
            {"source": "binance", "fetched_at": NOW.isoformat()},
            schema=schema,
        )


def invoke(*args: str) -> dict[str, Any]:
    result = CliRunner().invoke(context_app, list(args))
    assert result.exit_code == 0, result.output + str(result.exception)
    payload: dict[str, Any] = json.loads(result.stdout)
    return payload


def test_show_sources_and_future_poison(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ALPHA_DATA_DIR", str(tmp_path))
    seed(tmp_path)
    requests = [
        ("show-edgar", "--ticker", "TEST", "--view", "earnings", "--as-of", "2024-01-26", "--json"),
        (
            "show-binance",
            "--symbol",
            "BTCUSDT",
            "--kind",
            "funding",
            "--as-of",
            "2024-01-01",
            "--json",
        ),
        (
            "show-binance",
            "--symbol",
            "BTCUSDT",
            "--kind",
            "metrics",
            "--as-of",
            "2024-01-02T00:05",
            "--json",
        ),
    ]
    before = [invoke(*args) for args in requests]
    assert all(result["view"] == "as_known" and len(result["rows"]) == 1 for result in before)
    for path in tmp_path.rglob("*.parquet"):
        df = pl.read_parquet(path)
        cutoff = (
            datetime(2024, 1, 26, tzinfo=UTC)
            if "edgar" in str(path)
            else datetime(2024, 1, 2, 0, 5, tzinfo=UTC)
            if "metrics" in str(path)
            else datetime(2024, 1, 1, 0, 5, tzinfo=UTC)
        )
        column, value = (
            ("items", "2.02,POISON")
            if "edgar" in str(path)
            else (("funding_rate", 1e100) if "funding" in str(path) else ("open_interest", 1e100))
        )
        poisoned = df.with_columns(
            pl.when(pl.col("known_from") > cutoff)
            .then(pl.lit(value))
            .otherwise(pl.col(column))
            .alias(column)
        )
        assert not df.equals(poisoned)
        store_events(
            path,
            poisoned,
            {
                "source": "edgar" if "edgar" in str(path) else "binance",
                "fetched_at": NOW.isoformat(),
            },
            schema=dict(df.schema),
        )
    assert [invoke(*args) for args in requests] == before
    from alpha_cli import context_sources_cmds

    monkeypatch.setattr(context_sources_cmds, "as_known_events", lambda df, **kwargs: df)
    for args, expected in zip(requests, before, strict=True):
        with pytest.raises(AssertionError):
            assert invoke(*args) == expected  # each leaky command must fail the same comparison


@pytest.mark.parametrize(
    "args",
    [
        ["show-edgar", "--view", "filings"],
        ["show-edgar", "--ticker", "TEST", "--cik", "1", "--view", "filings"],
        ["show-edgar", "--cik", "1", "--view", "latest"],
        ["show-binance", "--symbol", "BTCUSDT", "--kind", "funding", "--as-of", "invalid"],
        [
            "pull-binance",
            "--symbol",
            "BTCUSDT",
            "--kind",
            "metrics",
            "--start",
            "2024-01-01",
            "--end",
            "2025-02-04",
        ],
    ],
)
def test_bad_options_fail_without_network(
    args: list[str], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ALPHA_DATA_DIR", str(tmp_path))
    assert CliRunner().invoke(context_app, args).exit_code != 0


def test_pull_command_dispatch_and_json(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from alpha_data.context import binance_bulk, edgar

    monkeypatch.setenv("ALPHA_DATA_DIR", str(tmp_path))
    calls: list[dict[str, Any]] = []

    def fake(**kwargs: Any) -> dict[str, int]:
        calls.append(kwargs)
        return {"rows": 2}

    monkeypatch.setattr(edgar, "pull_edgar", fake)
    monkeypatch.setattr(binance_bulk, "pull_binance", fake)
    assert invoke(
        "pull-edgar", "--cik", "1", "--forms", "4", "--since", "2024-01-01", "--json"
    ) == {"rows": 2}
    assert calls[-1]["since"].isoformat() == "2024-01-01"
    assert calls[-1]["forms"] == "4" and calls[-1]["data_dir"] == tmp_path
    assert invoke(
        "pull-binance",
        "--symbol",
        "BTCUSDT",
        "--kind",
        "funding",
        "--start",
        "2024-01",
        "--end",
        "2024-02",
        "--json",
    ) == {"rows": 2}
    assert calls[-1]["start"] == "2024-01" and calls[-1]["fetched_at"].tzinfo is UTC


def test_show_bounds_and_missing_table(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ALPHA_DATA_DIR", str(tmp_path))
    seed(tmp_path)
    assert (
        invoke(
            "show-binance",
            "--symbol",
            "BTCUSDT",
            "--kind",
            "funding",
            "--start",
            "2024-01-02",
            "--end",
            "2024-01-03",
            "--json",
        )["rows"]
        == []
    )
    missing = CliRunner().invoke(
        context_app, ["show-edgar", "--cik", "2", "--view", "filings", "--json"]
    )
    assert missing.exit_code != 0 and "not found" in missing.output


def test_errors_say_the_next_step(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ALPHA_DATA_DIR", str(tmp_path))
    monkeypatch.delenv("ALPHA_SEC_USER_AGENT", raising=False)
    result = CliRunner().invoke(context_app, ["pull-edgar", "--cik", "1"])
    assert result.exit_code != 0 and "Next: set ALPHA_SEC_USER_AGENT" in result.output
    result = CliRunner().invoke(
        context_app, ["show-binance", "--symbol", "BTCUSDT", "--kind", "funding"]
    )
    flat = " ".join(result.output.replace("│", " ").split())
    assert result.exit_code != 0 and "Next: nothing is stored yet; run" in flat


def test_bybit_import_show_and_future_poison(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from alpha_cli import context_sources_cmds
    from tests.unit.test_context_bybit_import import source

    src, data = tmp_path / "source", tmp_path / "data"
    monkeypatch.setenv("ALPHA_DATA_DIR", str(data))
    source(src, [0, 1], family="open_interest", values=[1.0, 1e100])
    assert invoke("import-bybit", "--from", str(src), "--json")["tables"][0]["rows"] == 2
    args = (
        "show-bybit",
        "--symbol",
        "BTCUSDT",
        "--kind",
        "open-interest",
        "--as-of",
        "2024-01-01T01:05",
        "--json",
    )
    expected = invoke(*args)
    assert len(expected["rows"]) == 1 and expected["rows"][0]["open_interest"] == 1.0
    monkeypatch.setattr(context_sources_cmds, "as_known_events", lambda df, **kwargs: df)
    with pytest.raises(AssertionError):
        assert invoke(*args) == expected


def test_bybit_errors_are_offline(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ALPHA_DATA_DIR", str(tmp_path / "data"))
    for args in [
        ["import-bybit", "--from", str(tmp_path / "missing")],
        ["show-bybit", "--symbol", "BTCUSDT", "--kind", "metrics"],
        ["show-bybit", "--symbol", "BTCUSDT", "--kind", "funding"],
    ]:
        result = CliRunner().invoke(context_app, args)
        assert result.exit_code != 0
        assert "network" not in result.output.lower()
        assert "Next:" in result.output


def test_bybit_catalog_authority() -> None:
    from alpha_cli.catalog import classify_generic_command

    assert classify_generic_command(["context", "show-bybit"]) == "safe"
    assert classify_generic_command(["context", "import-bybit"]) == "owner_only"
