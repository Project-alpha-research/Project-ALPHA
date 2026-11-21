"""`alpha propfirm run SYMBOL` holds the reserved period back; `--from-run` inherits its run."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import fields
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from alpha_cli import _runner
from alpha_cli.propfirm_cmds import propfirm_app
from alpha_cli.spine import reserve
from alpha_core.reserve import RESERVED_START
from tests.fixtures.reserve_read_fixtures import (
    HELD,
    LONG,
    SHORT,
    Spy,
    watch_loaders,
    write_store,
)

HELD_BACK = "reserved-period-held-back"
ARGS = ["SPY", "--n-paths", "200", "--seed", "7", "--horizon", "120"]


@pytest.fixture
def spy(monkeypatch: pytest.MonkeyPatch) -> Spy:
    return watch_loaders(monkeypatch)


def _run(home: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[str, dict[str, Any]]:
    monkeypatch.setenv("ALPHA_DATA_DIR", str(home))
    result = CliRunner().invoke(propfirm_app, ARGS)
    assert result.exit_code == 0, result.output
    paths = sorted((home / "propfirm").glob("*/manifest.json"))
    assert len(paths) == 1, paths
    manifest: dict[str, Any] = json.loads(paths[0].read_text())
    return result.output, manifest


def test_propfirm_reads_no_held_back_bar_or_action_and_equals_the_cut_store(
    tmp_path: Path, spy: Spy, monkeypatch: pytest.MonkeyPatch
) -> None:
    poisoned, cut = tmp_path / "poisoned", tmp_path / "cut"
    write_store(poisoned, LONG, poisoned=True)
    write_store(cut, SHORT, poisoned=False)
    _, held = _run(poisoned, monkeypatch)
    spy.assert_nothing_from_the_reserved_day()
    _, plain = _run(cut, monkeypatch)
    for key, value in held["metrics"].items():
        assert value == pytest.approx(plain["metrics"][key], rel=1e-9, abs=1e-12), key
    assert held["horizon_days"] == plain["horizon_days"]


def test_propfirm_records_and_says_what_it_held_back(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = tmp_path / "poisoned"
    write_store(home, LONG, poisoned=True)
    out, manifest = _run(home, monkeypatch)
    assert manifest["reserve"] == {"reserved_start": RESERVED_START, "held_back_bars": HELD}
    assert HELD_BACK in manifest["labels"]
    assert manifest["research_cutoff"] == "2023-12-31"
    assert reserve.sentence(HELD) in out


def test_propfirm_run_id_is_unchanged_when_no_bar_was_held_back(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = tmp_path / "cut"
    write_store(home, SHORT, poisoned=False)
    payloads: list[Mapping[str, object]] = []
    real = _runner.run_identity_for

    def watch(payload: Mapping[str, object], **kwargs: Any) -> Any:
        payloads.append(payload)
        return real(payload, **kwargs)

    monkeypatch.setattr(_runner, "run_identity_for", watch)
    out, manifest = _run(home, monkeypatch)
    assert "reserve" not in manifest and "labels" not in manifest
    assert "research_cutoff" not in manifest and "Held back" not in out
    # The payload that makes the run id is the one before this change: no new key.
    before = {"command", "firm", "overrides", "n_paths", "mean_block", "horizon", "seed"}
    before |= {"symbol", "snapshot"} | {f.name for f in fields(_runner.RunSpec)}
    assert [set(payload) for payload in payloads] == [before]
