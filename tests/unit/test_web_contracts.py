"""Committed and runtime workstation API contracts cannot drift."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi import HTTPException
from fastapi.responses import FileResponse
from fastapi.routing import APIRoute

from alpha_web import app as web_app
from alpha_web.app import create_app


def test_committed_openapi_matches_runtime() -> None:
    root = Path(__file__).parents[2]
    committed = json.loads((root / "apps/alpha-web/frontend/openapi.json").read_text())
    assert committed == create_app().openapi()


def test_every_stable_json_route_has_a_response_model() -> None:
    unmodeled = []
    for route in create_app().routes:
        if not isinstance(route, APIRoute) or not route.path.startswith("/api/"):
            continue
        if route.path.endswith("/stream") or route.path.endswith("/tearsheet"):
            continue
        if route.response_model is None:
            unmodeled.append(route.path)
    assert unmodeled == []


def test_profile_is_never_an_api_parameter_or_field() -> None:
    """Spec 2026-09-01 §4.1/§6: the crypto/equities profile is a display setting and never a
    permission — no route parameter and no schema property may be called `profile`."""
    document = create_app().openapi()
    for path, operations in document["paths"].items():
        for operation in operations.values():
            for parameter in operation.get("parameters", []):
                assert parameter["name"] != "profile", path
    for name, schema in document["components"]["schemas"].items():
        assert "profile" not in schema.get("properties", {}), name


@pytest.mark.parametrize("built", [False, True])
def test_api_starts_with_or_without_built_assets(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, built: bool
) -> None:
    index = tmp_path / "static/app/index.html"
    monkeypatch.setattr(web_app, "_PKG", tmp_path)
    monkeypatch.setattr(web_app, "_APP_INDEX", index)
    if built:
        index.parent.mkdir(parents=True)
        index.write_text("<html></html>", encoding="utf-8")

    app = create_app()
    assert "/api/rdagent/runs/{run_id}/journeys/{idea_id}" in app.openapi()["paths"]
    spa = next(
        route for route in app.routes if isinstance(route, APIRoute) and route.path == "/app"
    )
    if built:
        assert app.url_path_for("static", path="app/index.html") == "/static/app/index.html"
        response = spa.endpoint()
        assert isinstance(response, FileResponse)
        assert response.path == index
    else:
        with pytest.raises(HTTPException) as exc:
            spa.endpoint()
        assert exc.value.status_code == 503
        assert "npm run build" in exc.value.detail
        assert not index.parent.parent.exists()
