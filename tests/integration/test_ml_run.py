"""`alpha ml run`: plain spec -> frozen snapshot -> worker -> costed replay -> ordinary run."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import polars as pl
import pytest
from typer.testing import CliRunner

from alpha_cli import ml_cmds, ml_run
from alpha_cli.main import app
from alpha_cli.ml_result_validation import validate_result_bundle
from alpha_cli.spine.ledger import read_trials
from alpha_cli.spine.trial_reader import family_counts, spine_snapshot
from alpha_cli.spine.trial_record import map_row
from alpha_data.store import ParquetStore

REPO = Path(__file__).parents[2]
SYMBOLS = [f"S{i:02d}" for i in range(20)]
SESSIONS = 1200  # from 2021-01-04: crosses the held-back day 2024-01-01
SharedRun = tuple[Path, dict[str, Any]]


def _seed_store(home: Path) -> None:
    store = ParquetStore(home / "store")
    first = datetime(2021, 1, 4, tzinfo=UTC)
    for index, symbol in enumerate(SYMBOLS):
        rows = []
        for day in range(SESSIONS):
            price = 100.0 + day * 0.01 + index * 0.1 + ((day * (index + 3)) % 7) * 0.05
            rows.append(
                {
                    "ts": first + timedelta(days=day),
                    "open": price,
                    "high": price + 1.0,
                    "low": price - 1.0,
                    "close": price + 0.25,
                    "volume": 1_000_000.0,
                }
            )
        store.write_bars(symbol, pl.DataFrame(rows))
        store.write_provenance(
            symbol, source="synthetic:test", adapter_version="1", parser_version="1"
        )


def _spec(tmp_path: Path, extra: str = "") -> Path:
    path = tmp_path / "spec.toml"
    assets = ", ".join(f'"{s}"' for s in SYMBOLS)
    path.write_text(
        f'name = "synthetic gbm"\nassets = [{assets}]\n{extra}'
        "[split]\ntrain_days = 504\nvalidation_days = 120\ntest_days = 63\n",
        encoding="utf-8",
    )
    return path


def _fake_worker(exchange: Path, **_: object) -> object:
    """Run the repo's fake worker the way `test_ml_cli` does, then validate its result."""
    env = dict(os.environ)
    env["PYTHONPATH"] = str(REPO / "workers/qlib/src")
    subprocess.run(
        [
            sys.executable,
            "-m",
            "alpha_qlib_worker",
            "fake",
            str(exchange),
            "--worker-lock",
            str(REPO / "workers/qlib/uv.lock"),
        ],
        cwd=REPO,
        env=env,
        check=True,
    )
    return validate_result_bundle(exchange)


def _patch_worker(patch: pytest.MonkeyPatch, data: Path) -> None:
    patch.setattr(ml_cmds, "train_exchange", _fake_worker)
    patch.setattr(ml_run, "_require_worker", lambda project: REPO / "workers/qlib")
    patch.setenv("ALPHA_DATA_DIR", str(data))


@pytest.fixture(scope="module")
def _seeded(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Build the 20-symbol store once; each test gets its own copy of it."""
    data = tmp_path_factory.mktemp("ml-run-seed") / "alpha-data"
    _seed_store(data)
    return data


@pytest.fixture
def home(_seeded: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    data = tmp_path / "alpha-data"
    shutil.copytree(_seeded, data)
    _patch_worker(monkeypatch, data)
    return data


@pytest.fixture(scope="module")
def _shared_run(_seeded: Path, tmp_path_factory: pytest.TempPathFactory) -> SharedRun:
    """Run the fake worker once on a copy of the seeded store, for the tests that only read it."""
    root = tmp_path_factory.mktemp("ml-run-shared")
    data = root / "alpha-data"
    shutil.copytree(_seeded, data)
    with pytest.MonkeyPatch.context() as patch:
        _patch_worker(patch, data)
        result = ml_run.run_spec(_spec(root), data_dir=data)
    return data, result


@pytest.fixture
def ran_home(_shared_run: SharedRun, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> SharedRun:
    """This test's own copy of the shared run, patched the same way as `home`."""
    data = tmp_path / "alpha-data"
    shutil.copytree(_shared_run[0], data)
    _patch_worker(monkeypatch, data)
    return data, _shared_run[1]


def test_run_end_to_end_with_fake_worker(home: Path, tmp_path: Path) -> None:
    result = ml_run.run_spec(_spec(tmp_path), data_dir=home)
    manifest = json.loads((home / "runs" / result["run_id"] / "manifest.json").read_text())
    assert manifest["command"] == "ml_replay"
    assert manifest["costs"]["fee_bps"] > 0
    # Training and test windows are stated and never overlap; nothing from the held-back day on.
    folds = result["folds"]
    assert all(f["train_end"] < f["test_start"] for f in folds)
    assert folds[-1]["test_end"] < "2024-01-01"
    assert f"refit {len(folds)} times" in result["split_sentence"]
    assert "No model saw its own test days" in result["split_sentence"]
    assert "not recomputed under counterfactual" in result["label"]
    assert result["validation"]["promotion_eligible"] is False
    assert result["validation"]["counterfactual_refit"] is False
    assert "Held back" in result["reserve_sentence"]
    assert manifest["reserve"]["held_back_bars"] > 0


def test_run_counts_one_try_in_family_qlib(home: Path, tmp_path: Path) -> None:
    spec = _spec(tmp_path)
    first = ml_run.run_spec(spec, data_dir=home)
    rows = [row for row in read_trials(home) if row["kind"] == "ml_run"]
    assert len(rows) == 1
    assert rows[0]["run_id"] == first["run_id"]
    assert "1 try" in first["tries_sentence"]
    again = ml_run.run_spec(spec, data_dir=home)
    assert again["run_id"] == first["run_id"]
    assert "counted before" in again["tries_sentence"]
    mapped = map_row("spine", home / "ledger" / "trials.jsonl", 1, rows[0])
    assert mapped.family_id == "qlib"


def test_missing_worker_environment_says_what_to_run(
    home: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.undo()
    monkeypatch.setenv("ALPHA_DATA_DIR", str(home))
    project = tmp_path / "worker"
    project.mkdir()
    (project / "pyproject.toml").write_text("[project]\nname='x'\n")
    (project / "uv.lock").write_text("")
    with pytest.raises(ml_run.MlRunError, match=r"bash scripts/setup\.sh"):
        ml_run.run_spec(_spec(tmp_path), data_dir=home, worker_project=project)


@pytest.mark.parametrize(
    ("extra", "words"),
    [
        ('model = "xgboost"\n', "lightgbm"),
        ('features = "alpha999"\n', "alpha158"),
        ("horizon_days = 5\n", "1 day"),
    ],
)
def test_bad_spec_fails_loud(home: Path, tmp_path: Path, extra: str, words: str) -> None:
    with pytest.raises(ml_run.MlRunError, match=words):
        ml_run.run_spec(_spec(tmp_path, extra), data_dir=home)


def test_too_few_assets_say_how_many_are_needed(home: Path, tmp_path: Path) -> None:
    spec = tmp_path / "few.toml"
    spec.write_text('assets = ["S00", "S01", "S02"]\n', encoding="utf-8")
    with pytest.raises(
        ml_run.MlRunError, match=r"at least 20 assets.*has 3.*rank.*ml-gbm-etfs\.toml"
    ):
        ml_run.run_spec(spec, data_dir=home)


def test_cli_command_is_registered(home: Path, tmp_path: Path) -> None:
    out = CliRunner().invoke(app, ["ml", "run", str(tmp_path / "missing.toml")])
    assert out.exit_code != 0
    assert "missing.toml" in out.output


def test_new_split_action_makes_a_new_snapshot(home: Path) -> None:
    store = ParquetStore(home / "store")
    first = ml_run._freeze(home, SYMBOLS)
    assert ml_run._freeze(home, SYMBOLS) == first
    actions = store._actions_path(SYMBOLS[0])
    actions.parent.mkdir(parents=True, exist_ok=True)
    actions.write_text("changed")
    assert ml_run._freeze(home, SYMBOLS) != first


def test_ml_run_counts_in_family_qlib_totals(home: Path, tmp_path: Path) -> None:
    spec = _spec(tmp_path)
    ml_run.run_spec(spec, data_dir=home)
    ml_run.run_spec(spec, data_dir=home)  # a repeat adds nothing
    counts = {row["family_id"]: row for row in family_counts(spine_snapshot(home))}
    assert counts["qlib"]["reader_trials"] == 1


def test_a_finished_build_is_reused_under_its_lock_file(home: Path, tmp_path: Path) -> None:
    """A second run on the same key reuses the finished exchange; a lock file guards builds."""
    spec = _spec(tmp_path)
    first = ml_run.run_spec(spec, data_dir=home)
    base = next(path for path in (home / "ml_runs").iterdir() if path.is_dir())
    assert (base / "done").is_file()
    assert (home / "ml_runs" / f"{base.name}.lock").is_file()
    assert ml_run.run_spec(spec, data_dir=home)["run_id"] == first["run_id"]


def test_as_of_cutoff_is_kept_in_the_stored_run(home: Path, tmp_path: Path) -> None:
    result = ml_run.run_spec(_spec(tmp_path), data_dir=home, as_of="2023-06-30")
    manifest = json.loads((home / "runs" / result["run_id"] / "manifest.json").read_text())
    assert manifest["research_cutoff"] == "2023-06-30"
    assert result["folds"][-1]["test_end"] <= "2023-06-30"


def test_a_tampered_snapshot_is_not_reused(home: Path) -> None:
    store = ParquetStore(home / "store")
    snapshot_id = ml_run._freeze(home, SYMBOLS)
    bars = ParquetStore(home / "snapshots" / snapshot_id)._bars_path(SYMBOLS[0])
    bars.chmod(0o644)
    bars.write_bytes(bars.read_bytes() + b"x")
    assert store._bars_path(SYMBOLS[0]).is_file()
    with pytest.raises(ml_run.MlRunError, match="changed while it was frozen"):
        ml_run._freeze(home, SYMBOLS)


def test_results_list_an_ml_run_without_calling_it_a_fault(ran_home: SharedRun) -> None:
    run_id = ran_home[1]["run_id"]
    listed = CliRunner().invoke(app, ["results"])
    line = next(line for line in listed.output.splitlines() if run_id in line)
    assert "ml_run" in line
    assert "fault" not in line


def test_result_readers_say_an_ml_run_has_no_diagnostics(ran_home: SharedRun) -> None:
    run_id = ran_home[1]["run_id"]
    runner = CliRunner()
    report = runner.invoke(app, ["report", run_id])
    assert report.exit_code == 0, report.output
    assert "ml_replay" in report.output
    shown = json.loads(runner.invoke(app, ["results", "show", run_id, "--json"]).output)
    assert "ML run" in shown["runs"][0]["diagnostics_reason"]
    assert "re-run alpha test" not in shown["runs"][0]["diagnostics_reason"]
    diagnosed = runner.invoke(app, ["diagnose", run_id, "--json"])
    assert diagnosed.exit_code != 0
    assert "ML replay" in diagnosed.output
    assert "alpha report" in diagnosed.output


def _show(run_id: str) -> str:
    out = CliRunner().invoke(app, ["results", "show", run_id])
    assert out.exit_code == 0, out.output
    return out.output


def test_results_show_reads_an_ml_run_in_plain_words(ran_home: SharedRun) -> None:
    run_id = ran_home[1]["run_id"]

    text = _show(run_id)

    assert "Fault" not in text and "No reading" not in text
    assert "refit" in text and "No model saw its own test days" in text
    assert "20 assets" in text and "lightgbm" in text.lower()
    assert "bp fee" in text and "slippage" in text
    assert "equal-weight basket" in text and "Sharpe" in text
    assert "1 try" in text or "tries" in text
    shown = json.loads(CliRunner().invoke(app, ["results", "show", run_id, "--json"]).output)
    assert shown["runs"][0]["reading"]["kind"] == "ml_run"


def test_report_names_the_assets_and_gives_the_reading(ran_home: SharedRun) -> None:
    run_id = ran_home[1]["run_id"]

    out = CliRunner().invoke(app, ["report", run_id]).output

    assert "[?]" not in out and "S00" in out
    assert "equal-weight basket" in out and "No model saw its own test days" in out


def test_run_prints_a_fold_table_not_raw_dict_lines(home: Path, tmp_path: Path) -> None:
    out = CliRunner().invoke(app, ["ml", "run", str(_spec(tmp_path))]).output

    assert "train_start" not in out and "{'" not in out
    assert "FOLD\tTRAIN" in out
    assert "equal-weight basket" in out


def test_a_check_that_needs_only_stored_equity_accepts_an_ml_run(ran_home: SharedRun) -> None:
    run_id = ran_home[1]["run_id"]

    out = CliRunner().invoke(app, ["tool", "run", "performance.ulcer", run_id, "--json"])

    assert out.exit_code == 0, out.output
    assert "not made by alpha test" not in out.output


def test_a_check_that_needs_one_rules_bars_says_why_it_does_not_apply(
    ran_home: SharedRun,
) -> None:
    run_id = ran_home[1]["run_id"]

    out = CliRunner().invoke(app, ["tool", "run", "parameters.price_noise", run_id])

    assert out.exit_code != 0
    assert "model run" in out.output and "one rule" in out.output


def test_every_check_either_runs_or_says_why_on_an_ml_run(ran_home: SharedRun) -> None:
    """No check may crash or say the run is not a rule test; each runs or gives one reason."""
    from alpha_cli.toolbox.registry import SPECS

    run_id = ran_home[1]["run_id"]
    stored = {"stored_equity", "run_trades"}
    ran: list[str] = []
    refused: list[str] = []
    for spec in SPECS:
        if spec.compute is None or not set(spec.needs) <= stored:
            continue
        out = CliRunner().invoke(app, ["tool", "run", spec.id, run_id, "--json"])
        assert "not made by alpha test" not in out.output, spec.id
        assert "Traceback" not in out.output and "KeyError" not in out.output, (spec.id, out.output)
        (ran if out.exit_code == 0 else refused).append(spec.id)
        if out.exit_code != 0:
            assert "model run" in out.output or "at least" in out.output, (spec.id, out.output)
    assert len(ran) > 20
