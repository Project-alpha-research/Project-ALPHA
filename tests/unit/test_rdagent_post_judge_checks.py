"""The fixed checks describe a shown replay without contributing to the judge's family."""

import json
from dataclasses import replace
from pathlib import Path
from typing import Any
from unittest.mock import Mock, patch

import numpy as np
import polars as pl
import pytest

from alpha_cli import rdagent_factor_eval as ev
from alpha_cli import rdagent_journey as journey
from alpha_cli._rdagent_checks import FactorTarget, post_judge_checks
from alpha_cli.spine.ledger import read_trials
from alpha_cli.spine.trial_reader import spine_snapshot, trials_for_deflation
from alpha_cli.toolbox import declarations, runner
from alpha_cli.toolbox.inputs import Inputs
from alpha_cli.toolbox.registry import get
from alpha_validation import (
    FloatArray,
    block_bootstrap_ci,
    sharpe_ratio,
    stationary_bootstrap_indices,
    summarize_path_family,
)
from tests.unit.test_rdagent_factor_eval import evaluate, fixture
from tests.unit.test_rdagent_factor_eval import recorded_time as recorded_time
from tests.unit.test_rdagent_journey import make_run

SET = "rdagent-post-judge"
SHARPE = "resampling.sharpe_interval"
PATHS = "resampling.block_bootstrap_paths"
REFERENCE = Path(__file__).parents[1] / "fixtures/rdagent_post_judge_checks.json"
Row = dict[str, Any]


def direct(tool: str, returns: FloatArray, seed: int) -> dict[str, float]:
    if tool == SHARPE:
        ci = block_bootstrap_ci(
            returns,
            lambda x: sharpe_ratio(x, periods_per_year=365),
            confidence=0.95,
            n_resamples=2000,
            mean_block=5.0,
            seed=seed,
        )
        return {"point": ci.point, "lower": ci.lower, "upper": ci.upper}
    rows = stationary_bootstrap_indices(
        len(returns), mean_block=5.0, n_resamples=2000, rng=np.random.default_rng(seed)
    )
    s = summarize_path_family("stationary_bootstrap", returns[rows])
    return {
        "low": s.terminal_return_q05,
        "median": s.terminal_return_q50,
        "high": s.terminal_return_q95,
        "drop_q95": s.maximum_drawdown_q95,
    }


@pytest.mark.usefixtures("pre_table_costs")
def test_parity_attempts_and_cache(tmp_path: Path, recorded_time: None) -> None:
    run = tmp_path / "run"
    req = fixture(run)
    record = evaluate(run, req, tmp_path / "ledger")
    row = record["factors"][0]
    assert "checks" in record
    assert record["checks"]["set"] == SET
    (entry,) = record["checks"]["factors"]
    results = entry["results"]
    assert [r["tool"] for r in results] == [SHARPE, PATHS]
    code, clock = row["code_sha256"], row["lead_clock"]
    replay = run / "evaluations/iter-0/series" / f"{code}.replay.parquet"
    values = pl.read_parquet(replay).filter(pl.col("clock") == clock).sort("target_ts")
    returns = values["excess_return"].to_numpy()
    ref = json.loads(REFERENCE.read_bytes())

    source = FactorTarget.from_row(run, record, row)
    assert source.kinds == {"stored_equity"}
    with pytest.raises(ValueError, match="cannot supply"):
        source.prepare(run, ("run_trades",), {})
    source.prepare(run, ("stored_equity",), {})
    assert source.last_ts == values["exit_ts"][-1] and source.ppy == 365
    # Older records can carry another clock's top-level replay; the lead clock's is the verdict's.
    stale = FactorTarget.from_row(run, record, {**row, "replay": {"net": {}}})
    assert stale.scored_returns() == pytest.approx(returns, rel=0, abs=0)
    for result in results:
        tool = result["tool"]
        file = Path(result["file"])
        assert file.parent == Path("checks/diagnostics") / f"rdagent-iter0-{code[:16]}-{clock}"
        doc = json.loads((run / file).read_bytes())
        assert doc["reading"] == result["reading"]
        assert doc["labels"] == [
            "rdagent-factor",
            "excess-over-equal-weight-basket",
            "after-verdict",
            "declared",
        ]
        assert doc["values"] == pytest.approx(
            direct(tool, returns, doc["result"]["seed"]), rel=1e-9, abs=1e-12
        )
        if tool == SHARPE:
            assert doc["values"]["point"] == pytest.approx(
                row["replay"]["net"]["sharpe"], rel=1e-9, abs=1e-12
            )
        # The path tool's effective seed depends on the platform's Parquet bytes.
        # The numerical reference uses the same defaults and a portable effective seed.
        spec = get(tool)
        assert spec.compute is not None
        fixed = spec.compute(Inputs(source, seed=0), doc["params"], np.random.default_rng(0))
        assert fixed.values == pytest.approx(ref[tool], rel=1e-9, abs=1e-12)
    (declaration,) = declarations.read(run / "checks", source.run_id)
    assert declaration["set"] == SET and declaration["why"] == "fixed set run by rule"
    suffix = (
        " After the verdict, ALPHA ran its fixed checks (rdagent-post-judge) on factor."
        " They do not change the verdict. They use the idea's daily return above the average"
        " of all coins, after costs. This is not a profit. They are information, not a target. "
    )
    assert record["feedback_text"].endswith(suffix + " ".join(r["reading"] for r in results))
    attempts = read_trials(run / "checks")
    assert [a["outcome"] for a in attempts] == ["attempted", "ok"] * 2
    assert all(a["set"] == SET and a["seed"] == 0 and a["verdict"] is None for a in attempts)
    ev.evaluate(run, req, run / "copy.json", tmp_path / "fresh-ledger")
    assert (run / "copy.json").read_bytes() == (run / "result.json").read_bytes()
    assert read_trials(run / "checks") == attempts


def test_checks_leave_verdict_and_factor_ledger_identical(
    tmp_path: Path, recorded_time: None
) -> None:
    run = tmp_path / "run"
    req = fixture(run)
    with patch.object(ev, "post_judge_checks", return_value=({}, "")):
        control = evaluate(run, req, tmp_path / "control")
    checked = ev.evaluate(run, req, run / "checked.json", tmp_path / "checked")
    assert checked["checks"]["factors"]
    for key in (
        "decision",
        "factors",
        "legacy_result",
        "family_size",
        "total_trials",
        "replayed_trials",
    ):
        assert checked[key] == control[key]
    assert (tmp_path / "control").read_bytes() == (tmp_path / "checked").read_bytes()
    attempts = spine_snapshot(run / "checks")
    assert len(attempts.records) == 4 and not attempts.unknown
    assert trials_for_deflation(attempts, "rdagent-factors")["all_trials"] == 0


@pytest.mark.parametrize(
    ("stage", "status", "replay", "evidence", "eligible"),
    [
        ("screen", "SCREEN_FAIL", {}, True, False),
        ("replay", "SPREAD_FAIL", {"net": {}, "counted_only": True}, True, False),
        ("replay", "REPEAT", {"net": {}}, True, False),
        ("replay", "CANDIDATE", {}, True, False),
        ("replay", "CANDIDATE", {"net": {}}, False, False),
        ("replay", "REPLAY_FAIL", {"net": {}}, True, True),
        ("replay", "CANDIDATE", {"net": {}}, True, True),
    ],
)
def test_eligibility(
    tmp_path: Path, stage: str, status: str, replay: Row, evidence: bool, eligible: bool
) -> None:
    row = {
        "stage": stage,
        "status": status,
        "code_sha256": "a" * 64,
        "name": "factor",
        "lead_clock": "weekly",
        "clocks": {"weekly": {"replay": replay}},
        **({"evidence": {"series_manifest": "missing"}} if evidence else {}),
    }
    block, suffix = post_judge_checks(tmp_path, {"iteration": 0, "inputs": {}, "factors": [row]})
    assert len(block["factors"]) == int(eligible)
    assert bool(suffix) == eligible
    assert [r["outcome"] for r in read_trials(tmp_path / "checks")] == ["attempted", "error"] * (
        2 if eligible else 0
    )


@pytest.mark.parametrize(
    "fault", ["compute", "tamper", "manifest", "reserved", "self-check", "unexpected"]
)
def test_check_failure_isolated(tmp_path: Path, fault: str, recorded_time: None) -> None:
    run = tmp_path / "run"
    req = fixture(run)
    with patch.object(ev, "post_judge_checks", return_value=({}, "")):
        control = evaluate(run, req, tmp_path / "control")

    def inject(path: Path, record: Row) -> tuple[Row, str]:
        row = record["factors"][0]
        if fault == "unexpected":
            with patch.object(runner, "run", side_effect=OSError("lock unavailable")):
                return post_judge_checks(path, record)
        if fault == "compute":
            spec = get(SHARPE)
            specs = {
                SHARPE: replace(spec, compute=Mock(side_effect=ValueError("compute failed"))),
                PATHS: get(PATHS),
            }
            with patch.object(runner, "get", side_effect=specs.__getitem__):
                return post_judge_checks(path, record)
        manifest = run / row["evidence"]["series_manifest"]
        file = manifest.with_name(f"{row['code_sha256']}.replay.parquet")
        if fault == "tamper":
            file.write_bytes(file.read_bytes() + b"x")
        elif fault == "manifest":
            manifest.write_bytes(manifest.read_bytes() + b" ")
        else:
            expr = (
                pl.col("exit_ts") + pl.duration(days=1100)
                if fault == "reserved"
                else pl.col("excess_return") + 0.01
            )
            pl.read_parquet(file).with_columns(expr).write_parquet(file)
            contents = json.loads(manifest.read_bytes())
            for item in contents["factors"][0]["files"]:
                if item["name"] == file.name:
                    item["sha256"] = ev.sha(file.read_bytes())
            manifest.write_bytes(ev.canonical(contents))
            # Inject re-bound evidence into a copy, preserving the already issued verdict.
            record = json.loads(ev.canonical(record))
            record["inputs"]["series_sha256"] = record["factors"][0]["evidence"]["sha256"] = ev.sha(
                manifest.read_bytes()
            )
        return post_judge_checks(path, record)

    with patch.object(ev, "post_judge_checks", inject):
        failed = ev.evaluate(run, req, run / "failed.json", tmp_path / "failed")
    assert failed["factors"] == control["factors"] and failed["decision"] == control["decision"]
    if fault == "unexpected":
        assert failed["checks"] == {"set": SET, "note": "OSError: lock unavailable"}
        return
    results = failed["checks"]["factors"][0]["results"]
    code = {"compute": "TOOL_FAILED", "reserved": "RESERVED_PERIOD"}.get(
        fault, "FACTOR_SERIES_CHANGED"
    )
    errors = [r for r in results if "error_code" in r]
    assert [r["tool"] for r in errors] == ([SHARPE] if fault == "compute" else [SHARPE, PATHS])
    assert all(r["error_code"] == code for r in errors)
    for result in errors:
        assert (
            f"Check {result['tool']} could not run: {result['message']}" in failed["feedback_text"]
        )
    assert [r["error_code"] for r in read_trials(run / "checks") if r["outcome"] == "error"] == [
        code
    ] * len(errors)


def test_journey_keeps_older_bytes_and_appends_only_check_readings(tmp_path: Path) -> None:
    run, rows = make_run(tmp_path)
    row = rows[1]
    index = journey.build(run, None, None, False)
    file = index.parent / json.loads(index.read_bytes())["ideas"][1]["folder"] / "journey.json"
    baseline = file.read_bytes()
    assert baseline == json.loads(REFERENCE.read_bytes())["legacy_journey"].encode()
    record = run / "evaluations/iter-1/result.json"
    data = json.loads(record.read_bytes())
    output = "checks/diagnostics/target/sharpe.json"
    data["checks"] = {
        "set": SET,
        "factors": [
            {
                "name": "score",
                "code_sha256": row["code_sha256"],
                "results": [
                    {"tool": SHARPE, "reading": "Stored interval.", "file": output},
                    {"tool": PATHS, "error_code": "TOOL_FAILED", "message": "Bad input"},
                ],
            }
        ],
    }
    record.write_text(json.dumps(data))
    journey.build(run, None, None, False)
    story = json.loads(file.read_bytes())
    old = json.loads(baseline)
    limits = old["steps"][6]
    limits["text"] += (
        " After the verdict, ALPHA ran fixed checks. They do not change the verdict. They use"
        " the daily return above the average of all coins, after costs. This is not a profit."
        " Stored interval. Check resampling.block_bootstrap_paths could not run: Bad input."
    )
    limits["source"].append(output)
    assert story == old
    assert all(len(step["numbers"]) <= 3 for step in story["steps"])


def test_a_manual_run_of_the_set_is_declared_only_if_a_declaration_came_first(
    tmp_path: Path,
) -> None:
    from datetime import UTC, datetime

    home, target = tmp_path, "run-x"
    when = datetime(2026, 11, 17, 12, tzinfo=UTC)
    assert declarations.status(home, target, SHARPE, SET, when) == "exploratory"
    declarations.declare(home, target, set_name=SET, why="fixed set run by rule", now=lambda: when)
    assert declarations.status(home, target, SHARPE, SET, when) == "exploratory"  # equal time
    later = datetime(2026, 11, 17, 12, 0, 1, tzinfo=UTC)
    assert declarations.status(home, target, SHARPE, SET, later) == "declared"
    assert declarations.status(home, target, SHARPE, None, later) == "declared"  # tool is in set
    assert declarations.status(home, "other-run", SHARPE, SET, later) == "exploratory"
