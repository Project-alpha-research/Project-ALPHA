"""Shared helpers for the JSON routers."""

from __future__ import annotations

import os
from pathlib import Path

from fastapi import HTTPException, Request

from alpha_core.config import AlphaSettings


def data_dir() -> Path:
    """The active store root — shared with the CLI and the MCP server."""
    return AlphaSettings().data_dir


def require_local_origin(request: Request) -> None:
    """Refuse a write unless it comes as JSON from the exact local Workstation origin."""
    port = os.environ.get("ALPHA_WEB_PORT") or os.environ.get("PORT") or "8801"
    expected = f"http://localhost:{int(port)}"
    if (
        request.headers.get("origin") != expected
        or request.headers.get("host") != f"localhost:{int(port)}"
        or request.headers.get("sec-fetch-site") not in {None, "same-origin"}
        or request.headers.get("content-type", "").split(";", 1)[0].strip() != "application/json"
    ):
        raise HTTPException(
            status_code=403, detail="This action requires the local Workstation origin"
        )
