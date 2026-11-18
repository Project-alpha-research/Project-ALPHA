"""Funding is a separate, ticker-aware input and a per-factor eligibility rule."""

from __future__ import annotations

import importlib.util
import json
import subprocess
from datetime import date, timedelta
from pathlib import Path
from types import ModuleType
from typing import Any
from unittest.mock import MagicMock, patch

import numpy as np
import pandas as pd
import polars as pl
import pytest

from alpha_cli import _rdagent_judge as judge
from alpha_cli import rdagent_factor_eval as ev
from alpha_cli import rdagent_factor_eval as evaluator
from tests.unit.test_context_daily_funding import write_funding

ROOT = Path(__file__).resolve().parents[2]
# The main commit before funding existed: the optional path must leave its outputs byte-identical.
# HEAD would compare this code with itself once merged. CI checks out full history.
BASELINE = "1119f02d14c2b06b3e9bbc8d23318bad293e652d"


def worker(name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, ROOT / "workers/rdagent" / f"{name}.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def raw_panel() -> pl.DataFrame:
    keys = [
        (date(2023, 1, d), s)
        for d in (1, 2)
        for s in (
            "OLDUSDT" if d == 1 else "NEWUSDT",
            "REUSEUSDT",
            "COCOSUSDT",
            "NONEUSDT",
            "1000XUSDT",
        )
    ]
    return pl.DataFrame(
        {
            "date": [d for d, _ in keys],
            "instrument": [s for _, s in keys],
            **{c: [1.0] * len(keys) for c in judge.PANEL_COLUMNS[2:]},
        }
    )


def test_join_uses_raw_ticker_and_blocks_reuse(tmp_path: Path) -> None:
    breaks = [
        {
            "instrument": "OLDUSDT",
            "continues_as": "NEWUSDT",
            "new_from": "2023-01-02",
            "reason": "renamed",
        },
        {"instrument": "REUSEUSDT", "new_from": "2023-01-02", "reason": "ticker_reused"},
    ]
    for index, symbol in enumerate(
        ("OLDUSDT", "NEWUSDT", "REUSEUSDT", "COCOSUSDT", "1000XUSDT"), 1
    ):
        write_funding(
            tmp_path, symbol, [(f"2023-01-0{d}T08:00:00.008", float(index), None) for d in (1, 2)]
        )
    frame, sources = judge._panel_funding(tmp_path, raw_panel(), breaks)
    assert frame.select("date", "instrument").rows() == [
        (date(2023, 1, 1), "OLDUSDT"),
        (date(2023, 1, 1), "REUSEUSDT"),
        (date(2023, 1, 2), "OLDUSDT"),
    ]
    assert frame["funding_last"].to_list() == [1.0, 3.0, 2.0]
    assert set(sources) == {"OLDUSDT", "NEWUSDT", "REUSEUSDT"}


def test_prepare_funding_in_every_partition(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    data = worker("alpha_factor_data")
    panel = tmp_path / "panel.parquet"
    raw_panel().write_parquet(panel)
    pl.DataFrame(
        {
            "date": [date(2023, 1, 1)],
            "instrument": ["OLDUSDT"],
            "funding_sum": [0.1],
            "funding_last": [0.1],
            "funding_count": [1],
        }
    ).write_parquet(tmp_path / "funding.parquet")
    captured: dict[str, pd.DataFrame] = {}

    def capture(frame: pd.DataFrame, path: Path, **kwargs: Any) -> None:
        captured[str(path.relative_to(tmp_path / "out"))] = frame.copy()
        path.write_bytes(b"captured")

    monkeypatch.setattr(pd.DataFrame, "to_hdf", capture)
    receipt = data.prepare(panel, tmp_path / "out")
    assert receipt["funding_sha256"] == judge.sha((tmp_path / "funding.parquet").read_bytes())
    for frame in captured.values():
        assert list(frame.columns[-3:]) == ["$funding_sum", "$funding_last", "$funding_count"]
        assert all(str(dtype) == "float64" for dtype in frame.dtypes)
    full = captured["full/daily_pv.h5"]
    assert full.loc[(pd.Timestamp("2023-01-01"), "OLDUSDT"), "$funding_sum"] == 0.1
    assert full.xs("NONEUSDT", level="instrument")["$funding_sum"].isna().all()
    assert "Futures funding" in (tmp_path / "out/full/README.md").read_text()


@pytest.mark.parametrize(
    "code, expected",
    [
        ("x = df['$funding_sum']", True),
        ("x = df[['$close', '$funding_last']]", True),
        ("# df['$funding_sum']\nx = df['$close']", False),
        ("note = '$funding_sum'\nx = df['$close']", False),
    ],
)
def test_code_read_detection(code: str, expected: bool) -> None:
    assert evaluator.reads_funding(code.encode()) is expected


def test_funded_coverage_still_requires_eighty_percent(tmp_path: Path) -> None:
    rng = np.random.default_rng(7)
    days = [date(2023, 1, 1) + timedelta(days=n) for n in range(30)]
    symbols = [f"S{i:03d}" for i in range(141)]
    folder = tmp_path / "panel"
    folder.mkdir()
    funding = pl.DataFrame(
        {
            "date": [d for d in days for _ in symbols[:85]],
            "instrument": symbols[:85] * len(days),
            "funding_count": [1] * (85 * len(days)),
        }
    )
    funding.write_parquet(folder / "funding.parquet")
    (folder / "panel-receipt.json").write_text(
        json.dumps({"funding": {"sha256": judge.sha((folder / "funding.parquet").read_bytes())}})
    )
    mask = evaluator.funding_eligibility(tmp_path, days, symbols, None)
    signal = np.where(mask, rng.normal(size=mask.shape), np.nan)
    outcome = rng.normal(size=mask.shape)
    full = judge.screen(signal, outcome, "a" * 64, eligible=mask, n_resamples=20)
    assert full["coverage"] == 1.0
    assert full["status"] == "OK"
    signal[:, 42:] = np.nan
    half = judge.screen(signal, outcome, "a" * 64, eligible=mask, n_resamples=20)
    assert half["status"] == "DEGENERATE"
    assert half["coverage"] < 0.5


def test_funding_family_is_named() -> None:
    families = worker("idea_families")
    for name in ("funding_sum", "carry_28d", "basis", "perp"):
        assert families.name_family(name) == "futures funding"
    # A funding construct is never filed under a closed price family by a second keyword.
    for name in ("funding_momentum_7d", "funding_volatility_28d", "funding_trend", "funding_range"):
        assert families.name_family(name) == "futures funding"


def test_legacy_prepare_bytes(tmp_path: Path) -> None:
    pytest.importorskip("tables", reason="requires the factor runtime's PyTables")
    source = subprocess.run(
        ["git", "show", f"{BASELINE}:workers/rdagent/alpha_factor_data.py"],
        cwd=ROOT,
        capture_output=True,
        check=True,
    ).stdout
    baseline: dict[str, Any] = {}
    exec(compile(source, "<baseline-factor-data>", "exec"), baseline)
    panel = tmp_path / "panel.parquet"
    raw_panel().write_parquet(panel)
    old = baseline["prepare"](panel, tmp_path / "old")
    new = worker("alpha_factor_data").prepare(panel, tmp_path / "new")
    # HDF5 embeds write timestamps, so two runs of the same code differ in a few bytes once a
    # second boundary passes: compare every frame exactly, and every other file by its bytes.
    assert old["panel_sha256"] == new["panel_sha256"]
    assert sorted(old["files"]) == sorted(new["files"])
    for name, digest in old["files"].items():
        if name.endswith(".h5"):
            before = pd.read_hdf(tmp_path / "old" / name, key="data")
            after = pd.read_hdf(tmp_path / "new" / name, key="data")
            assert isinstance(before, pd.DataFrame) and isinstance(after, pd.DataFrame)
            pd.testing.assert_frame_equal(before, after, check_exact=True)
        else:
            assert new["files"][name] == digest


def test_freeze_legacy_bytes_and_optional_receipt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import io

    panel = raw_panel()
    manifests = tmp_path / "crypto/manifests"
    manifests.mkdir(parents=True)
    records: dict[str, tuple[dict[str, Any], bytes]] = {}
    for symbol in panel["instrument"].unique():
        dataset = {
            "family": "market_bars",
            "venue": "binance",
            "market_type": "spot",
            "frequency": "1d",
            "timestamp_convention": "interval_start_utc",
            "instrument": symbol,
        }
        raw = panel.filter(pl.col("instrument") == symbol).rename(
            {"date": "open_time", "volume": "base_volume"}
        )
        buffer = io.BytesIO()
        raw.write_parquet(buffer)
        payload = buffer.getvalue()
        manifest = {
            "artifact_kind": "normalized",
            "dataset": dataset,
            "artifact_sha256": judge.sha(payload),
            "quality": {"state": "qualified", "failures": [], "warnings": []},
        }
        (manifests / f"{symbol}.json").write_text(json.dumps(manifest))
        records[symbol] = manifest, payload

    class Store:
        def read_verified_normalized(
            self, key: str, *, max_bytes: int
        ) -> tuple[dict[str, Any], bytes]:
            return records[key]

    monkeypatch.setattr(judge, "configured_crypto_bulk_store", lambda _: Store())
    source = subprocess.run(
        ["git", "show", f"{BASELINE}:apps/alpha-cli/src/alpha_cli/_rdagent_judge.py"],
        cwd=ROOT,
        capture_output=True,
        check=True,
    ).stdout
    baseline: dict[str, Any] = {"__name__": "alpha_cli.baseline_judge"}
    exec(compile(source, "<baseline-judge>", "exec"), baseline)
    baseline["configured_crypto_bulk_store"] = lambda _: Store()
    old = baseline["freeze"](tmp_path, tmp_path / "old")
    new = judge.freeze(tmp_path, tmp_path / "new")
    assert old == new
    for name in ("panel.parquet", "panel-receipt.json"):
        assert (tmp_path / "old" / name).read_bytes() == (tmp_path / "new" / name).read_bytes()
    write_funding(tmp_path, "OLDUSDT", [("2023-01-01T08:00:00.008", 0.1, None)])
    funded = judge.freeze(tmp_path, tmp_path / "funded", funding_dir=tmp_path)
    assert funded["panel_sha256"] == old["panel_sha256"]
    assert funded["funding"]["names"] == ["OLDUSDT"]
    assert funded["funding"]["coverage_by_year"] == {"2023": 0.1}
    assert {key: value for key, value in funded.items() if key != "funding"} == old


@pytest.mark.parametrize("funded", [False, True])
def test_factor_specific_mask_and_price_only_parity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, funded: bool
) -> None:
    code = b"x = df['$funding_sum']" if funded else b"# $funding_sum\nx = df['$close']"
    digest = judge.sha(code)
    (tmp_path / "code").mkdir()
    (tmp_path / "code" / f"{digest}.py").write_bytes(code)
    days, symbols = [date(2023, 1, 1)], [f"S{i}" for i in range(10)]
    values = pl.DataFrame({"date": days * 10, "instrument": symbols, "factor": list(range(10))})
    request = {
        "iteration": 0,
        "factors": [
            {
                "name": "factor",
                "status": "OK",
                "code_sha256": digest,
                "declared_direction": 1,
                "primary_clock": "weekly",
                "direction_reason": "test",
            }
        ],
    }
    inputs = {"panel_sha256": "a" * 64, "factor_values_path": "unused", "factors_sha256": "b" * 64}
    masks: list[np.ndarray | None] = []

    def capture(*args: Any, **kwargs: Any) -> dict[str, Any]:
        masks.append(kwargs.get("eligible"))
        return {"status": "DEGENERATE", "p": 1.0}

    monkeypatch.setattr(evaluator, "screen_at_clock", capture)

    def run() -> tuple[list[dict[str, Any]], dict[str, np.ndarray]]:
        rows, signals = evaluator._screen_factors(
            tmp_path, request, values, inputs, [], {}, [], days, symbols, np.ones((3, 10)), days, {}
        )
        for row in rows:
            row.pop("recorded_at")
        return rows, signals

    before = None if funded else run()
    (tmp_path / "panel").mkdir()
    funding = (
        values.head(6).select("date", "instrument").with_columns(pl.lit(1).alias("funding_count"))
    )
    funding.write_parquet(tmp_path / "panel/funding.parquet")
    (tmp_path / "panel/panel-receipt.json").write_text(
        json.dumps(
            {"funding": {"sha256": judge.sha((tmp_path / "panel/funding.parquet").read_bytes())}}
        )
    )
    rows, signals = run()
    if funded:
        assert rows[0]["eligibility"] == "perp-funding"
        assert rows[0]["mean_eligible_names"] == 6.0
        assert np.isnan(signals[digest][0, 6:]).all()
        assert all(mask is not None and mask.sum() == 6 for mask in masks)
    else:
        assert before is not None
        assert rows == before[0]
        np.testing.assert_array_equal(signals[digest], before[1][digest])
        assert all(mask is None for mask in masks)


def test_scenario_columns_follow_prepared_data(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from tests.unit._rdagent_support import judge_namespace

    data = worker("alpha_factor_data")
    setting = judge_namespace()["current_funding_setting"]
    monkeypatch.setenv("ALPHA_FACTOR_RUN_DIR", str(tmp_path))
    assert setting() == ""
    full = tmp_path / "factor_data/full"
    full.mkdir(parents=True)
    (full / "daily_pv.h5").write_bytes(b"fixture")
    store = MagicMock()
    monkeypatch.setattr(pd, "HDFStore", store)
    columns = store.return_value.__enter__.return_value.get_storer.return_value.read_index
    for names in (["$close"], data.FUNDING_COLUMNS[:-1]):
        columns.return_value = pd.Index(names)
        assert setting() == ""
    columns.return_value = pd.Index(data.FUNDING_COLUMNS)
    assert all(name in setting() for name in data.FUNDING_COLUMNS)


def test_launcher_passes_and_records_funding(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.syspath_prepend(str(ROOT / "workers/rdagent"))
    launch_module = worker("factor_loop_launch")
    argv = [
        "run",
        "--data-dir",
        str(tmp_path),
        "--funding-dir",
        str(tmp_path),
        "--run-dir",
        str(tmp_path),
        "--gateway-data-dir",
        str(tmp_path),
        "--trial-ledger",
        str(tmp_path / "ledger"),
        "--run-id",
        "funding-test",
    ]
    args = launch_module.parser().parse_args(argv)
    paths = {
        "ALPHA_RDAGENT_SOURCE": tmp_path,
        "ALPHA_FACTOR_PYTHON": tmp_path / "runtime/venv/bin/python",
    }
    launch = launch_module.Launch(args, paths)
    panel = tmp_path / "panel"
    panel.mkdir()
    block = {"sha256": "a" * 64, "names": ["BTCUSDT"]}
    (panel / "panel-receipt.json").write_text(
        json.dumps({"panel_sha256": "b" * 64, "instruments": {"BTCUSDT": {}}, "funding": block})
    )
    commands: list[list[str]] = []

    def check(step: str, command: list[str]) -> str:
        commands.append(command)
        return ""

    monkeypatch.setattr(launch, "check", check)
    launch.prepare()
    assert commands[0][-2:] == ["--funding-dir", str(tmp_path)]
    assert launch.receipt["funding_dir"] == str(tmp_path)
    assert launch.receipt["funding"] == block
    launch_module.write_launch_command(tmp_path, argv, {})
    recorded = json.loads((tmp_path / "launch-command.json").read_bytes())
    assert recorded["argv"] == argv


def test_complete_price_evaluation_ignores_funding_file(tmp_path: Path) -> None:
    panel = raw_panel()
    values = panel.select("date", "instrument").with_columns(pl.lit(1.0).alias("price"))
    code = b"note = '$funding_sum'\nx = df['$close']"
    digest = judge.sha(code)
    request = {
        "iteration": 0,
        "factors": [
            {
                "name": "price",
                "status": "OK",
                "code_sha256": digest,
                "declared_direction": 1,
                "primary_clock": "weekly",
                "direction_reason": "test",
            }
        ],
    }
    inputs = {
        "panel_sha256": "a" * 64,
        "factor_values_path": str(tmp_path / "values.parquet"),
        "factors_sha256": "b" * 64,
    }
    results: list[dict[str, Any]] = []
    for funded in (False, True):
        run = tmp_path / str(funded)
        (run / "panel").mkdir(parents=True)
        (run / "code").mkdir()
        (run / "code" / f"{digest}.py").write_bytes(code)
        (run / "run-identity.json").write_text(json.dumps({"run_id": "same-run"}))
        receipt: dict[str, Any] = {"instruments": dict.fromkeys(panel["instrument"].unique(), {})}
        if funded:
            funding = (
                values.head(1)
                .select("date", "instrument")
                .with_columns(pl.lit(1).alias("funding_count"))
            )
            funding.write_parquet(run / "panel/funding.parquet")
            receipt["funding"] = {"sha256": judge.sha((run / "panel/funding.parquet").read_bytes())}
        (run / "panel/panel-receipt.json").write_text(json.dumps(receipt))
        record = evaluator._evaluate_locked(
            run, request, panel, values, inputs, run / "ledger.jsonl"
        )
        for row in record["factors"]:
            row.pop("recorded_at")
        results.append(record)
    assert judge.canonical(results[0]) == judge.canonical(results[1])


@pytest.mark.parametrize(
    "selector",
    [
        "df['$funding_sum']",
        "df.get('$funding_sum')",
        "df.filter(items=['$funding_sum'])",
        "df.__getitem__('$funding_sum')",
    ],
)
def test_input_columns_only_read_selectors(tmp_path: Path, selector: str) -> None:
    code = ("# df['$funding_last']\nnote = '$funding_count'\nx = " + selector).encode()
    digest = judge.sha(code)
    (tmp_path / "code").mkdir()
    (tmp_path / "code" / f"{digest}.py").write_bytes(code)
    (tmp_path / "panel").mkdir()
    (tmp_path / "panel/funding.parquet").write_bytes(b"funding")
    row: dict[str, Any] = {}
    with patch.object(ev, "funding_eligibility", return_value=np.ones((1, 5), dtype=bool)):
        ev._factor_eligibility(
            tmp_path,
            {"code_sha256": digest, "status": "OK"},
            row,
            [date(2021, 1, 1)],
            list("ABCDE"),
            None,
        )
    assert row["input_columns"] == ["$funding_sum"]
    assert row["input_columns_method"] == "source-selectors"
    assert row["eligibility"] == "perp-funding"


def test_input_columns_detection_miss_is_disclosed(tmp_path: Path) -> None:
    code = b"column = '$' + 'close'\nx = df[column]"
    digest = judge.sha(code)
    (tmp_path / "code").mkdir()
    (tmp_path / "code" / f"{digest}.py").write_bytes(code)
    row: dict[str, Any] = {}
    ev._factor_eligibility(tmp_path, {"code_sha256": digest, "status": "OK"}, row, [], [], None)
    assert row["input_columns_method"].startswith("fallback:")
    assert row.get("input_columns", []) == []
