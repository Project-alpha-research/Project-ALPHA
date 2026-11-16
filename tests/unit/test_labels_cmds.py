"""`alpha labels`: the factor join and the commands, with a stand-in for the worker."""

from __future__ import annotations

import json
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import polars as pl
import pytest
from typer.testing import CliRunner

from alpha_cli import labels_cmds
from alpha_cli.labels_cmds import _factor_table
from alpha_cli.spine.errors import SpineError
from alpha_data.store import ParquetStore
from tests.fixtures.cli_fixtures import seed_store

START = datetime(2024, 1, 1, tzinfo=UTC)


def _folders(tmp_path: Path, n: int = 40) -> tuple[Path, Path, pl.Series]:
    parent, staging = tmp_path / "parent", tmp_path / "staging"
    parent.mkdir()
    staging.mkdir()
    ts = pl.Series([START + timedelta(days=i) for i in range(n)], dtype=pl.Datetime("us", "UTC"))
    pos = list(range(0, n, 2))
    pl.DataFrame({
        "ts": ts.gather(pos), "pos": pos, "end_pos": [p + 1 for p in pos],
        "meta_label": [float(i % 2) for i in range(len(pos))],
    }).write_parquet(parent / "events.parquet")  # fmt: skip
    weights = {"start": ts.gather(pos), "end": ts.gather([p + 1 for p in pos])}
    pl.DataFrame({**weights, "avg_uniqueness": [1.0] * len(pos)}).write_parquet(
        staging / "weights.parquet"
    )
    return parent, staging, ts


def _factors(ts: pl.Series, path: Path, **columns: list[float | None]) -> Path:
    pl.DataFrame({"ts": ts, **columns}).write_parquet(path)
    return path


def test_every_decided_event_must_find_its_factor_row(tmp_path: Path) -> None:
    parent, staging, ts = _folders(tmp_path)
    half = _factors(ts.head(20), tmp_path / "half.parquet", f=[1.0 * i for i in range(20)])
    with pytest.raises(ValueError, match="10 of 20 events"):
        _factor_table(parent, half, staging)
    gaps = [None if i % 3 == 0 else float(i) for i in range(40)]
    with pytest.raises(ValueError, match="of 20 events"):
        _factor_table(parent, _factors(ts, tmp_path / "gaps.parquet", f=gaps), staging)


def test_shifted_or_naive_local_times_fail_with_the_match_count(tmp_path: Path) -> None:
    parent, staging, ts = _folders(tmp_path)
    shifted = ts.dt.offset_by("5h")
    with pytest.raises(ValueError, match="0 of 20 events"):
        _factor_table(parent, _factors(shifted, tmp_path / "s.parquet", f=[1.0] * 40), staging)


def test_an_unsorted_factor_file_is_accepted_and_rows_stay_in_time_order(tmp_path: Path) -> None:
    parent, staging, ts = _folders(tmp_path)
    frame = pl.DataFrame({"ts": ts, "f": [float(i) for i in range(40)]}).sample(
        fraction=1.0, shuffle=True, seed=3
    )
    frame.write_parquet(tmp_path / "shuffled.parquet")
    path, names = _factor_table(parent, tmp_path / "shuffled.parquet", staging)
    table = pl.read_parquet(path)
    assert names == ["f"] and table.height == 20
    assert table["start"].to_list() == sorted(table["start"].to_list())
    assert table["f"].to_list() == [float(p) for p in table["start"].to_list()]


# --- the commands, with the worker replaced by a stand-in that writes its files ----------------


def _stand_in(project: Path, argv: list[str], *, timeout: int = 900) -> dict[str, Any]:
    """Writes what the real worker writes, from the files it is given."""
    command, args = argv[0], argv[1:]
    out = Path(args[args.index("--out") + 1])
    if command == "labels":
        bars = pl.read_parquet(args[0])
        pos = list(range(25, bars.height - 12, 9))
        pl.DataFrame({
            "ts": bars["ts"].gather(pos), "pos": pos, "end_pos": [p + 5 for p in pos],
            "end": bars["ts"].gather([p + 5 for p in pos]),
            "meta_label": [float(i % 2) for i in range(len(pos))],
        }).write_parquet(out)  # fmt: skip
        if "--figure" in args:
            Path(args[args.index("--figure") + 1]).write_bytes(b"\x89PNG")
        if "--basis" in args and args[args.index("--basis") + 1] == "close":
            return {"basis": "close", "events": len(pos), "decided": len(pos),
                    "libraries_disagree_explained": 0}  # fmt: skip
        outcomes = {"target": 2, "stop": 2, "vertical": len(pos) - 4, "open": 0}
        return {"basis": "high_low", "events": len(pos), "decided": len(pos), "ambiguous": 1,
                "outcomes": outcomes}  # fmt: skip
    if command == "uniqueness":
        events = pl.read_parquet(args[0])
        events.select(start="ts", end="end").with_columns(avg_uniqueness=pl.lit(0.8)).write_parquet(
            out
        )
        scope = "labels ending on or before x" if "--train-end" in args else "every finished label"
        return {"labels": events.height, "labels_left_out": 0, "mean_avg_uniqueness": 0.8,
                "bootstrap_sample_uniqueness": 0.7, "plain_bootstrap_sample_uniqueness": 0.6,
                "max_library_gap": 0.0, "weights_scope": scope}  # fmt: skip
    if command == "importance":
        table = pl.read_parquet(args[0])
        names = [c for c in table.columns if c not in {"start", "end", "label", "weight"}]
        report = {kind: {n: {"mean": 0.1, "std": 0.01} for n in names}
                  for kind in ("mdi", "mda", "sfi")}  # fmt: skip
        out.write_text(json.dumps(report))
        return {"rows": table.height, "features": len(names), "folds": 5}
    raise AssertionError(command)


@pytest.fixture
def home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    data = tmp_path / "data"
    seed_store(data, symbol="SPY", n=120)
    ParquetStore(data / "store").write_provenance(
        "SPY", source="alpaca", adapter_version="1", parser_version="1"
    )
    project = tmp_path / "worker"
    (project / ".venv" / "bin").mkdir(parents=True)
    (project / ".venv" / "bin" / "python").write_text("")
    (project / "pyproject.toml").write_text("")
    (project / "uv.lock").write_text("lock")
    (project / "src").mkdir()
    (project / "src" / "m.py").write_text("x = 1\n")
    monkeypatch.setenv("ALPHA_DATA_DIR", str(data))
    monkeypatch.setattr(labels_cmds, "_default_worker", lambda: project)
    monkeypatch.setattr(labels_cmds, "_call_worker", _stand_in)
    return data


def _run(*args: str) -> tuple[int, dict[str, Any]]:
    result = CliRunner().invoke(labels_cmds.labels_app, [*args, "--json"])
    return result.exit_code, json.loads(result.stdout.strip().splitlines()[-1])


def test_barrier_weights_and_importance_publish_result_folders(home: Path, tmp_path: Path) -> None:
    code, ran = _run("barrier", "--asset", "SPY")
    assert code == 0 and not ran["repeat"]
    assert {"bars.parquet", "events.parquet", "labels.png", "result.json", "theme.json"} <= {
        p.name for p in Path(ran["result_dir"]).iterdir()
    }
    assert "small-sample" in ran["labels"] and "ambiguous-bars" in ran["labels"]
    facts = {f["metric"]: f for f in ran["facts"]}
    assert facts["target"]["value"] == 2 and "high/low" in facts["target"]["basis"]
    assert _run("barrier", "--asset", "SPY")[1]["repeat"]

    code, weighted = _run("weights", ran["result_id"], "--train-end", "2020-03-01")
    assert code == 0 and weighted["labels"][0] == "weights-train-only"
    assert _run("weights", ran["result_id"])[1]["labels"][0] == "weights-whole-sample"

    bars = pl.read_parquet(Path(ran["result_dir"]) / "bars.parquet")
    factors = tmp_path / "factors.parquet"
    bars.select("ts", f=pl.col("close"), g=pl.col("close") * 2).write_parquet(factors)
    code, report = _run("importance", ran["result_id"], "--factors", str(factors))
    assert code == 0 and "report-only" in report["labels"]
    assert {f["metric"] for f in report["facts"]} >= {"mdi:f", "sfi:g"}

    code, close = _run("barrier", "--asset", "SPY", "--basis", "close")
    assert code == 0 and "parity-basis" in close["labels"]
    code, refused = _run("weights", close["result_id"])
    assert code == 1 and refused["error"]["code"] == "WRONG_BASIS"


def test_refusals_name_the_problem(home: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    assert (
        _run("barrier", "--asset", "SPY", "--basis", "both")[1]["error"]["code"] == "UNKNOWN_BASIS"
    )
    assert _run("weights", "nope")[1]["error"]["code"] == "UNKNOWN_RESULT"
    assert (
        _run("importance", "nope", "--factors", "x.parquet")[1]["error"]["code"] == "UNKNOWN_RESULT"
    )
    code, missing = _run("barrier", "--asset", "QQQ")
    assert code == 1 and missing["error"]["code"] == "LABELS_FAILED"
    code, bad_date = _run("weights", "x", "--train-end", "2020-03-01T00:00")
    assert code == 1


def test_missing_worker_names_the_setup_step(tmp_path: Path) -> None:
    with pytest.raises(SpineError) as absent:
        labels_cmds._worker(tmp_path / "nowhere")
    assert absent.value.payload["code"] == "WORKER_MISSING"
    (tmp_path / "w").mkdir()
    (tmp_path / "w" / "pyproject.toml").write_text("")
    (tmp_path / "w" / "uv.lock").write_text("")
    with pytest.raises(SpineError) as bare:
        labels_cmds._worker(tmp_path / "w")
    assert bare.value.payload["next"].endswith(labels_cmds.SETUP_STEP)


def test_train_end_parsing() -> None:
    assert labels_cmds._parse_train_end(None) is None
    assert labels_cmds._parse_train_end("2024-01-02") == datetime(2024, 1, 2, tzinfo=UTC)
    with pytest.raises(ValueError, match="zone"):
        labels_cmds._parse_train_end("2024-01-02T10:00")


def test_worker_failure_is_reported_with_its_last_line(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fake_run(*args: Any, **kwargs: Any) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(
            args, 2, "", "trace\nalpha-afml-worker: ContractError: bad\n"
        )

    monkeypatch.setattr("alpha_cli.labels_cmds.shutil.which", lambda name: "/usr/bin/uv")
    monkeypatch.setattr("alpha_cli.labels_cmds.subprocess.run", fake_run)
    with pytest.raises(SpineError) as failed:
        labels_cmds._call_worker(tmp_path, ["capabilities"])
    assert "ContractError: bad" in str(failed.value)

    def ok_run(*args: Any, **kwargs: Any) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(args, 0, '{"ok": 1}', "")

    monkeypatch.setattr("alpha_cli.labels_cmds.subprocess.run", ok_run)
    assert labels_cmds._call_worker(tmp_path, ["capabilities"]) == {"ok": 1}
    monkeypatch.setattr("alpha_cli.labels_cmds.shutil.which", lambda name: None)
    with pytest.raises(SpineError):
        labels_cmds._call_worker(tmp_path, ["capabilities"])
