"""The web app has no owner-auth surface; assistant writes keep the exact local-origin check."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from alpha_web.app import create_app

ORIGIN = "http://localhost:8801"
ASSISTANT_WRITES = ("/api/assistant/sessions", "/api/assistant/sessions/s1/check")


def test_owner_auth_routes_and_enrollment_page_are_gone() -> None:
    with TestClient(create_app(), base_url=ORIGIN, headers={"Origin": ORIGIN}) as client:
        for route in ("actions/challenge", "actions/perform", "enrollment/options"):
            assert client.post("/api/" + "owner-auth/" + route, json={}).status_code == 404
        assert client.get("/" + "owner-auth/enroll").status_code == 404
        paths = client.get("/openapi.json").json()["paths"]
    assert not [path for path in paths if "owner-auth" in path]


def test_generic_jobs_cannot_reach_owner_auth_cli() -> None:
    with TestClient(create_app(), base_url=ORIGIN, headers={"Origin": ORIGIN}) as client:
        response = client.post(
            "/api/jobs",
            json={"command": "owner-auth", "args": "enroll --reason generic-console-bypass"},
        )
    assert response.status_code == 422
    assert "trusted-local CLI" in response.json()["message"]


@pytest.mark.parametrize("origin", [None, "null", "https://evil.example", "http://localhost:8802"])
def test_assistant_writes_reject_wrong_origin(
    origin: str | None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ALPHA_WEB_PORT", "8801")
    headers = {} if origin is None else {"Origin": origin}
    with TestClient(create_app(), base_url=ORIGIN) as client:
        for route in ASSISTANT_WRITES:
            assert client.post(route, headers=headers, json={}).status_code == 403


@pytest.mark.parametrize(
    "host,fetch,content",
    [
        ("evil.example", "same-origin", "application/json"),
        ("localhost:8801", "cross-site", "application/json"),
        ("localhost:8801", "same-origin", "text/plain"),
    ],
)
def test_assistant_writes_reject_host_fetch_and_content(
    monkeypatch: pytest.MonkeyPatch, host: str, fetch: str, content: str
) -> None:
    monkeypatch.setenv("ALPHA_WEB_PORT", "8801")
    headers = {"origin": ORIGIN, "host": host, "sec-fetch-site": fetch, "content-type": content}
    with TestClient(create_app(), base_url=ORIGIN) as client:
        for route in ASSISTANT_WRITES:
            assert client.post(route, content="{}", headers=headers).status_code == 403
