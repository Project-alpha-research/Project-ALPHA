"""Kronos reads its model from the local cache when the files are there: no hub request."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from alpha_cli import _forecast


class _Capture:
    def __init__(self, **kwargs: Any) -> None:
        _Capture.kwargs = kwargs

    kwargs: dict[str, Any] = {}


def _build(cache: Path | None, *, requested: bool = False) -> dict[str, Any]:
    _forecast._forecaster_factory(
        model="NeoQuasar/Kronos-small",
        model_revision="abc",
        tokenizer="NeoQuasar/Kronos-Tokenizer-base",
        tokenizer_revision="def",
        device="cpu",
        hub_cache=cache,
        local_files_only=requested,
    )
    return _Capture.kwargs


@pytest.fixture(autouse=True)
def _kronos(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("alpha_forecast.KronosForecaster", _Capture)


def test_both_models_in_the_cache_load_offline(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "huggingface_hub.try_to_load_from_cache", lambda *a, **k: "/cache/config.json"
    )
    assert _build(Path("/cache"))["local_files_only"] is True


def test_a_model_missing_from_the_cache_may_still_use_the_hub(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("huggingface_hub.try_to_load_from_cache", lambda *a, **k: None)
    assert _build(Path("/cache"))["local_files_only"] is False


def test_an_explicit_offline_setting_is_kept(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("huggingface_hub.try_to_load_from_cache", lambda *a, **k: None)
    assert _build(None, requested=True)["local_files_only"] is True
