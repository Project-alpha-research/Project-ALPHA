"""``/api/follow/*`` against the real ``alpha`` subprocess on an empty home."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from alpha_web.app import create_app


def _client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("ALPHA_DATA_DIR", str(tmp_path))
    return TestClient(create_app())


def test_an_empty_home_has_no_follows(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    body = _client(tmp_path, monkeypatch).get("/api/follow/today").json()
    assert body["rows"] == [] and body["followed"] == 0 and body["behind"] == 0
    assert body["notice"].startswith("Paper only")
    assert not (tmp_path / "forward").exists()


def test_an_unknown_follow_is_a_409_with_the_command_text(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    response = _client(tmp_path, monkeypatch).get("/api/follow/abcdef012345")
    assert response.status_code == 409 and response.json()["message"]
