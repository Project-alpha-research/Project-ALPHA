"""`alpha-web --help` prints help and does not start the server."""

from __future__ import annotations

import pytest

from alpha_web import app


def test_help_prints_facts_and_does_not_serve(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    def boom(*_a: object, **_k: object) -> None:
        raise AssertionError("the server must not start")

    monkeypatch.setattr("uvicorn.run", boom)
    app.main(["--help"])
    out = capsys.readouterr().out
    assert "ALPHA_WEB_PORT" in out
    assert "ALPHA_DATA_DIR" in out
    assert "http://127.0.0.1:8801" in out
