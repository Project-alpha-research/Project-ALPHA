"""Setup studies measure recorded occurrences without changing detection."""

import hashlib
import json
from pathlib import Path
from typing import Any

import polars as pl
import pytest
from typer.testing import CliRunner

from alpha_cli import results_cmds, setup_cmds
from alpha_cli.spine import setup_study
from alpha_cli.spine.errors import SpineError
from alpha_cli.spine.facts import METRIC_UNITS
from alpha_cli.spine.ledger import read_trials
from alpha_cli.spine.trial_reader import family_counts, spine_snapshot
from tests.unit.test_setup_find import seed, spec_file


def make_find(home: Path, *, study: bool = True) -> dict[str, Any]:
    store = seed(home)
    frame = store.read_bars("SPY")
    # Entries 3, 31, 61, 96; event 3 joins event 2's cluster and is not an occurrence.
    frame = frame.with_columns(
        pl.Series("open", [100.0] * 100),
        pl.Series("close", [100.0 + i for i in range(100)]),
        pl.Series("high", [201.0] * 100),
        pl.Series("low", [99.0] * 100),
        pl.Series("volume", [float(i in (2, 3, 30, 60, 95)) for i in range(100)]),
    )
    store.write_bars("SPY", frame)
    path = spec_file(home)
    if study:
        path.write_text(path.read_text() + "[study]\nhorizons=[1,5,20]\nprimary=5\n")
    return setup_cmds.run_find(path, home=home)


def snapshot(folder: Path) -> dict[str, tuple[int, bytes]]:
    return {
        str(p.relative_to(folder)): (p.stat().st_mtime_ns, p.read_bytes())
        for p in folder.rglob("*")
        if p.is_file()
    }


def test_returns_incomplete_facts_repeat_and_blindness(tmp_path: Path) -> None:
    found = make_find(tmp_path)
    before = snapshot(Path(found["folder"]))
    out = setup_study.run_study(found["find_id"], home=tmp_path)
    expected_id = hashlib.sha256((found["find_id"] + "|setup-study-1").encode()).hexdigest()[:16]
    assert out["study_id"] == expected_id
    assert out["matching_days"] == 5 and out["occurrences"] == 4
    rows = pl.read_parquet(Path(out["folder"]) / "outcomes.parquet")
    assert rows.height == 12
    first = rows.filter(pl.col("candidate_id") == 1).sort("horizon")
    assert first["gross_return"].to_list() == pytest.approx([0.03, 0.07, 0.22])
    assert first["net_return"].to_list() == pytest.approx([0.0294, 0.0694, 0.2194])
    assert first["net_path"][0].to_list() == pytest.approx([i / 100 - 0.0006 for i in range(3, 23)])
    assert out["horizons"]["1"]["pooled"]["occurrences"] == 4
    for horizon in ("5", "20"):
        row = out["horizons"][horizon]["pooled"]
        assert row["occurrences"] == 3 and row["incomplete"] == 1
    assert out["horizons"]["1"]["labels"] == ["not-primary"]
    assert {"exploratory", "too-few-occurrences", "single-asset", "short-history"} <= set(
        out["labels"]
    )
    assert "outcomes-not-viewed" not in out["labels"]
    assert out["reading"].startswith("Too few occurrences (3)")
    facts = {f["metric"]: f for f in out["facts"]}
    assert METRIC_UNITS["setup_occurrences"] == "count"
    assert METRIC_UNITS["setup_mean_net_return"] == "fraction"
    assert facts["setup_mean_net_return"]["value"] == pytest.approx(
        (0.07 + 0.35 + 0.65) / 3 - 0.0006
    )
    assert all(f["run_id"] == expected_id and f["basis"] and f["source"] for f in facts.values())
    stored = snapshot(Path(out["folder"]))
    repeat = setup_study.run_study(found["find_id"], home=tmp_path)
    assert "repeat" in repeat["labels"] and "repeat" in repeat["facts"][0]["labels"]
    assert snapshot(Path(out["folder"])) == stored
    setup_cmds.run_find(tmp_path / "spec.toml", home=tmp_path)
    assert snapshot(Path(found["folder"])) == before
    ledger = spine_snapshot(tmp_path)
    assert [r.counts_for_deflation for r in ledger.records] == [False, True, False, False]
    studies = [r for r in ledger.records if r.kind == "setup_study"]
    assert studies[0].family_id == "setup:inspect matches"
    assert studies[0].outcome == "inconclusive"
    assert sum(r["reader_trials"] for r in family_counts(ledger)) == 1
    assert read_trials(tmp_path)[1]["verdict"] is None


@pytest.mark.parametrize("code", ["FIND_NOT_FOUND", "SPEC_HAS_NO_STUDY", "DATA_CHANGED_SINCE_FIND"])
def test_errors(tmp_path: Path, code: str) -> None:
    found = make_find(tmp_path, study=code != "SPEC_HAS_NO_STUDY")
    if code == "DATA_CHANGED_SINCE_FIND":
        from alpha_data.store import ParquetStore

        store = ParquetStore(tmp_path / "store")
        store.write_bars(
            "SPY", store.read_bars("SPY").with_columns((pl.col("volume") + 1).alias("volume"))
        )
    with pytest.raises(SpineError) as caught:
        setup_study.run_study(
            "missing" if code == "FIND_NOT_FOUND" else found["find_id"], home=tmp_path
        )
    assert caught.value.payload["code"] == code
    assert not list((tmp_path / "setup-studies").glob("*/manifest.json"))


def test_manifest_last_and_detection_not_recomputed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from alpha_study.setup import evaluate

    found = make_find(tmp_path)

    def broken(*args: Any, **kwargs: Any) -> bytes:
        raise OSError("draw failed")

    def no_detection(*args: Any, **kwargs: Any) -> None:
        pytest.fail("study must only read the recorded candidates")

    monkeypatch.setattr(evaluate, "find_candidates", no_detection)
    monkeypatch.setattr(setup_study, "draw_event_study", broken)
    with pytest.raises(SpineError, match="draw failed") as caught:
        setup_study.run_study(found["find_id"], home=tmp_path)
    assert caught.value.payload["code"] == "STUDY_FAILED"
    assert not list((tmp_path / "setup-studies").glob("*/manifest.json"))
    assert len(read_trials(tmp_path)) == 1


def test_command_cite_check_and_ledger(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from alpha_cli.ledger_cmds import ledger_app

    found = make_find(tmp_path)
    monkeypatch.setenv("ALPHA_DATA_DIR", str(tmp_path))
    runner = CliRunner()
    result = runner.invoke(setup_cmds.setup_app, ["study", found["find_id"], "--json"])
    assert result.exit_code == 0, result.output
    out = json.loads(result.stdout)
    study_id = out["study_id"]
    cite = runner.invoke(
        results_cmds.results_app, ["cite", study_id, "setup_mean_net_return", "--json"]
    )
    assert cite.exit_code == 0, cite.output
    fact = json.loads(cite.stdout)
    assert fact == next(f for f in out["facts"] if f["metric"] == "setup_mean_net_return")
    assert results_cmds.fact_lookup(tmp_path)(study_id, "setup_mean_net_return") == fact
    count = results_cmds.fact_lookup(tmp_path)(study_id, "total_trials")
    draft = tmp_path / "draft.md"
    draft.write_text(
        f"Exploratory, short history. Return {fact['value']:.2%} "
        f"[{study_id}:setup_mean_net_return]. "
        f"Trials {count['value']} [{study_id}:total_trials]."
    )
    checked = runner.invoke(results_cmds.results_app, ["check", str(draft), "--json"])
    assert checked.exit_code == 0, checked.output
    human = runner.invoke(setup_cmds.setup_app, ["study", found["find_id"]])
    assert human.exit_code == 0 and human.stdout.startswith(out["reading"])
    assert "also looked at, not tested" in human.stdout
    assert f"Next: alpha results cite {study_id} setup_mean_net_return" in human.stdout
    for command in ("summary", "list", "families"):
        report = runner.invoke(ledger_app, [command, "--json"])
        assert report.exit_code == 0, report.output
        assert "setup_study" in report.stdout


def test_no_occurrences_and_manifest_publication_order(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from alpha_core.atomic import write_text

    seed(tmp_path)
    path = spec_file(tmp_path)
    path.write_text(path.read_text() + "[study]\nhorizons=[1,5]\nprimary=5\n")
    found = setup_cmds.run_find(path, home=tmp_path)
    writes: list[str] = []

    def record(path: Path, text: str) -> None:
        if path.name == "manifest.json":
            assert {p.name for p in path.parent.iterdir()} == {
                "outcomes.parquet",
                "summary.json",
                "event-study.png",
            }
        writes.append(path.name)
        write_text(path, text)

    monkeypatch.setattr(setup_study, "write_text", record)
    out = setup_study.run_study(found["find_id"], home=tmp_path)
    assert writes == ["summary.json", "manifest.json"]
    assert out["occurrences"] == 0
    assert out["reading"].startswith("Too few occurrences (0)")
    assert all(f["value"] is not None or f["reason"] for f in out["facts"])
    assert pl.read_parquet(Path(out["folder"]) / "outcomes.parquet").height == 0
    # Citation and repeats must reject a changed sidecar rather than trusting its number.
    summary = Path(out["folder"]) / "summary.json"
    summary.write_text(summary.read_text() + " ")
    with pytest.raises(ValueError, match="artifact changed"):
        results_cmds.fact_lookup(tmp_path)(out["study_id"], "setup_mean_net_return")
    with pytest.raises(SpineError, match="artifact changed"):
        setup_study.run_study(found["find_id"], home=tmp_path)


def test_warmup_uses_all_evaluator_expressions(tmp_path: Path) -> None:
    from alpha_cli.spine.setup_find import study_inputs
    from alpha_study.setup.expr import compile_expr
    from alpha_study.setup.spec import SetupSpec

    seed(tmp_path)
    path = spec_file(tmp_path)
    path.write_text(path.read_text().replace('base="low"', 'base="sma(close, 20)"'))
    found = setup_cmds.run_find(path, home=tmp_path)
    manifest = json.loads((Path(found["folder"]) / "manifest.json").read_text())
    _, warmup = study_inputs(tmp_path, manifest, SetupSpec.load(path))
    assert warmup == compile_expr("sma(close, 20)").warmup == 19


def test_corrupt_candidates_fail_with_structured_study_error(tmp_path: Path) -> None:
    found = make_find(tmp_path)
    (Path(found["folder"]) / "candidates.parquet").write_bytes(b"broken parquet")
    with pytest.raises(SpineError) as caught:
        setup_study.run_study(found["find_id"], home=tmp_path)
    assert caught.value.payload["code"] == "STUDY_FAILED"


def test_changing_the_primary_horizon_is_a_new_counted_trial(tmp_path: Path) -> None:
    found = make_find(tmp_path)
    first = setup_study.run_study(found["find_id"], home=tmp_path)
    path = tmp_path / "spec.toml"
    path.write_text(path.read_text().replace("primary=5", "primary=20"))
    shopped = setup_cmds.run_find(path, home=tmp_path)
    second = setup_study.run_study(shopped["find_id"], home=tmp_path)
    assert shopped["find_id"] != found["find_id"]
    assert second["study_id"] != first["study_id"] and second["primary_horizon"] == 20
    studies = [r for r in spine_snapshot(tmp_path).records if r.kind == "setup_study"]
    assert [r.counts_for_deflation for r in studies] == [True, True]
    assert {r.family_id for r in studies} == {"setup:inspect matches"}
    assert sum(r["reader_trials"] for r in family_counts(spine_snapshot(tmp_path))) == 2
