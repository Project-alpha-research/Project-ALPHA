"""Rule tests (``alpha test`` runs) on the run API: what was tested, labels, stored diagnostics."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from alpha_web import _rule_test
from alpha_web.app import create_app

RUN_ID = "abcd00000000beef"
SPINE = {
    "idea": "test a 50/200-day trend rule on SPY",
    "labels": ["all-in", "dev-machine-data", "quick"],
    "name": "ma_cross-50-200",
    "rule": {"fast": 50, "kind": "ma_cross", "slow": 200},
    "spec_sha256": "b" * 64,
    "store": "alpaca",
    "test_id": "1a2d962ba3bc8173",
}
MANIFEST: dict[str, Any] = {
    "command": "validate",
    "source": "alpaca",
    "spine": SPINE,
    "metadata": {
        "symbol": "SPY",
        "first_ts": "2016-01-04T00:00:00+00:00",
        "last_ts": "2026-11-13T00:00:00+00:00",
        "n_bars": 2733,
        "fee_bps": 1.0,
        "slippage_bps": 2.0,
        "periods_per_year": 252,
        "sizing": "all_in",
        "max_leverage": 1.0,
    },
}
PERFORMANCE = {"cagr": 0.09, "max_drawdown": -0.31, "reasons": {}, "sharpe": 0.73}
DIAGNOSTICS: dict[str, Any] = {
    "audit": [
        {"check": "enough-trades", "detail": "4 closed trades; threshold 30.", "status": "FLAG"}
    ],
    "benchmark": {
        **PERFORMANCE,
        "basis": "buy and hold, same bars, no costs; close prices",
        "strategy_minus_benchmark": {
            "cagr": -0.038,
            "max_drawdown": None,
            "reasons": {"max_drawdown": "strategy or benchmark metric is unavailable"},
            "sharpe": -0.054,
            "total_return": -1.17,
        },
        "total_return": 2.75,
    },
    "by_year": {
        "basis": "full-sample returns grouped by ending calendar year",
        "benchmark_positive_years": 1,
        "strategy_positive_years": 1,
        "years": [{"benchmark_return": 0.11, "strategy_return": 0.05, "year": 2016}],
    },
    "concentration": {"basis": "closed trades", "reasons": {}, "top_1": 0.48, "top_3": 1.11},
    "delay": {
        "base_sharpe": 0.626,
        "basis": "approximation",
        "delayed_sharpe": 0.621,
        "reasons": {},
    },
    "drawdowns": {
        "basis": "peak to trough",
        "episodes": [
            {
                "benchmark_return": -0.34,
                "depth": -0.31,
                "reasons": {"recovery": "not recovered by the last bar"},
                "recovery": None,
                "share_explained": 1.09,
                "start": "2020-02-19T00:00:00+00:00",
                "trough": "2020-03-23T00:00:00+00:00",
            }
        ],
    },
    "flags": [
        {"detail": "Strategy Sharpe 0.73 is below buy-and-hold 0.784.", "flag": "below-benchmark"}
    ],
    "full_sample": {
        **PERFORMANCE,
        "basis": "full-sample backtest",
        "exposure": 0.77,
        "total_return": 1.57,
        "trades": 4,
    },
    "macro_window": {"available": False, "reason": "no stored FRED context series"},
    "sensitivity": {
        "basis": "full-sample engine re-runs",
        "variants": [
            {
                **PERFORMANCE,
                "basis": "re-run",
                "kind": "costs",
                "name": "costs_x2",
                "total_return": 1.5,
            }
        ],
    },
    "trials": {
        "available_sharpes": 7,
        "basis": "ledger",
        "dsr": 0.98,
        "reasons": {},
        "total_trials": 3,
    },
    "variants_evaluated": 5,
    "a_key_added_later": {"ignored": True},
}


def _client(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    manifest: dict[str, Any],
    diagnostics: object | None = None,
) -> TestClient:
    monkeypatch.setenv("ALPHA_DATA_DIR", str(tmp_path))
    rdir = tmp_path / "runs" / RUN_ID
    rdir.mkdir(parents=True)
    (rdir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    if diagnostics is not None:
        (rdir / "diagnostics.json").write_text(json.dumps(diagnostics), encoding="utf-8")
    return TestClient(create_app())


def test_rule_test_detail_relays_the_stored_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client = _client(tmp_path, monkeypatch, MANIFEST, DIAGNOSTICS)
    body = client.get(f"/api/runs/{RUN_ID}").json()
    test = body["rule_test"]
    assert body["display_name"] == "rule test ma_cross-50-200 D1 — SPY · alpaca · run abcd0000"
    assert body["market"] == "equities"
    # the launch classification keeps its meaning; the screen decides what to show for rule tests
    assert body["run_context_kind"] == "legacy_context_unknown"
    assert test["idea"] == SPINE["idea"]
    assert test["rule_kind"] == "ma_cross"
    assert test["rule_params"] == {"fast": 50, "slow": 200}
    assert test["rule_sentence"] == (
        "Long while the 50-day average is above the 200-day average, otherwise flat; "
        "decide at the close, fill at the next open; all capital in, no leverage"
    )
    assert (test["symbol"], test["source"], test["store"]) == ("SPY", "alpaca", "alpaca")
    assert test["labels"] == SPINE["labels"]
    assert test["test_id"] == SPINE["test_id"]
    assert (test["fee_bps"], test["slippage_bps"], test["n_bars"]) == (1.0, 2.0, 2733)
    assert test["total_trials"] == 3
    assert test["diagnostics_reason"] is None
    stored = test["diagnostics"]
    assert stored["flags"] == DIAGNOSTICS["flags"]
    assert stored["audit"] == DIAGNOSTICS["audit"]
    assert stored["full_sample"]["total_return"] == 1.57
    assert stored["full_sample"]["trades"] == 4
    difference = stored["benchmark"]["strategy_minus_benchmark"]
    assert difference["sharpe"] == -0.054
    assert difference["max_drawdown"] is None
    assert difference["reasons"] == {"max_drawdown": "strategy or benchmark metric is unavailable"}
    assert stored["by_year"]["years"] == DIAGNOSTICS["by_year"]["years"]
    assert stored["sensitivity"]["variants"][0]["name"] == "costs_x2"
    assert stored["delay"]["delayed_sharpe"] == 0.621
    assert stored["concentration"]["top_3"] == 1.11
    assert stored["trials"]["dsr"] == 0.98
    assert stored["worst_drawdown"]["recovery"] is None
    assert stored["worst_drawdown"]["reasons"] == {"recovery": "not recovered by the last bar"}
    assert stored["macro_window"]["available"] is False
    assert stored["macro_window"]["reason"] == "no stored FRED context series"
    assert stored["variants_evaluated"] == 5
    item = client.get("/api/runs").json()["items"][0]
    assert item["rule_test_labels"] == SPINE["labels"]
    assert item["display_name"] == body["display_name"]


def test_rule_test_relays_a_stored_macro_window(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    series: list[dict[str, Any]] = [
        {"series_id": "VIXCLS", "start_value": 14.38, "trough_value": 61.59, "change": 47.21},
        {"series_id": "UNRATE", "reason": "no observation known by then"},
    ]
    macro = {
        "available": True,
        "basis": "stored FRED series as known on the trough date",
        "start": "2020-02-19",
        "trough": "2020-03-23",
        "as_of": "2020-03-23",
        "series": series,
    }
    client = _client(tmp_path, monkeypatch, MANIFEST, {**DIAGNOSTICS, "macro_window": macro})
    window = client.get(f"/api/runs/{RUN_ID}").json()["rule_test"]["diagnostics"]["macro_window"]
    assert window["available"] is True
    assert window["series"][0] == {**series[0], "reason": None}
    assert window["series"][1] == {
        "series_id": "UNRATE",
        "start_value": None,
        "trough_value": None,
        "change": None,
        "reason": "no observation known by then",
    }


@pytest.mark.parametrize(
    ("diagnostics", "reason"),
    [
        (None, "this run recorded no diagnostics.json"),
        (["not", "an", "object"], "diagnostics.json is not an object"),
    ],
)
def test_rule_test_without_usable_diagnostics_is_null_not_an_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, diagnostics: object | None, reason: str
) -> None:
    client = _client(tmp_path, monkeypatch, MANIFEST, diagnostics)
    response = client.get(f"/api/runs/{RUN_ID}")
    assert response.status_code == 200
    test = response.json()["rule_test"]
    assert test["diagnostics"] is None
    assert test["diagnostics_reason"] == reason
    assert test["total_trials"] is None
    assert test["name"] == "ma_cross-50-200"


def test_rule_test_tolerates_an_empty_diagnostics_object(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client = _client(tmp_path, monkeypatch, MANIFEST, {})
    stored = client.get(f"/api/runs/{RUN_ID}").json()["rule_test"]["diagnostics"]
    assert stored["flags"] == []
    assert stored["audit"] == []
    assert all(
        stored[key] is None
        for key in ("full_sample", "benchmark", "by_year", "sensitivity", "delay", "trials")
    )


def test_a_run_without_spine_is_unchanged(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    manifest = {key: value for key, value in MANIFEST.items() if key != "spine"}
    client = _client(tmp_path, monkeypatch, manifest, DIAGNOSTICS)
    body = client.get(f"/api/runs/{RUN_ID}").json()
    assert body["rule_test"] is None
    assert body["display_name"] == "validate D1 — SPY · alpaca · run abcd0000"
    assert body["run_context_watermark"] == "LEGACY_CONTEXT_UNKNOWN"
    assert client.get("/api/runs").json()["items"][0]["rule_test_labels"] is None


@pytest.mark.parametrize(
    ("kind", "params", "metadata", "expected"),
    [
        (
            "breakout",
            {"window": 55},
            {"periods_per_year": 365},
            "Long after a close above the highest high of the prior 55 days, otherwise flat; "
            "decide at the close, fill at the next open",
        ),
        (
            "tsmom",
            {"lookback": 252, "skip": 21},
            {"periods_per_year": 252, "sizing": "all_in", "max_leverage": 1.0},
            "Long while the close 21 days ago is above the close 273 days ago, otherwise flat; "
            "decide at the close, fill at the next open; all capital in, no leverage",
        ),
        (
            "tsmom",
            {"lookback": 20, "skip": 0},
            {"periods_per_year": 1638},
            "Long while the latest close is above the close 20 bars ago, otherwise flat; "
            "decide at the close, fill at the next open",
        ),
        ("something_new", {"n": 3}, {}, None),
        ("ma_cross", {"fast": 50}, {}, None),
    ],
)
def test_rule_sentence_states_the_rule_or_nothing(
    kind: str, params: dict[str, int], metadata: dict[str, Any], expected: str | None
) -> None:
    assert _rule_test.rule_sentence(kind, params, metadata) == expected
