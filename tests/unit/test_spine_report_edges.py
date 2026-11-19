"""Atomic publication of diagnostics, report paths and annualisation metadata."""

from __future__ import annotations

import json
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any, NoReturn

import pytest

from alpha_cli import _gauntlet, _runner
from alpha_cli._identity import RunIdentity
from alpha_cli.spine import run
from alpha_cli.spine.diagnose import _publish
from alpha_cli.spine.facts import build_facts
from alpha_cli.spine.spec import IdeaSpec, Rule
from alpha_cli.spine.trial_reader import LedgerSnapshot
from alpha_core import Bar, CorporateAction
from tests.unit.test_spine_stores import START

Publication = tuple[Path, IdeaSpec, run.Prepared, dict[str, Any], Path]


@pytest.fixture
def publication(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Publication:
    identity = RunIdentity("a" * 16, "b" * 64, None, "c" * 64, None)
    bars = [
        Bar(
            symbol="SPY",
            ts=START + timedelta(days=i),
            open=100,
            high=101,
            low=99,
            close=100,
            volume=10,
        )
        for i in range(100)
    ]
    idea = IdeaSpec(assets=("SPY",), rule=Rule(kind="ma_cross", fast=2, slow=5))
    spec = run.assemble_run_spec(idea, "SPY", 252, len(bars))
    prepared = run.Prepared(bars, [], spec, identity)
    out = SimpleNamespace(
        oos=SimpleNamespace(oos_timestamps=[b.ts for b in bars[10:]]),
        result=SimpleNamespace(resized_entries=0),
        report=None,
    )
    monkeypatch.setattr(_gauntlet, "run_gauntlet", lambda *a, **kw: out)
    monkeypatch.setattr(run, "report_to_manifest", lambda report: {})
    final = tmp_path / "runs" / identity.run_id
    result: dict[str, Any] = {
        "run_dir": str(final),
        "source": "test",
        "store": "home",
        "labels": ["data-health-unchecked"],
        "data_health": {"verdict": "unchecked", "sentence": "Data health: unchecked."},
        "variants_evaluated": 0,
        "periods_per_year_basis": "elapsed years; daily snap",
    }

    def diagnose(
        idea: IdeaSpec,
        bars: list[Bar],
        dividends: list[CorporateAction],
        spec: _runner.RunSpec,
        out: SimpleNamespace,
        identity: RunIdentity,
        home: Path,
        result: dict[str, Any],
        *,
        snapshot: LedgerSnapshot | None = None,
    ) -> SimpleNamespace:
        _publish(
            Path(result["run_dir"]),
            {
                "trials": {"total_trials": 1},
                "audit": [{"check": "artifacts-intact"}],
            },
            identity,
        )
        return out

    monkeypatch.setattr(run, "write_diagnostics", diagnose)
    return tmp_path, idea, prepared, result, final


def test_crash_before_manifest_does_not_publish_diagnostics(
    publication: Publication, monkeypatch: pytest.MonkeyPatch
) -> None:
    home, idea, prepared, result, final = publication

    def crash(*args: object, **kwargs: object) -> NoReturn:
        assert not (final / "diagnostics.json").exists()
        raise RuntimeError("simulated manifest failure")

    monkeypatch.setattr(run, "write_validation_run", crash)
    with pytest.raises(RuntimeError, match="simulated manifest failure"):
        run._execute(idea, prepared, home, _gauntlet.GauntletParams(), "test-id", result)
    assert not final.exists()
    assert result["run_dir"] == str(final)


def test_manifest_records_both_periods_and_annualisation_basis(
    publication: Publication, monkeypatch: pytest.MonkeyPatch
) -> None:
    home, idea, prepared, result, final = publication

    def write(
        home: Path,
        bars: list[Bar],
        spec: _runner.RunSpec,
        out: SimpleNamespace,
        identity: RunIdentity,
        *,
        extra_manifest: dict[str, Any],
    ) -> tuple[Path, dict[str, Any]]:
        directory = home / "runs" / identity.run_id
        manifest = {"run_id": identity.run_id, **extra_manifest}
        (directory / "manifest.json").write_text(json.dumps(manifest))
        return directory, manifest

    monkeypatch.setattr(run, "write_validation_run", write)
    run._execute(idea, prepared, home, _gauntlet.GauntletParams(), "test-id", result)
    manifest = json.loads((final / "manifest.json").read_text())
    assert (final / "diagnostics.json").is_file()
    spine = manifest["spine"]
    assert spine["data_period"] == {
        "first_ts": prepared.bars[0].ts.isoformat(),
        "last_ts": prepared.bars[-1].ts.isoformat(),
    }
    assert spine["traded_period"] == {
        "first_ts": prepared.bars[10].ts.isoformat(),
        "last_ts": prepared.bars[-1].ts.isoformat(),
    }
    assert spine["annualisation"] == {
        "periods_per_year": 252,
        "basis": result["periods_per_year_basis"],
    }
    facts = {fact["metric"]: fact for fact in build_facts(final)}
    for name in ("data_period", "traded_period"):
        assert facts[name]["value"] == spine[name]
        assert facts[name]["source"] == f"manifest.json:spine.{name}"


def test_crash_after_staged_manifest_leaves_final_run_absent(
    publication: Publication, monkeypatch: pytest.MonkeyPatch
) -> None:
    home, idea, prepared, result, final = publication

    def write(
        home: Path,
        bars: list[Bar],
        spec: _runner.RunSpec,
        out: SimpleNamespace,
        identity: RunIdentity,
        *,
        extra_manifest: dict[str, Any],
    ) -> tuple[Path, dict[str, Any]]:
        directory = home / "runs" / identity.run_id
        (directory / "manifest.json").write_text(json.dumps(extra_manifest))
        return directory, extra_manifest

    def crash(staged: Path, destination: Path) -> NoReturn:
        assert (staged / "manifest.json").is_file()
        assert (staged / "diagnostics.json").is_file()
        assert destination == final and not final.exists()
        raise OSError("simulated rename failure")

    monkeypatch.setattr(run, "write_validation_run", write)
    monkeypatch.setattr(Path, "rename", crash)
    with pytest.raises(OSError, match="simulated rename failure"):
        run._execute(idea, prepared, home, _gauntlet.GauntletParams(), "test-id", result)
    assert not final.exists()
    assert result["run_dir"] == str(final)


def test_no_printed_or_stored_path_names_the_staging_folder(
    publication: Publication, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    home, idea, prepared, result, final = publication

    def write(
        home: Path,
        bars: list[Bar],
        spec: _runner.RunSpec,
        out: SimpleNamespace,
        identity: RunIdentity,
        *,
        extra_manifest: dict[str, Any],
    ) -> tuple[Path, dict[str, Any]]:
        directory = home / "runs" / identity.run_id
        print(f"HTML report saved to: {directory}/.tearsheet.html.x.tmp")
        manifest = {"run_id": identity.run_id, **extra_manifest}
        (directory / "manifest.json").write_text(json.dumps(manifest))
        return directory, manifest

    monkeypatch.setattr(run, "write_validation_run", write)
    run._execute(idea, prepared, home, _gauntlet.GauntletParams(), "test-id", result)
    printed = capsys.readouterr().out
    assert f"HTML report saved to: {final}/tearsheet.html" in printed
    stored = json.dumps(result) + (final / "manifest.json").read_text()
    assert ".pending-" not in printed + stored
