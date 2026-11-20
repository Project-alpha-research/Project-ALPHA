"""Setup Lab recheck, and the nightly run on a tiny synthetic store, twice in one home."""

from __future__ import annotations

import json
import shutil
from collections.abc import Sequence
from datetime import date
from pathlib import Path
from typing import Any

import polars as pl
import pytest
from typer.testing import CliRunner

from alpha_cli.main import app
from alpha_cli.nightly_config import NightlyConfig
from alpha_cli.nightly_run import run_nightly
from alpha_cli.nightly_steps import Outcome
from alpha_cli.spine import setup_recheck, setup_study
from alpha_cli.spine.ledger import read_trials
from alpha_cli.spine.setup_exits import trades_frame
from alpha_data.store import ParquetStore
from tests.fixtures.cli_fixtures import seed_store

SETUP = (
    '[setup]\nname="Rechecked"\nidea="Inspect matches"\ntimeframe="1D"\nassets=["BTC/USD"]\n'
    'event="volume == 1"\n[reference]\nbase="low"\n[study]\nhorizons=[1,5]\nprimary=5\n'
    '[exit]\ntime_bars=2\nstop="5 %"\ntarget="10 %"\n'
)
RULE = 'assets = ["BTC/USD"]\n[rule]\nkind = "ma_cross"\nfast = 5\nslow = 20\n'
cli = CliRunner()


def _listing(root: Path) -> dict[str, tuple[int, int]]:
    return {
        str(p.relative_to(root)): (p.stat().st_size, p.stat().st_mtime_ns)
        for p in sorted(root.rglob("*"))
    }


def _home(path: Path) -> Path:
    seed_store(path, symbol="BTC/USD", n=1100)
    store = ParquetStore(path / "store")
    store.write_provenance("BTC/USD", source="alpaca", adapter_version="1", parser_version="1")
    frame = store.read_bars("BTC/USD")
    flags = [1.0 if i >= 100 and i % 40 == 0 else 0.0 for i in range(frame.height)]
    store.write_bars(
        "BTC/USD", frame.with_columns(pl.Series("volume", [1.0 if f else 1000.0 for f in flags]))
    )
    return path


def _json(args: Sequence[str]) -> tuple[int, dict[str, Any]]:
    done = cli.invoke(app, [*args, "--json"])
    return done.exit_code, json.loads(done.stdout)


@pytest.fixture
def home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = _home(tmp_path / "home")
    monkeypatch.setenv("ALPHA_DATA_DIR", str(path))
    return path


@pytest.fixture
def find(home: Path, tmp_path: Path) -> str:
    spec = tmp_path / "setup.toml"
    spec.write_text(SETUP)
    code, found = _json(["setup", "find", str(spec)])
    assert code == 0 and found["executed"] is True
    assert _json(["setup", "find", str(spec)])[1]["executed"] is False
    return str(found["find_id"])


@pytest.mark.parametrize("kind", ["study", "trade"])
def test_setup_recheck_matches_writes_nothing_and_reports_executed(
    home: Path, find: str, kind: str
) -> None:
    code, first = _json(["setup", kind, find, "--recheck"])
    assert code == 0 and first["recheck"]["match"] is None and first["recheck"]["computed"] is False
    code, ran = _json(["setup", kind, find])
    assert ran["executed"] is True and "repeat" not in ran["labels"]
    before, rows = _listing(home), len(read_trials(home))
    code, again = _json(["setup", kind, find, "--recheck"])
    assert code == 0 and again["recheck"]["match"] is True and again["recheck"]["computed"] is True
    assert again["recheck"]["differences"] == []
    assert _listing(home) == before and len(read_trials(home)) == rows
    served = _json(["setup", kind, find])[1]
    assert served["executed"] is False and "repeat" in served["labels"]


def test_setup_drift_is_named_and_exits_four(
    home: Path, find: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    _json(["setup", "study", find])
    real = setup_study.compute_study

    def drifted(*args: Any, **kwargs: Any) -> tuple[dict[str, Any], Any]:
        summary, outcomes = real(*args, **kwargs)
        summary["horizons"]["5"]["pooled"]["mean"] += 0.01
        return summary, outcomes

    monkeypatch.setattr(setup_study, "compute_study", drifted)
    before = _listing(home)
    code, found = _json(["setup", "study", find, "--recheck"])
    assert code == 4 and found["recheck"]["match"] is False
    assert found["recheck"]["differences"][0]["field"] == "summary.horizons.5.pooled.mean"
    assert _listing(home) == before


def test_one_different_trade_row_is_a_difference_with_the_same_count(
    home: Path, find: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The summary is unchanged; one value of the per-trade table differs."""
    assert _json(["setup", "trade", find])[0] == 0
    real = trades_frame

    def drifted(rows: Any) -> pl.DataFrame:
        frame: pl.DataFrame = real(rows)
        column = next(n for n, t in frame.schema.items() if t == pl.Float64)
        return frame.with_columns(pl.col(column) * 1.01)

    monkeypatch.setattr(setup_recheck, "trades_frame", drifted)
    before = _listing(home)
    code, found = _json(["setup", "trade", find, "--recheck"])
    assert code == 4 and found["recheck"]["match"] is False
    fields = [d["field"] for d in found["recheck"]["differences"]]
    assert fields and all(f.startswith("trades.parquet.columns.") for f in fields)
    assert found["recheck"]["code_changed"] is None
    assert _listing(home) == before


def test_nightly_twice_in_one_home_rechecks_computes_and_matches(
    home: Path, tmp_path: Path
) -> None:
    rule, setup = tmp_path / "rule.toml", tmp_path / "setup.toml"
    rule.write_text(RULE)
    setup.write_text(SETUP)
    config = NightlyConfig(
        assets=("BTC/USD",),
        rule_spec=rule,
        setup_spec=setup,
        quick=True,
        source=tmp_path / "n.toml",
    )
    seen: list[list[str]] = []

    def runner(argv: Sequence[str], timeout: float) -> Outcome:
        tail = list(argv)[3:]
        seen.append(tail)
        done = cli.invoke(app, tail)
        return Outcome(done.exit_code, done.stdout, "", 0.5, False)

    steps: dict[date, dict[str, dict[str, Any]]] = {}
    for day in (date(2026, 11, 19), date(2026, 11, 20)):
        record = run_nightly(config, home, runner, only=("N1", "N2"), today=day)
        steps[day] = {s["id"]: s for s in record["steps"]}
        for name in ("N1.test", "N2.find", "N2.study", "N2.trade"):
            assert steps[day][name]["state"] == "pass", record["defects"]
    first, second = steps[date(2026, 11, 19)], steps[date(2026, 11, 20)]
    assert first["N1.test"]["evidence"] == "computed" and "recheck" not in first["N1.test"]
    check = "N1.check.BTC/USD"
    assert second[check]["state"] == first[check]["state"] == "pass", second[check]["defect"]
    assert second["N1.test"]["evidence"] == "computed"
    assert second["N1.test"]["recheck"][0]["match"] is True
    assert second["N1.test"]["recheck"][0]["code_changed"] is False
    assert second["N2.study"]["evidence"] == second["N2.trade"]["evidence"] == "computed"
    assert second["N2.study"]["recheck"][0]["match"] is True
    plain = [t for t in seen if t[0] == "test" and "--recheck" not in t]
    assert len(plain) == 1  # the normal test ran on the first night only
    assert len([t for t in seen if t[:1] == ["test"]]) == 3
    assert len([r for r in read_trials(home) if r["kind"] == "rule_test"]) == 1


def test_rule_test_executed_field_survives_a_json_round_trip(home: Path, tmp_path: Path) -> None:
    spec = tmp_path / "rule.toml"
    spec.write_text(RULE)
    shutil.rmtree(home / "runs", ignore_errors=True)
    code, out = _json(["test", str(spec), "--quick"])
    assert code == 0 and out["results"][0]["executed"] is True
    code, out = _json(["test", str(spec), "--quick"])
    assert out["results"][0]["executed"] is False and "repeat" in out["results"][0]["labels"]
