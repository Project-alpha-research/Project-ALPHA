"""``GET /api/runs/{id}/checks``: stored toolbox results of a rule test, relayed unedited."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from alpha_web import _checks
from alpha_web.app import create_app

RUN_ID = "abcd00000000beef"
READING = "Calm months made 0.9 of the return; turbulent months made 0.1."
STORED = {
    "tool": "market.vol_regimes",
    "id": "1a2b3c4d",
    "params": {"split": "median"},
    "recorded_at": "2026-11-19T10:00:00+00:00",
    "file": "diagnostics/abcd00000000beef/market.vol_regimes@v1-1a2b3c4d.json",
    "labels": ["ad-hoc", "reserved-period-seen"],
    "reading": READING,
}
FAILED = {
    "kind": "tool:market.attribution",
    "run_id": RUN_ID,
    "outcome": "error",
    "error_code": "UNKNOWN_ASSET",
    "labels": ["ad-hoc"],
    "recorded_at": "2026-11-19T09:00:00+00:00",
}
ATTEMPT = {**FAILED, "outcome": "attempted", "recorded_at": "2026-11-19T08:59:00+00:00"}
OK_ROW = {**STORED, "kind": "tool:market.vol_regimes", "outcome": "ok"}


def _client(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    shown: object,
    calls: list[list[str]] | None = None,
) -> TestClient:
    monkeypatch.setenv("ALPHA_DATA_DIR", str(tmp_path))
    rdir = tmp_path / "runs" / RUN_ID
    rdir.mkdir(parents=True)
    (rdir / "manifest.json").write_text(json.dumps({"spine": {"labels": []}}), encoding="utf-8")

    def fake(args: list[str], *, data_dir: Path, **_: Any) -> object:
        assert data_dir == tmp_path
        if calls is not None:
            calls.append(args)
        return shown

    monkeypatch.setattr(_checks, "_run_json", fake)
    return TestClient(create_app())


def test_stored_results_are_returned_with_their_stored_reading(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[list[str]] = []
    shown: dict[str, Any] = {"runs": [{"tools": [STORED], "tool_history": [ATTEMPT, OK_ROW]}]}
    body = _client(tmp_path, monkeypatch, shown, calls).get(f"/api/runs/{RUN_ID}/checks").json()
    assert calls == [["results", "show", RUN_ID, "--json"]]
    assert body == {
        "run_id": RUN_ID,
        "checks": [
            {
                "tool": "market.vol_regimes",
                "outcome": "ok",
                "reading": READING,
                "error": None,
                "labels": ["ad-hoc", "reserved-period-seen"],
                "recorded_at": "2026-11-19T10:00:00+00:00",
            }
        ],
    }


def test_no_stored_results_is_an_empty_list(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    shown: dict[str, Any] = {"runs": [{"tools": [], "tool_history": []}]}
    response = _client(tmp_path, monkeypatch, shown).get(f"/api/runs/{RUN_ID}/checks")
    assert response.status_code == 200
    assert response.json() == {"run_id": RUN_ID, "checks": []}


def test_a_tool_error_row_is_shown_as_an_error_in_time_order(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    shown: dict[str, Any] = {
        "runs": [{"tools": [STORED], "tool_history": [ATTEMPT, FAILED, OK_ROW]}]
    }
    body = _client(tmp_path, monkeypatch, shown).get(f"/api/runs/{RUN_ID}/checks").json()
    assert [(c["tool"], c["outcome"]) for c in body["checks"]] == [
        ("market.attribution", "error"),
        ("market.vol_regimes", "ok"),
    ]
    assert body["checks"][0]["error"] == "UNKNOWN_ASSET"
    assert body["checks"][0]["reading"] is None


def test_unknown_run_is_404_and_a_cli_failure_is_422(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client = _client(tmp_path, monkeypatch, {"runs": []})
    assert client.get("/api/runs/ffff00000000ffff/checks").status_code == 404
    refused = client.get(f"/api/runs/{RUN_ID}/checks")
    assert refused.status_code == 422

    def fail(args: list[str], *, data_dir: Path, **_: Any) -> object:
        raise RuntimeError("Unknown run")

    monkeypatch.setattr(_checks, "_run_json", fail)
    failed = client.get(f"/api/runs/{RUN_ID}/checks")
    assert failed.status_code == 422
    assert "Unknown run" in failed.text
