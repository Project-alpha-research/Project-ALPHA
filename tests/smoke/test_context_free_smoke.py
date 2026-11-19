"""Installed free-context reads over stored synthetic rows; no provider network calls."""

import json
import os
import subprocess
from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from alpha_data.context import cftc_cot, finra_short
from alpha_data.context.events import store_events

pytestmark = pytest.mark.smoke
ROOT = Path(__file__).parents[2]
FIX = ROOT / "tests/fixtures/context"


def test_context_free_local_reads(tmp_path: Path) -> None:
    now = datetime(2024, 2, 1, tzinfo=UTC)
    records = json.loads((FIX / "cftc/legacy_futures_sample.json").read_text())
    frame = cftc_cot.map_rows(records, "13874A")
    path = cftc_cot.table_path(tmp_path, "13874A")
    path.parent.mkdir(parents=True)
    store_events(
        path,
        frame,
        {
            "source": "cftc-cot",
            "fetched_at": now.isoformat(),
            "known_from_rule": "x",
            "caveat": "x",
        },
        schema=cftc_cot.SCHEMA,
    )
    raw = (FIX / "finra/CNMSshvol20240102.txt").read_bytes()
    short = finra_short.map_file(raw, date(2024, 1, 2), {"SPY"})
    spath = finra_short.table_path(tmp_path, "SPY")
    spath.parent.mkdir(parents=True)
    store_events(
        spath,
        short,
        {
            "source": "finra-short-volume",
            "fetched_at": now.isoformat(),
            "known_from_rule": "x",
            "caveat": finra_short.CAVEAT,
        },
        schema=finra_short.SCHEMA,
    )
    requests = [
        ["show-cftc-cot", "--market", "13874A", "--as-of", "2024-01-12T21:00"],
        ["show-finra-short-volume", "--symbol", "SPY", "--as-of", "2024-01-03"],
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
