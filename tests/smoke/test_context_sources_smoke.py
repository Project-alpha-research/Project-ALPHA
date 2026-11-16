"""Installed context reads over invented fixture tables; no provider network calls."""

import json
import os
import subprocess
from datetime import UTC, datetime
from pathlib import Path

import polars as pl
import pytest

from alpha_data.context.binance_bulk import map_binance_csv
from alpha_data.context.edgar import map_submission_arrays
from alpha_data.context.events import FILINGS_SCHEMA, FUNDING_SCHEMA, store_events

pytestmark = pytest.mark.smoke
ROOT = Path(__file__).parents[2]
FIX = ROOT / "tests/fixtures/context"


def test_context_sources_local_reads(tmp_path: Path) -> None:
    now = datetime(2024, 2, 1, tzinfo=UTC).isoformat()
    directory = tmp_path / "context/edgar"
    directory.mkdir(parents=True)
    (directory / "company_tickers.json").write_bytes(
        (FIX / "edgar/company_tickers.json").read_bytes()
    )
    body = json.loads((FIX / "edgar/submissions_CIK0000000001.json").read_text())
    rows = [
        {"cik": "0000000001", "ticker": "TEST", **row}
        for row in map_submission_arrays(body["filings"]["recent"])
        if "rejected" not in row
    ]
    store_events(
        directory / "0000000001/filings.parquet",
        pl.DataFrame(rows, schema=FILINGS_SCHEMA),
        {"source": "edgar", "fetched_at": now},
        schema=FILINGS_SCHEMA,
    )
    funding = map_binance_csv("funding", (FIX / "binance/funding_2024-01.csv").read_bytes())
    store_events(
        tmp_path / "context/binance/um/funding/BTCUSDT.parquet",
        funding.with_columns(pl.lit("BTCUSDT").alias("symbol")),
        {"source": "binance", "fetched_at": now},
        schema=FUNDING_SCHEMA,
    )
    requests = [
        ["show-edgar", "--ticker", "TEST", "--view", "earnings", "--as-of", "2024-01-26"],
        ["show-binance", "--symbol", "BTCUSDT", "--kind", "funding", "--as-of", "2024-01-01"],
    ]
    for args in requests:
        result = subprocess.run(
            [str(ROOT / ".venv/bin/alpha"), "context", *args, "--json"],
            env={**os.environ, "ALPHA_DATA_DIR": str(tmp_path)},
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
        assert result.returncode == 0, result.stdout + result.stderr
        payload = json.loads(result.stdout)
        assert payload["view"] == "as_known" and len(payload["rows"]) == 1
