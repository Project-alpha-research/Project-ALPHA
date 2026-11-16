"""Family count contracts and the brief's independently pinned numerical examples."""

from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np
import pytest
from typer.testing import CliRunner

from alpha_cli import _gauntlet, results_cmds
from alpha_cli.spine.deflation import TrialFamily, deflate, family_count
from alpha_cli.spine.diagnose import trials
from alpha_cli.spine.errors import SpineError
from alpha_cli.spine.facts import build_facts
from alpha_cli.spine.trial_reader import LedgerSnapshot
from alpha_validation.dsr import deflated_sharpe


def sample() -> tuple[np.ndarray, list[float]]:
    z = np.random.default_rng(20261116).standard_normal(500)
    z = (z - z.mean()) / z.std(ddof=1)
    return 1.2 / math.sqrt(252) * 0.01 + 0.01 * z, [
        s / math.sqrt(252) for s in (1.2, 0.8, 0.3, -0.2, 0.5)
    ]


def ledger(home: Path, *, other_symbol: bool = True) -> Path:
    path = home / "ledger/trials.jsonl"
    path.parent.mkdir(parents=True)
    rows = []
    for i in range(1, 41 if other_symbol else 51):
        rows.append(
            dict(
                schema="AlphaTrialV1",
                trial_index=i,
                total_trials=i,
                recorded_at="2026-11-16T00:00:00+00:00",
                symbol="AAA" if other_symbol else "SPY",
                rule="ma_cross" if other_symbol and i != 39 else "breakout",
                verdict="E" if i == 40 and other_symbol else "D" if i in (37, 38) else "B",
                labels=["repeat"] if other_symbol and i in (37, 38) else [],
                oos_sharpe=i / 100,
                periods_per_year=252,
            )
        )
    path.write_text("".join(json.dumps(row) + "\n" for row in rows))
    return path


@pytest.mark.parametrize(
    "n,used,sr0,probability",
    [
        (1, 5, 0.039539596638979206, 0.7884548114505915),
        (40, 40, 0.0725906427268426, 0.5265926343748291),
        (201, 201, 0.09174299677486003, 0.35985720986016),
    ],
)
def test_worked_example(n: int, used: int, sr0: float, probability: float) -> None:
    returns, sharpes = sample()
    result = deflate(returns, sharpes, n)
    assert result["n_trials_used"] == used
    assert result["trial_sharpe_variance"] == pytest.approx(0.001099206349206349, abs=1e-12, rel=0)
    assert result["expected_max_sharpe"] == pytest.approx(sr0, abs=1e-12, rel=0)
    assert result["dsr"] == pytest.approx(probability, abs=1e-12, rel=0)
    assert result["reasons"] == {}


@pytest.mark.parametrize("n", [1, 4, 5])
def test_matches_public_deflated_sharpe(n: int) -> None:
    returns, sharpes = sample()
    assert (
        deflate(returns, sharpes, n)["dsr"] == deflated_sharpe(returns, trial_sharpes=sharpes).dsr
    )


@pytest.mark.parametrize("other_symbol", [True, False])
def test_ledger_fixture(tmp_path: Path, other_symbol: bool) -> None:
    ledger(tmp_path, other_symbol=other_symbol)
    returns, _ = sample()
    result = trials(
        tmp_path, "SPY", returns, 252, [{"sharpe": i / 10} for i in range(5)], "ma_cross"
    )
    family = result["family"]
    assert family["prior_trials"] == (36 if other_symbol else 0)
    assert family["unknown_rows"] == (1 if other_symbol else 0)
    assert family["variants_scored"] == 5
    assert family["n_trials"] == (43 if other_symbol else 6)
    assert family["available_sharpes"] == (6 if other_symbol else 56)
    assert family["n_trials_used"] == (43 if other_symbol else 56)
    assert family["reader_version"] == 1
    assert family["ledger_rows"] == (40 if other_symbol else 50)


def test_missing_ledger_and_ignored_source_config(tmp_path: Path) -> None:
    (tmp_path / "ledger").mkdir()
    (tmp_path / "ledger/sources.toml").write_text("invalid toml!")
    count = family_count(tmp_path, "ma_cross")
    assert (count.prior_trials, count.unknown_rows, count.ledger_rows) == (0, 0, 0)
    assert count.family_id == "spine:ma_cross"


def test_unavailable_sharpes() -> None:
    assert deflate([1, 2], [0.1], 40)["reasons"] == {
        "dsr": "fewer than two available trial Sharpes"
    }
    assert deflate([1, 1], [0.1, 0.2], 40)["dsr"] is None


def test_family_fact_and_older_run(tmp_path: Path) -> None:
    fact = next(f for f in build_facts(tmp_path) if f["metric"] == "family_trials")
    assert fact["value"] is None
    assert fact["reason"] == "recorded before family counts were used"
    (tmp_path / "diagnostics.json").write_text(
        json.dumps({"trials": {"family": {"n_trials_used": 43}}})
    )
    fact = next(f for f in build_facts(tmp_path) if f["metric"] == "family_trials")
    assert fact["value"] == 43
    assert fact["source"] == "diagnostics.json:trials.family.n_trials_used"
    assert fact["reason"] is None


def mock_run(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import alpha_cli.figures

    monkeypatch.setattr(results_cmds, "find_run_dir", lambda *_: tmp_path)
    monkeypatch.setattr(
        results_cmds, "_run", lambda *_: (tmp_path, {"spine": {"rule": {"kind": "ma_cross"}}})
    )
    monkeypatch.setattr(alpha_cli.figures, "available_figures", lambda *_: [])
    monkeypatch.setenv("ALPHA_DATA_DIR", str(tmp_path))


def test_unreadable_ledger(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = ledger(tmp_path)
    mock_run(tmp_path, monkeypatch)
    original = Path.read_bytes

    def denied(self: Path) -> bytes:
        if self == path:
            raise PermissionError("denied")
        return original(self)

    monkeypatch.setattr(Path, "read_bytes", denied)
    with pytest.raises(SpineError) as caught:
        family_count(tmp_path, "ma_cross")
    assert caught.value.payload["code"] == "LEDGER_UNREADABLE"
    result = CliRunner().invoke(results_cmds.results_app, ["show", "run", "--json"])
    assert result.exit_code == 1
    assert json.loads(result.stdout)["error"]["code"] == "LEDGER_UNREADABLE"


def test_live_family_matches_ledger(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from alpha_cli.ledger_cmds import ledger_app

    ledger(tmp_path)
    mock_run(tmp_path, monkeypatch)
    result = CliRunner().invoke(ledger_app, ["families", "--json"])
    assert result.exit_code == 0, result.stdout
    payload = json.loads(result.stdout)
    family = results_cmds._show(tmp_path, "run")["family"]
    counts = next(row for row in payload["families"] if row["family_id"] == "spine:ma_cross")
    assert family["now"] == {key: counts[key] for key in ("reader_trials", "rows", "outcomes")}
    assert family["trials_at_run"] is None
    assert family["reason"] == "recorded before family counts were used"


def test_gauntlet_count_and_explicit_basis() -> None:
    returns, sharpes = sample()
    alone = _gauntlet._dsr_summary(returns, 0.95)
    assert alone.trial_basis == "no ledger family: counted as one trial"
    # The gauntlet adds this run's own per-bar Sharpe to the family's prior Sharpes.
    own = float(np.mean(returns) / np.std(returns, ddof=1))
    family = TrialFamily("spine:ma_cross", family_count=40, count=40, comparable=5)
    counted = _gauntlet._dsr_summary(returns, 0.95, sharpes[:4], family)
    expected = deflate(returns, [*sharpes[:4], own], 40)["dsr"]
    assert counted.dsr == pytest.approx(expected, abs=1e-12, rel=0)
    assert counted.n_trials == 40
    assert counted.prior_sharpes == tuple(sharpes[:4])
    assert counted.family_id == "spine:ma_cross" and alone.family_id is None
    assert counted.trial_basis == "ledger family spine:ma_cross, 40 trials"
    assert not counted.passed and alone.passed


def test_rule_run_records_family_beside_verdict(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from alpha_cli.spine.run import run_idea
    from alpha_cli.spine.spec import load_spec
    from alpha_data.store import ParquetStore
    from tests.fixtures.cli_fixtures import seed_store

    ledger(tmp_path)
    seed_store(tmp_path, symbol="SPY", n=150)
    monkeypatch.setenv("ALPHA_DATA_DIR", str(tmp_path))
    ParquetStore(tmp_path / "store").write_provenance(
        "SPY", source="alpaca", adapter_version="1", parser_version="1"
    )
    idea = load_spec(None, rule="ma_cross", param=["fast=5", "slow=20"], asset=["SPY"])
    result = run_idea(idea, home=tmp_path, quick=True)["results"][0]
    assert result["error"] is None, result["error"]
    rdir = Path(result["run_dir"])
    manifest = json.loads((rdir / "manifest.json").read_text())
    diagnostics = json.loads((rdir / "diagnostics.json").read_text())
    assert manifest["spine"]["deflation"] == diagnostics["trials"]["family"]
    assert manifest["dsr"]["n_trials"] == manifest["verdict"]["n_trials"] == 43
    assert manifest["dsr"]["trial_basis"] == manifest["verdict"]["trial_basis"]
    assert manifest["dsr"]["trial_basis"] == "ledger family spine:ma_cross, 43 trials"
    assert manifest["dsr"]["dsr"] <= manifest["dsr"]["psr"]
    frozen = {p.name: p.read_bytes() for p in rdir.iterdir()}
    again = run_idea(idea, home=tmp_path, quick=True)["results"][0]
    assert again["run_id"] == result["run_id"]
    assert "repeat" in again["labels"]
    assert frozen == {p.name: p.read_bytes() for p in rdir.iterdir()}


def test_validate_family_inputs(tmp_path: Path) -> None:
    from alpha_cli.spine.deflation import validation_family

    assert validation_family(tmp_path, "ma_crossover", 252, "none") == {}
    ledger(tmp_path)
    inputs = validation_family(tmp_path, "ma_crossover", 252, "none")
    assert inputs["trial_family"] == TrialFamily("spine:ma_cross", 38, 38, 37, 0)
    assert len(inputs["trial_sharpes"]) == 36
    assert validation_family(tmp_path, "kronos", 252, "none") == {}


def test_explicit_bar_size(tmp_path: Path) -> None:
    from alpha_cli.spine.deflation import spine_snapshot

    path = ledger(tmp_path)
    rows = [json.loads(line) for line in path.read_text().splitlines()]
    rows[0]["bar_size"] = "1h"
    rows[1]["bar_size"] = ""
    path.write_text("".join(json.dumps(row) + "\n" for row in rows))
    records = spine_snapshot(tmp_path).records
    assert records[0].bar_size == "1h"
    assert records[1].bar_size == "1D"


def test_no_diagnostics_still_deflates_verdict(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from alpha_cli.spine.run import run_idea
    from alpha_cli.spine.spec import load_spec
    from alpha_data.store import ParquetStore
    from tests.fixtures.cli_fixtures import seed_store

    ledger(tmp_path)
    seed_store(tmp_path, symbol="SPY", n=150)
    monkeypatch.setenv("ALPHA_DATA_DIR", str(tmp_path))
    ParquetStore(tmp_path / "store").write_provenance(
        "SPY", source="alpaca", adapter_version="1", parser_version="1"
    )
    idea = load_spec(None, rule="ma_cross", param=["fast=5", "slow=20"], asset=["SPY"])
    result = run_idea(idea, home=tmp_path, quick=True, no_diagnose=True)["results"][0]
    assert result["error"] is None, result["error"]
    manifest = json.loads((Path(result["run_dir"]) / "manifest.json").read_text())
    assert manifest["spine"]["deflation"] is None
    assert manifest["dsr"]["n_trials"] == 38
    assert manifest["verdict"]["trial_basis"] == "ledger family spine:ma_cross, 38 trials"


def test_validate_passes_existing_family_to_verdict(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import typer

    from alpha_cli.validate_cmds import validate
    from alpha_data.store import ParquetStore
    from tests.fixtures.cli_fixtures import seed_store

    ledger(tmp_path)
    seed_store(tmp_path, symbol="SPY", n=150)
    monkeypatch.setenv("ALPHA_DATA_DIR", str(tmp_path))
    ParquetStore(tmp_path / "store").write_provenance(
        "SPY", source="alpaca", adapter_version="1", parser_version="1"
    )
    app = typer.Typer()
    app.command()(validate)
    result = CliRunner().invoke(
        app,
        [
            "SPY",
            "--strategy",
            "ma_crossover",
            "--param",
            "fast=5",
            "--param",
            "slow=20",
            "--train-size",
            "64",
            "--test-size",
            "30",
            "--tier1-paths",
            "20",
            "--tier2-paths",
            "4",
            "--tier3-paths",
            "4",
            "--n-resamples",
            "50",
            "--max-workers",
            "1",
        ],
    )
    assert result.exit_code == 0, (result.output, result.exception)
    path = next((tmp_path / "runs").glob("*/manifest.json"))
    manifest = json.loads(path.read_text())
    assert manifest["dsr"]["n_trials"] == 38
    assert manifest["verdict"]["trial_basis"] == "ledger family spine:ma_cross, 38 trials"


def test_insufficient_family_sharpes_cannot_pass() -> None:
    returns, _ = sample()
    # Five comparable trials claimed (no floor) but only this run's Sharpe available.
    family = TrialFamily("spine:ma_cross", family_count=40, count=40, comparable=5)
    summary = _gauntlet._dsr_summary(returns, 0.95, [], family)
    assert summary.n_trials == 40
    assert not summary.passed
    assert math.isnan(summary.dsr)
    assert summary.reason == "fewer than two available trial Sharpes"


def validate_args() -> list[str]:
    return [
        "SPY",
        "--strategy",
        "ma_crossover",
        "--param",
        "fast=5",
        "--param",
        "slow=20",
        "--train-size",
        "64",
        "--test-size",
        "30",
        "--tier1-paths",
        "20",
        "--tier2-paths",
        "4",
        "--tier3-paths",
        "4",
        "--n-resamples",
        "50",
        "--max-workers",
        "1",
    ]


def test_validate_rerun_keeps_the_family_recorded_at_first_publication(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A grown ledger must neither break a re-run nor silently change the stored verdict."""
    import typer

    from alpha_cli.validate_cmds import validate
    from alpha_data.store import ParquetStore
    from tests.fixtures.cli_fixtures import seed_store

    path = ledger(tmp_path)
    seed_store(tmp_path, symbol="SPY", n=150)
    monkeypatch.setenv("ALPHA_DATA_DIR", str(tmp_path))
    ParquetStore(tmp_path / "store").write_provenance(
        "SPY", source="alpaca", adapter_version="1", parser_version="1"
    )
    app = typer.Typer()
    app.command()(validate)
    first = CliRunner().invoke(app, validate_args())
    assert first.exit_code == 0, (first.output, first.exception)
    manifest_path = next((tmp_path / "runs").glob("*/manifest.json"))
    stored = manifest_path.read_bytes()
    assert json.loads(stored)["dsr"]["n_trials"] == 38
    assert json.loads(stored)["dsr"]["deflation_rule"] == "family-dedup-floor-1"
    rows = [json.loads(line) for line in path.read_text().splitlines()]
    for i in range(41, 61):
        rows.append({**rows[0], "trial_index": i, "total_trials": i, "oos_sharpe": -i / 50})
    path.write_text("".join(json.dumps(row) + "\n" for row in rows))
    again = CliRunner().invoke(app, validate_args())
    assert again.exit_code == 0, (again.output, again.exception)
    assert manifest_path.read_bytes() == stored


def test_family_sharpes_keep_only_the_run_frequency(tmp_path: Path) -> None:
    """Per-bar Sharpes of other bar sizes are on another scale: they count, but not in variance."""
    from alpha_cli.spine.deflation import count_snapshot, family_sharpes, spine_snapshot

    path = ledger(tmp_path)
    rows = [json.loads(line) for line in path.read_text().splitlines()]
    rows[0]["periods_per_year"] = 252 * 78
    rows[1]["periods_per_year"] = 365
    path.write_text("".join(json.dumps(row) + "\n" for row in rows))
    snapshot = spine_snapshot(tmp_path)
    assert count_snapshot(snapshot, "ma_cross").prior_trials == 36
    daily = family_sharpes(snapshot, "spine:ma_cross", 252)
    assert len(daily) == 35
    assert daily[0] == pytest.approx(0.02 / math.sqrt(365), abs=1e-15, rel=0)
    assert daily[1] == pytest.approx(0.03 / math.sqrt(252), abs=1e-15, rel=0)
    assert len(family_sharpes(snapshot, "spine:ma_cross", 365)) == 35
    assert len(family_sharpes(snapshot, "spine:ma_cross", 252 * 78)) == 1


def test_one_ledger_snapshot_per_rule_run(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The verdict and diagnostics must count the same point-in-time ledger."""
    from alpha_cli.spine import deflation, diagnose, run
    from alpha_cli.spine.run import run_idea
    from alpha_cli.spine.spec import load_spec
    from alpha_data.store import ParquetStore
    from tests.fixtures.cli_fixtures import seed_store

    ledger(tmp_path)
    seed_store(tmp_path, symbol="SPY", n=150)
    monkeypatch.setenv("ALPHA_DATA_DIR", str(tmp_path))
    ParquetStore(tmp_path / "store").write_provenance(
        "SPY", source="alpaca", adapter_version="1", parser_version="1"
    )
    reads: list[Path] = []
    original = deflation.spine_snapshot

    def counted(home: Path) -> LedgerSnapshot:
        reads.append(home)
        return original(home)

    monkeypatch.setattr(run, "spine_snapshot", counted)
    monkeypatch.setattr(diagnose, "spine_snapshot", counted)
    idea = load_spec(None, rule="ma_cross", param=["fast=5", "slow=20"], asset=["SPY"])
    result = run_idea(idea, home=tmp_path, quick=True)["results"][0]
    assert result["error"] is None, result["error"]
    assert len(reads) == 1


def test_one_trial_basis_reads_singular() -> None:
    returns, _ = sample()
    family = TrialFamily("spine:ma_cross", family_count=1, count=1, comparable=1)
    summary = _gauntlet._dsr_summary(returns, 0.95, [], family)
    assert summary.trial_basis.startswith("ledger family spine:ma_cross, 1 trial,")
    assert summary.dsr == pytest.approx(summary.psr, abs=1e-15)


def keyed_ledger(home: Path, keys: list[tuple[str, str, str]]) -> Path:
    """Valid rule-test rows of ``ma_cross`` with a spec hash, symbol and window start each."""
    path = home / "ledger/trials.jsonl"
    path.parent.mkdir(parents=True)
    rows = [
        dict(
            schema="AlphaTrialV1",
            trial_index=i,
            total_trials=i,
            recorded_at="2026-11-16T00:00:00+00:00",
            symbol=symbol,
            rule="ma_cross",
            verdict="B",
            labels=[],
            spec_sha256=spec,
            first_ts=start,
            last_ts="2026-11-13T00:00:00+00:00",
            oos_sharpe=i / 10,
            periods_per_year=252,
        )
        for i, (spec, symbol, start) in enumerate(keys, 1)
    ]
    path.write_text("".join(json.dumps(row) + "\n" for row in rows))
    return path


def test_same_test_repeats_count_once_keeping_the_earliest(tmp_path: Path) -> None:
    from alpha_cli.spine.deflation import (
        count_snapshot,
        family_sharpes,
        spine_snapshot,
        spine_test_key,
    )

    same = ("a" * 64, "SPY", "2016-01-04T00:00:00+00:00")
    keyed_ledger(tmp_path, [same, ("b" * 64, "SPY", same[2]), same, same])
    snapshot = spine_snapshot(tmp_path)
    count = count_snapshot(snapshot, "ma_cross")
    assert (count.prior_trials, count.repeats, count.this_run) == (2, 2, 1)
    sharpes = family_sharpes(snapshot, "spine:ma_cross", 252)
    assert sharpes == pytest.approx([0.1 / math.sqrt(252), 0.2 / math.sqrt(252)], abs=1e-15)
    # This run repeating the earlier "b" test is not counted again, and its own Sharpe stands in.
    current = spine_test_key("b" * 64, "SPY", same[2], "2026-11-13T00:00:00+00:00", 252)
    count = count_snapshot(snapshot, "ma_cross", current)
    assert (count.prior_trials, count.repeats, count.this_run) == (2, 3, 0)
    assert family_sharpes(snapshot, "spine:ma_cross", 252, current) == pytest.approx(
        [0.1 / math.sqrt(252)], abs=1e-15
    )


def test_trial_basis_names_repeats_floor_and_wider_count() -> None:

    returns, sharpes = sample()
    family = TrialFamily("spine:ma_cross", family_count=9, count=13, comparable=3, repeats=3)
    summary = _gauntlet._dsr_summary(returns, 0.95, sharpes[:2], family)
    assert summary.trial_basis == (
        "ledger family spine:ma_cross, 13 trials (the wider count of same-asset tests of any "
        "rule; the family alone has 9), 3 repeats of earlier tests not counted, "
        "spread floored: fewer than 5 comparable trials"
    )
    assert summary.spread_floored and summary.repeats == 3 and summary.family_count == 9


def sampling_variance(returns: np.ndarray) -> float:
    from scipy import stats

    sr = float(np.mean(returns) / np.std(returns, ddof=1))
    skew = float(stats.skew(returns, bias=True))
    kurt = float(stats.kurtosis(returns, fisher=False, bias=True))
    return (1.0 - skew * sr + (kurt - 1.0) / 4.0 * sr * sr) / (returns.size - 1)


def test_spread_floored_below_five_comparable_trials() -> None:

    returns, sharpes = sample()
    own = float(np.mean(returns) / np.std(returns, ddof=1))
    floor = sampling_variance(returns)
    assert floor > float(np.var([*sharpes[:2], own], ddof=1))
    tiny = TrialFamily("spine:ma_cross", family_count=3, count=3, comparable=3)
    summary = _gauntlet._dsr_summary(returns, 0.95, sharpes[:2], tiny)
    expected = deflate(returns, [*sharpes[:2], own], 3, variance_floor=floor)
    assert summary.dsr == pytest.approx(expected["dsr"], abs=1e-12, rel=0)
    assert expected["trial_sharpe_variance"] == pytest.approx(floor, abs=1e-15, rel=0)
    assert summary.spread_floored
    wide = TrialFamily("spine:ma_cross", family_count=6, count=6, comparable=6)
    summary = _gauntlet._dsr_summary(returns, 0.95, sharpes, wide)
    assert summary.dsr == pytest.approx(
        deflate(returns, [*sharpes, own], 6)["dsr"], abs=1e-12, rel=0
    )
    assert not summary.spread_floored
    assert "floored" not in summary.trial_basis


def test_floored_spread_needs_only_this_runs_sharpe() -> None:

    returns, _ = sample()
    family = TrialFamily("spine:ma_cross", family_count=40, count=40, comparable=1)
    summary = _gauntlet._dsr_summary(returns, 0.95, [], family)
    assert math.isfinite(summary.dsr) and summary.dsr < summary.psr
    assert summary.reason is None


def test_validate_reports_an_unreadable_ledger_cleanly(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import typer

    from alpha_cli.validate_cmds import validate
    from alpha_data.store import ParquetStore
    from tests.fixtures.cli_fixtures import seed_store

    path = ledger(tmp_path)
    seed_store(tmp_path, symbol="SPY", n=150)
    monkeypatch.setenv("ALPHA_DATA_DIR", str(tmp_path))
    ParquetStore(tmp_path / "store").write_provenance(
        "SPY", source="alpaca", adapter_version="1", parser_version="1"
    )
    original = Path.read_bytes

    def denied(self: Path) -> bytes:
        if self == path:
            raise PermissionError("denied")
        return original(self)

    monkeypatch.setattr(Path, "read_bytes", denied)
    app = typer.Typer()
    app.command()(validate)
    result = CliRunner().invoke(app, validate_args())
    assert result.exit_code == 1
    assert isinstance(result.exception, SystemExit)
    assert "Cannot read the trial ledger" in result.output
    assert "Fix the file's permissions" in result.output
