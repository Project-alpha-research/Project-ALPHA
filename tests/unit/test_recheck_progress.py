"""`alpha test --recheck` shows the same estimate and progress as a normal test."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from alpha_cli import test_cmds


def test_a_recheck_prints_an_estimate_and_runs_inside_a_heartbeat(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    beats: list[str] = []

    @contextmanager
    def fake_heartbeat(label: Callable[[], str], **_: Any) -> Iterator[None]:
        beats.append(label())
        yield

    def fake_recheck(_idea: object, *, stage: Callable[[str], None], **_: Any) -> dict[str, Any]:
        stage("testing SPY (1 of 2)")
        stage("testing QQQ (2 of 2)")
        found = {
            "compared_with": "r",
            "match": True,
            "computed": True,
            "differences": [],
            "code_changed": False,
            "bit_identical": True,
            "identity_note": None,
            "seconds": 1.0,
            "differences_total": 0,
        }
        return {"results": [{"asset": "SPY", "error": None, "run_id": "r", "recheck": found}]}

    monkeypatch.setattr(test_cmds, "heartbeat", fake_heartbeat)
    monkeypatch.setattr(test_cmds, "recheck_idea", fake_recheck)
    parsed: Any = SimpleNamespace(assets=["SPY", "QQQ"], rule=SimpleNamespace(kind="sma"))
    settings: Any = SimpleNamespace(data_dir=tmp_path, random_seed=7)

    test_cmds._recheck(parsed, settings, False, None, False, True)

    captured = capsys.readouterr()
    assert "no time estimate yet" in captured.err or "takes about" in captured.err
    assert "Progress lines follow about every 10 seconds" in captured.err
    assert beats == ["alpha test: starting"]
    assert "no time estimate" not in captured.out
