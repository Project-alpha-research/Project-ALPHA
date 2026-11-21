"""`alpha labels weights` and `importance` refuse a stored barrier result that saw the reserved day.

A result made after the hold-back never holds a bar or event from the reserved day, so the
check passes it. An older one may, and it is told apart and refused, never used silently.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import polars as pl
import pytest
from typer.testing import CliRunner

from alpha_cli import labels_cmds
from alpha_cli.spine import reserve
from alpha_core.reserve import RESERVED_START
from tests.fixtures.reserve_read_fixtures import LONG, SHORT, write_store

LATE = datetime(2024, 2, 1, tzinfo=UTC)


class Worker:
    """A stand-in for the AFML worker that counts its calls and writes the files it must."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    def __call__(self, project: Path, argv: list[str], *, timeout: int = 900) -> dict[str, Any]:
        command, args = argv[0], argv[1:]
        self.calls.append(command)
        out = Path(args[args.index("--out") + 1])
        if command == "labels":
            bars = pl.read_parquet(args[0])
            pos = list(range(25, bars.height - 12, 9))
            pl.DataFrame(
                {
                    "ts": bars["ts"].gather(pos),
                    "pos": pos,
                    "end_pos": [p + 5 for p in pos],
                    "end": bars["ts"].gather([p + 5 for p in pos]),
                    "meta_label": [float(i % 2) for i in range(len(pos))],
                }
            ).write_parquet(out)
            Path(args[args.index("--figure") + 1]).write_bytes(b"\x89PNG")
            outcomes = {"target": 2, "stop": 2, "vertical": len(pos) - 4, "open": 0}
            return {
                "basis": "high_low",
                "events": len(pos),
                "decided": len(pos),
                "ambiguous": 0,
                "outcomes": outcomes,
            }
        events = pl.read_parquet(args[0])
        events.select(start="ts", end="end").with_columns(avg_uniqueness=pl.lit(0.8)).write_parquet(
            out
        )
        return {
            "labels": events.height,
            "labels_left_out": 0,
            "mean_avg_uniqueness": 0.8,
            "bootstrap_sample_uniqueness": 0.7,
            "plain_bootstrap_sample_uniqueness": 0.6,
            "max_library_gap": 0.0,
            "weights_scope": "every finished label",
        }


@pytest.fixture
def worker(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Worker:
    project = tmp_path / "worker"
    (project / ".venv" / "bin").mkdir(parents=True)
    (project / ".venv" / "bin" / "python").write_text("")
    (project / "pyproject.toml").write_text("")
    (project / "uv.lock").write_text("lock")
    (project / "src").mkdir()
    (project / "src" / "m.py").write_text("x = 1\n")
    stand_in = Worker()
    monkeypatch.setattr(labels_cmds, "_default_worker", lambda: project)
    monkeypatch.setattr(labels_cmds, "_call_worker", stand_in)
    return stand_in


def _run(*args: str) -> tuple[int, dict[str, Any]]:
    result = CliRunner().invoke(labels_cmds.labels_app, [*args, "--json"])
    return result.exit_code, json.loads(result.stdout.strip().splitlines()[-1])


def _barrier(home: Path, monkeypatch: pytest.MonkeyPatch, n: int, poisoned: bool) -> dict[str, Any]:
    write_store(home, n, poisoned=poisoned)
    monkeypatch.setenv("ALPHA_DATA_DIR", str(home))
    code, ran = _run("barrier", "--asset", "SPY")
    assert code == 0, ran
    return ran


def _make_old(result_dir: Path, name: str) -> None:
    """Rewrite one parent file as an older barrier result would have it: a row on the day."""
    path = result_dir / name
    frame = pl.read_parquet(path)
    last = frame.tail(1).with_columns(pl.lit(LATE).cast(frame.schema["ts"]).alias("ts"))
    pl.concat([frame, last]).write_parquet(path)


def test_a_result_made_after_the_hold_back_is_weighted(
    tmp_path: Path, worker: Worker, monkeypatch: pytest.MonkeyPatch
) -> None:
    ran = _barrier(tmp_path / "home", monkeypatch, LONG, poisoned=True)
    assert "reserve" in ran and reserve.HELD_BACK in ran["labels"]
    code, weighted = _run("weights", ran["result_id"])
    assert code == 0 and weighted["labels"][0] == "weights-whole-sample"
    assert "uniqueness" in worker.calls


@pytest.mark.parametrize("name", ["bars.parquet", "events.parquet"])
def test_weights_refuses_a_parent_holding_a_row_from_the_reserved_day(
    name: str, tmp_path: Path, worker: Worker, monkeypatch: pytest.MonkeyPatch
) -> None:
    ran = _barrier(tmp_path / "home", monkeypatch, SHORT, poisoned=False)
    _make_old(Path(ran["result_dir"]), name)
    calls = list(worker.calls)
    code, refused = _run("weights", ran["result_id"])
    assert code == 1 and refused["error"]["code"] == "RESERVED_PERIOD_SEEN"
    assert RESERVED_START in refused["error"]["message"]
    assert "alpha labels barrier" in refused["error"]["next"]
    assert worker.calls == calls  # the worker was never asked


def test_importance_refuses_the_same_parent(
    tmp_path: Path, worker: Worker, monkeypatch: pytest.MonkeyPatch
) -> None:
    ran = _barrier(tmp_path / "home", monkeypatch, SHORT, poisoned=False)
    _make_old(Path(ran["result_dir"]), "bars.parquet")
    factors = tmp_path / "factors.parquet"
    pl.read_parquet(Path(ran["result_dir"]) / "bars.parquet").select(
        "ts", f=pl.col("close")
    ).write_parquet(factors)
    calls = list(worker.calls)
    code, refused = _run("importance", ran["result_id"], "--factors", str(factors))
    assert code == 1 and refused["error"]["code"] == "RESERVED_PERIOD_SEEN"
    assert worker.calls == calls


def _stable(path: Path, home: Path) -> bytes:
    """A file's bytes; a JSON file without its creation time and with the home path named."""
    if path.suffix != ".json":
        return path.read_bytes()
    document = json.loads(path.read_text("utf-8"))
    document.pop("created_at", None)
    return json.dumps(document, sort_keys=True).replace(str(home), "HOME").encode()


def test_the_check_changes_nothing_for_a_parent_that_did_not_see_the_period(
    tmp_path: Path, worker: Worker, monkeypatch: pytest.MonkeyPatch
) -> None:
    outputs = []
    for checked in (True, False):
        home = tmp_path / str(checked)
        ran = _barrier(home, monkeypatch, SHORT, poisoned=False)
        if not checked:  # the same command as before the check existed
            monkeypatch.setattr(labels_cmds, "_refuse_parent_that_saw_period", lambda *_a: None)
        code, weighted = _run("weights", ran["result_id"])
        assert code == 0, weighted
        folder = Path(weighted.pop("result_dir"))
        files = {p.name: _stable(p, home) for p in sorted(folder.iterdir()) if p.is_file()}
        weighted.pop("created_at")
        outputs.append((json.dumps(weighted).replace(str(home), "HOME"), files))
    assert outputs[0] == outputs[1]
