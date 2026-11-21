"""`alpha results correlate`: stored runs only, small samples, constant series, labels."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import polars as pl
import pytest
from typer.testing import CliRunner

from alpha_cli.main import app

RUNNER = CliRunner()
A, B, C = "a1" * 8, "b2" * 8, "c3" * 8
START = datetime(2020, 1, 1, tzinfo=UTC)


def _wave(n: int, shift: int = 0) -> list[float]:
    return [(0.02, -0.01, 0.005)[(i + shift) % 3] for i in range(n)]


def stored_run(
    home: Path,
    run_id: str,
    returns: list[float],
    *,
    start: datetime = START,
    held: list[float] | None = None,
    exposure: bool = True,
) -> None:
    """A stored rule-test run with the two files the command reads; nothing else."""
    rdir = home / "runs" / run_id
    rdir.mkdir(parents=True)
    stamps = [start + timedelta(days=i) for i in range(len(returns) + 1)]
    equity = [1.0]
    for r in returns:
        equity.append(equity[-1] * (1.0 + r))
    last = stamps[-1].isoformat()
    manifest = {
        "run_id": run_id,
        "metadata": {"symbol": "SPY", "last_ts": last},
        "spine": {"labels": ["quick"], "store": "home", "data_period": {"last_ts": last}},
    }
    (rdir / "manifest.json").write_text(json.dumps(manifest))
    (rdir / "spec.json").write_text("{}")
    pl.DataFrame({"ts": stamps, "equity": equity}).write_parquet(rdir / "equity_curve.parquet")
    if exposure:
        net = held if held is not None else [1.0] * len(returns)
        pl.DataFrame(
            {
                "start_ts": stamps[:-1],
                "end_ts": stamps[1:],
                "net_exposure": net,
                "exposure_available": [True] * len(returns),
            }
        ).write_parquet(rdir / "exposure_turnover.parquet")


def _cli(home: Path, *args: str) -> tuple[int, str]:
    result = RUNNER.invoke(app, ["results", "correlate", *args], env={"ALPHA_DATA_DIR": str(home)})
    return result.exit_code, result.output


def near(value: float) -> object:
    return pytest.approx(value, rel=1e-9, abs=1e-12)


def test_two_identical_stored_runs(tmp_path: Path) -> None:
    stored_run(tmp_path, A, _wave(90))
    stored_run(tmp_path, B, _wave(90), held=[1.0, 0.0] * 45)
    code, out = _cli(tmp_path, A, B, "--json")
    assert code == 0, out
    facts = json.loads(out)
    pair = facts["pairs"][0]
    assert pair["runs"] == [A, B]
    assert pair["common_days"] == 90
    assert pair["correlation"] == near(1.0)
    assert pair["both_in_market_days"] == 45 and pair["overlap_share"] == near(0.5)
    assert facts["basis"] == "stored walk-forward equity and exposure of each run"
    assert [r["run_id"] for r in facts["runs"]] == [A, B]
    assert facts["runs"][0]["labels"] == ["quick"]
    code, text = _cli(tmp_path, A, B)
    assert code == 0
    assert (
        f"Runs {A} and {B}: daily returns moved closely together (correlation 1.00) over "
        "90 common days; both were in the market on 50% of them."
    ) in text
    assert text.rstrip().endswith("Readings of stored runs only. Not advice.")


def test_three_runs_give_three_pairs_and_prefixes_resolve(tmp_path: Path) -> None:
    stored_run(tmp_path, A, _wave(90))
    stored_run(tmp_path, B, _wave(90, shift=1))
    stored_run(tmp_path, C, _wave(90, shift=2))
    code, out = _cli(tmp_path, A[:8], B[:8], C[:8], "--json")
    assert code == 0, out
    pairs = json.loads(out)["pairs"]
    assert [p["runs"] for p in pairs] == [[A, B], [A, C], [B, C]]
    # A three-day pattern against itself one day later: r = -0.5 in the limit; 90 days, exact.
    assert pairs[0]["correlation"] == near(-0.5)


def test_too_few_common_days_prints_no_correlation(tmp_path: Path) -> None:
    stored_run(tmp_path, A, _wave(90))
    stored_run(tmp_path, B, _wave(90), start=START + timedelta(days=50))
    code, out = _cli(tmp_path, A, B, "--json")
    assert code == 0, out
    pair = json.loads(out)["pairs"][0]
    assert pair["common_days"] == 40 and pair["correlation"] is None
    assert pair["correlation_reason"] == "too few common days to read"
    code, text = _cli(tmp_path, A, B)
    assert "too few common days to read" in text and "correlation " not in text


def test_a_constant_stored_series_is_not_defined(tmp_path: Path) -> None:
    stored_run(tmp_path, A, _wave(90))
    stored_run(tmp_path, B, [0.0] * 90, held=[0.0] * 90)
    code, out = _cli(tmp_path, A, B, "--json")
    assert code == 0, out
    pair = json.loads(out)["pairs"][0]
    assert pair["correlation"] is None
    assert pair["correlation_reason"].startswith("not defined")
    assert pair["both_in_market_days"] == 0


def test_a_run_without_stored_exposure_still_gets_its_correlation(tmp_path: Path) -> None:
    stored_run(tmp_path, A, _wave(90))
    stored_run(tmp_path, B, _wave(90), exposure=False)
    code, out = _cli(tmp_path, A, B, "--json")
    assert code == 0, out
    pair = json.loads(out)["pairs"][0]
    assert pair["correlation"] == near(1.0)
    assert pair["overlap_share"] is None and pair["overlap_reason"] == f"run {B} stored no exposure"


def test_a_run_that_saw_the_held_back_period_keeps_its_label(tmp_path: Path) -> None:
    stored_run(tmp_path, A, _wave(90), start=datetime(2023, 12, 1, tzinfo=UTC))
    stored_run(tmp_path, B, _wave(90), start=datetime(2023, 12, 1, tzinfo=UTC))
    code, out = _cli(tmp_path, A, B, "--json")
    assert code == 0, out
    facts = json.loads(out)
    assert all("reserved-period-seen" in r["labels"] for r in facts["runs"])
    code, text = _cli(tmp_path, A, B)
    assert f"Run {A}: This run used data from 2024-01-01 on" in text


@pytest.mark.parametrize(
    "args,code",
    [
        ([A], "INVALID_RUN_COUNT"),
        ([A, A], "DUPLICATE_RUN"),
        ([A, "ffffffffffffffff"], "UNKNOWN_RUN"),
    ],
)
def test_structured_errors(tmp_path: Path, args: list[str], code: str) -> None:
    stored_run(tmp_path, A, _wave(90))
    status, out = _cli(tmp_path, *args, "--json")
    assert status == 1
    error = json.loads(out)["error"]
    assert error["code"] == code and "alpha results" in error["next"]


def test_a_run_not_made_by_alpha_test_is_refused(tmp_path: Path) -> None:
    stored_run(tmp_path, A, _wave(90))
    stored_run(tmp_path, B, _wave(90))
    (tmp_path / "runs" / B / "spec.json").unlink()
    status, out = _cli(tmp_path, A, B, "--json")
    assert status == 1 and json.loads(out)["error"]["code"] == "NOT_A_RULE_TEST"


def test_a_damaged_equity_file_fails_loud(tmp_path: Path) -> None:
    stored_run(tmp_path, A, _wave(90))
    stored_run(tmp_path, B, _wave(90))
    stamps = [START + timedelta(days=i) for i in range(3)]
    pl.DataFrame({"ts": stamps, "equity": [1.0, float("nan"), 1.0]}).write_parquet(
        tmp_path / "runs" / B / "equity_curve.parquet"
    )
    status, out = _cli(tmp_path, A, B, "--json")
    assert status == 1
    assert json.loads(out)["error"]["code"] == "INVALID_ARTIFACT"


def test_the_command_reads_no_bars_and_writes_nothing(tmp_path: Path) -> None:
    stored_run(tmp_path, A, _wave(90))
    stored_run(tmp_path, B, _wave(90))
    before = sorted(p.relative_to(tmp_path).as_posix() for p in tmp_path.rglob("*"))
    code, _ = _cli(tmp_path, A, B)
    assert code == 0  # there is no bar store in this home: the command cannot have read one
    assert sorted(p.relative_to(tmp_path).as_posix() for p in tmp_path.rglob("*")) == before
