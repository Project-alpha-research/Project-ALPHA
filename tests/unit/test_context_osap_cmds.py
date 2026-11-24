"""`alpha context pull-osap-portfolios` and `show-osap-portfolios` on synthetic release files."""

import io
import json
from collections.abc import Mapping
from datetime import date
from pathlib import Path
from typing import Any

import polars as pl
import pytest
from typer.testing import CliRunner

from alpha_cli.context_cmds import context_app
from alpha_data.context import free_http

FIX = Path(__file__).parents[1] / "fixtures/context/osap/signal_doc_sample.csv"


def _parquet() -> bytes:
    frame = pl.DataFrame(
        {
            "date": [date(2023, 10, 31), date(2023, 11, 30)],
            "SynthAccrual": [5.0, -2.5],
            "SynthMom": [1.0, None],
            "SynthOption": [None, 0.5],
        }
    )
    buffer = io.BytesIO()
    frame.write_parquet(buffer)
    return buffer.getvalue()


def invoke(*args: str, ok: bool = True) -> dict[str, Any]:
    result = CliRunner().invoke(context_app, list(args))
    assert (result.exit_code == 0) == ok, result.output + str(result.exception)
    if not ok:
        return {"output": result.output}
    payload: dict[str, Any] = json.loads(result.stdout)
    return payload


@pytest.fixture
def home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("ALPHA_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(free_http, "PAUSE_SECONDS", 0.0)

    def transport(
        url: str, headers: Mapping[str, str], timeout: float
    ) -> tuple[int, Mapping[str, str], bytes]:
        if url.endswith("SignalDoc.csv"):
            return 200, {}, FIX.read_bytes()
        return 200, {}, _parquet()

    monkeypatch.setattr(free_http, "default_transport", transport)
    return tmp_path


def test_pull_show_and_list_name_the_vintage(home: Path) -> None:
    pulled = invoke(
        "pull-osap-portfolios", "--release", "2023.12", "--released", "2023-12-20", "--json"
    )
    assert (pulled["signals"], pulled["months"], pulled["rows"]) == (3, 2, 4)
    early = invoke(
        "show-osap-portfolios", "--as-of", "2023-12-20", "--signal", "SynthMom", "--json"
    )
    assert early["release"] is None and early["rows"] == []
    assert "the stored release is dated 2023-12-20, after the as-of date" in early["note"]
    late = invoke(
        "show-osap-portfolios", "--as-of", "2023-12-21", "--signal", "SynthAccrual", "--json"
    )
    assert late["release"] == "2023.12" and late["signals"] == 3 and late["months"] == 2
    assert [r["long_short_return"] for r in late["rows"]] == pytest.approx([0.05, -0.025])
    assert {r["published_year"] for r in late["rows"]} == {1999}
    counts_only = invoke("show-osap-portfolios", "--as-of", "2023-12-21", "--json")
    assert counts_only["rows"] == [] and counts_only["signals"] == 3
    listed = invoke("list", "--json")
    rows = [t for t in listed["free_context"] if t["source"] == "osap-portfolios"]
    assert rows[0]["key"] == "2023.12" and rows[0]["signals"] == 3


def test_a_future_release_date_and_a_bad_release_id_are_refused(home: Path) -> None:
    out = invoke(
        "pull-osap-portfolios", "--release", "2023.12", "--released", "2999-01-01", ok=False
    )
    assert "released" in out["output"]
    out = invoke("pull-osap-portfolios", "--release", "x", "--released", "2023-12-20", ok=False)
    assert "release" in out["output"]
    assert not list(home.rglob("*.parquet"))
