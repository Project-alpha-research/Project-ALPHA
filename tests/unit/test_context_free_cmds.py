"""Commands for the free CFTC and FINRA context series, on recorded synthetic fixtures."""

import json
import urllib.parse
from collections.abc import Mapping
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from alpha_cli.context_cmds import context_app
from alpha_data.context import cftc_cot, finra_short, free_http

FIX = Path(__file__).parents[1] / "fixtures/context"


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
        if "cftc.gov" in url:
            rows = json.loads((FIX / "cftc/legacy_futures_sample.json").read_text())
            offset = int(urllib.parse.parse_qs(urllib.parse.urlsplit(url).query)["$offset"][0])
            return 200, {}, json.dumps(rows[offset:]).encode()
        path = FIX / "finra" / url.rsplit("/", 1)[1]
        return (200, {}, path.read_bytes()) if path.exists() else (403, {}, b"")

    monkeypatch.setattr(free_http, "default_transport", transport)
    return tmp_path


def test_pull_show_list_cftc(home: Path) -> None:
    pulled = invoke("pull-cftc-cot", "--market", "13874A", "--since", "2024-01-01", "--json")
    assert pulled["markets"] == [
        {
            "market_code": "13874A",
            "rows": 3,
            "first_period": "2024-01-09",
            "last_period": "2024-01-23",
        }
    ]
    assert "Friday 15:30" in pulled["known_from_rule"]
    early = invoke("show-cftc-cot", "--market", "13874A", "--as-of", "2024-01-11", "--json")
    assert early["rows"] == [] and early["view"] == "as_known"
    later = invoke("show-cftc-cot", "--market", "13874A", "--as-of", "2024-01-12T20:31", "--json")
    assert [r["report_date"] for r in later["rows"]] == ["2024-01-09"]
    assert later["rows"][0]["known_from"] == "2024-01-12T20:30:47.123000+00:00"
    listed = invoke("list", "--json")
    cot = [t for t in listed["free_context"] if t["source"] == "cftc-cot"]
    assert cot[0]["key"] == "13874A" and cot[0]["rows"] == 3
    assert cot[0]["last_known_from"] == "2024-01-26T20:30:50.500000+00:00"
    assert listed["series"] == []


def test_pull_show_list_finra_prints_the_caveat(home: Path) -> None:
    pulled = invoke(
        "pull-finra-short-volume",
        "--symbol",
        "SPY",
        "--start",
        "2024-01-02",
        "--end",
        "2024-01-05",
        "--json",
    )
    assert pulled["symbols"] == [
        {"symbol": "SPY", "rows": 2, "first_period": "2024-01-02", "last_period": "2024-01-03"}
    ]
    assert pulled["missing_days"] == ["2024-01-04", "2024-01-05"]
    assert "FINRA facilities only" in pulled["caveat"]
    shown = invoke(
        "show-finra-short-volume", "--symbol", "SPY", "--as-of", "2024-01-03T12:00", "--json"
    )
    assert [r["trade_date"] for r in shown["rows"]] == ["2024-01-02"]
    assert "FINRA facilities only" in shown["caveat"]
    listed = invoke("list", "--json")["free_context"]
    assert listed[0]["source"] == "finra-short-volume" and "FINRA facilities" in listed[0]["caveat"]
    plain = CliRunner().invoke(context_app, ["show-finra-short-volume", "--symbol", "SPY"])
    assert "FINRA facilities only" in plain.output


def test_show_missing_table_and_bad_options_fail_with_a_next_step(home: Path) -> None:
    out = invoke("show-cftc-cot", "--market", "13874A", ok=False)["output"]
    assert "pull-cftc-cot" in out
    assert invoke("show-finra-short-volume", "--symbol", "spy!", ok=False)
    assert invoke("pull-cftc-cot", "--market", "13874A", "--since", "2024-1-1", ok=False)
    assert invoke(
        "pull-finra-short-volume",
        "--symbol",
        "SPY",
        "--start",
        "2024-01-05",
        "--end",
        "2024-01-02",
        ok=False,
    )


def test_offline_pull_exits_with_a_clear_message(
    home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def offline(url: str, headers: Mapping[str, str], timeout: float) -> Any:
        raise OSError("network is unreachable")

    monkeypatch.setattr(free_http, "default_transport", offline)
    out = invoke("pull-cftc-cot", "--market", "13874A", ok=False)["output"]
    assert "offline" in out and "nothing was stored" in out


def test_module_constants_are_importable() -> None:
    assert cftc_cot.DATASET == "6dca-aqww" and finra_short.SOURCE == "finra-short-volume"
    assert date(2024, 1, 1) < datetime(2024, 1, 2, tzinfo=UTC).date()
