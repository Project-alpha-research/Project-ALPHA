"""Installed context commands with synthetic stored vintages, no provider access."""

import json
import os
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from alpha_data.context.fred import parse_observations, store_series


@pytest.mark.smoke
def test_context_list_show_window(tmp_path: Path) -> None:
    home = tmp_path / "home"
    home.mkdir()
    data_dir = tmp_path / "data"
    df = parse_observations(
        "X",
        [
            dict(
                date="2024-01-01", value="1", realtime_start="2024-01-02", realtime_end="2024-02-29"
            ),
            dict(
                date="2024-01-01", value="9", realtime_start="2024-03-01", realtime_end="9999-12-31"
            ),
            dict(
                date="2024-02-01", value="3", realtime_start="2024-02-02", realtime_end="9999-12-31"
            ),
        ],
    )
    store_series(
        "X",
        df,
        dict(
            title="Example",
            units="Percent",
            frequency="Monthly",
            seasonal_adjustment="None",
            last_updated="2024-03-01",
        ),
        data_dir=data_dir,
        fetched_at=datetime(2024, 3, 1, tzinfo=UTC),
    )
    env = {
        name: value
        for name, value in os.environ.items()
        if not name.startswith("ALPHA_") and name not in {"FRED_API_KEY", "HOME"}
    }
    env.update(HOME=str(home), ALPHA_DATA_DIR=str(data_dir))
    alpha = Path(sys.executable).parent / "alpha"

    def run(*args: str) -> dict[str, Any]:
        result = subprocess.run(
            [str(alpha), "context", *args, "--json"],
            cwd=home,
            env=env,
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert result.returncode == 0, result.stderr
        payload: dict[str, Any] = json.loads(result.stdout)
        return payload

    assert run("list")["series"][0]["series_id"] == "X"
    shown = run("show", "X", "--as-of", "2024-02-15")
    assert shown["view"] == "as_known" and shown["rows"][0]["value"] == 1.0
    window = run("window", "--start", "2024-01-15", "--end", "2024-02-15")
    assert window["series"][0]["change"] == 2.0
