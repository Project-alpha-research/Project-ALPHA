"""`alpha forecast run` prints picture files with the plain names the other figures use."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from alpha_cli import _artifacts, figures_cmds, forecast_cmds
from alpha_cli.figures.builders_mcpaths import fan_axis_label


def test_the_printed_pictures_are_named_without_the_hash(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cache = tmp_path / "figure-cache" / ("a" * 16)
    cache.mkdir(parents=True)

    def fake_render(figure_id: str, *, variant: str, **_: Any) -> dict[str, Any]:
        image = cache / f"{figure_id}.{variant}hash.png"
        image.write_bytes(b"png-" + variant.encode())
        image.with_suffix(".json").write_text(json.dumps({"variant": variant}))
        return {"figure_id": figure_id, "path": str(image), "format": "png"}

    monkeypatch.setattr(figures_cmds, "_render_one", fake_render)
    monkeypatch.setattr(_artifacts, "read_manifest", lambda _rdir: {})

    plain, annotated = forecast_cmds._cone_pictures("a" * 16, tmp_path, tmp_path)

    assert Path(plain).name == "forecast_fan.png"
    assert Path(annotated).name == "forecast_fan.annotated.png"
    assert Path(plain).read_bytes() == b"png-plain"
    assert Path(annotated).read_bytes() == b"png-annotated"


def test_the_kronos_fan_axis_label_is_plain() -> None:
    assert fan_axis_label("kronos_synthetic") == "Account value on simulated prices (1 = start)"
    assert "OHLCV" not in fan_axis_label("kronos_synthetic")
    assert fan_axis_label("student_t") == "Student-t equity (x)"
