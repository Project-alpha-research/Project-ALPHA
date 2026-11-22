"""The hypothesis scan and archive replays hold back the reserved period."""

from __future__ import annotations

import hashlib
import io
import json
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import numpy as np
import polars as pl
import pytest
from typer.testing import CliRunner

from alpha_cli import _archive_bars, _hypothesis_scan, _runner, crypto_data_cmds
from alpha_cli.main import app
from alpha_core import Bar
from alpha_core.corporate import ActionType, CorporateAction
from alpha_core.reserve import RESERVED_DAY, RESERVED_START
from alpha_data.crypto.contracts import CryptoQualityReportV1
from alpha_data.crypto.quality import QUALITY_METHOD_VERSION
from alpha_data.crypto.storage import CryptoBulkStore
from alpha_data.snapshot import create_snapshot
from alpha_data.store import ParquetStore
from tests.fixtures.cli_fixtures import seed_store
from tests.fixtures.hypothesis_scan_fixtures import crypto_manifest, crypto_store

HELD_BACK = "reserved-period-held-back"
NAMES = ["AAA", "BBB", "CCC", "DDD", "EEE"]
# 2020-01-01 plus 1,600 daily bars ends 2024-05-19; the first 1,461 bars are dated before 2024.
LONG, SHORT, PRE = 1600, 1461, 1000
HELD = LONG - SHORT
SCAN = [
    "scan",
    "hypotheses",
    "--symbols",
    ",".join(NAMES),
    "--snapshot",
    "frozen",
    "--signals",
    "rev_1m,mom_6_1",
    "--horizons",
    "1,5",
    "--min-names",
    "5",
    "--quantiles",
    "5",
    "--json",
]
# Pinned before the reserved period was held back in the scan: a store with no bar from the
# reserved day on keeps its result and its frozen inputs (the code hashes are left out).
PINNED_PRE_RESULT = "dc9436f022aea1c10d0209d806834da05e5f99555405054c17cbfbd47f1c80b1"
# The inputs pin moved in M97 only because the frozen spec holds `data_hash` (rows before the
# boundary) in place of the whole-snapshot `snapshot_hash`; the result pin is unchanged.
PINNED_PRE_INPUTS = "a53eb5c8f97a1b438998ed38407424530decb9f3f4ded0b3ab4c4b062bcd79ac"
PINNED_PRE_ARCHIVE_RUN = "8a7424386db8ec4a"


def _equity_home(root: Path, n: int, *, poisoned: bool) -> Path:
    store = ParquetStore(root / "store")
    for index, symbol in enumerate(NAMES):
        seed_store(root, symbol=symbol, n=n, seed=index)
        store.write_provenance(symbol, source="alpaca", adapter_version="1", parser_version="1")
        if not poisoned:
            continue
        late = pl.col("ts").dt.date() >= RESERVED_DAY
        store.write_bars(
            symbol,
            store.read_bars(symbol).with_columns(
                [
                    pl.when(late).then(pl.col(c) * 1000.0).otherwise(pl.col(c)).alias(c)
                    for c in ("open", "high", "low", "close")
                ]
            ),
        )
        store.write_actions(
            symbol,
            [
                CorporateAction(
                    symbol=symbol,
                    action_type=ActionType.SPLIT,
                    ex_date=date(2024, 2, 15),
                    ratio=4.0,
                ),
                CorporateAction(
                    symbol=symbol,
                    action_type=ActionType.DIVIDEND,
                    ex_date=date(2024, 3, 1),
                    pay_date=date(2024, 3, 5),
                    amount=1.0,
                ),
            ],
        )
    create_snapshot(
        store,
        root / "snapshots",
        "frozen",
        NAMES,
        source="alpaca",
        adapter_version="1",
        parser_version="1",
        created_at=datetime(2025, 1, 1, tzinfo=UTC),
    )
    return root


def _scan(home: Path, monkeypatch: pytest.MonkeyPatch, as_of: str, *extra: str) -> dict[str, Any]:
    monkeypatch.setenv("ALPHA_DATA_DIR", str(home))
    result = CliRunner().invoke(app, [*SCAN, "--as-of", as_of, *extra])
    assert result.exit_code == 0, result.output
    payload: dict[str, Any] = json.loads(result.stdout)
    return payload


def _flat(value: object, path: str = "") -> list[tuple[str, object]]:
    if isinstance(value, dict):
        return [item for k, v in sorted(value.items()) for item in _flat(v, f"{path}/{k}")]
    if isinstance(value, list):
        return [item for i, v in enumerate(value) for item in _flat(v, f"{path}/{i}")]
    return [(path, value)]


def assert_equal_results(left: object, right: object) -> None:
    """Every number equal to 1e-9 relative; every other value exactly equal."""
    a, b = _flat(left), _flat(right)
    assert [p for p, _ in a] == [p for p, _ in b]
    for (path, x), (_, y) in zip(a, b, strict=True):
        if isinstance(x, float) and isinstance(y, float):
            assert x == pytest.approx(y, rel=1e-9, abs=1e-12) or (np.isnan(x) and np.isnan(y)), path
        else:
            assert x == y, path


class Latest:
    """The latest bar each wrapped reader call returned."""

    def __init__(self) -> None:
        self.bars: list[datetime] = []


@pytest.fixture
def latest(monkeypatch: pytest.MonkeyPatch) -> Latest:
    seen = Latest()
    load_bars = _runner.load_bars

    def wrapped(*args: Any, **kwargs: Any) -> tuple[list[Bar], str | None]:
        result = load_bars(*args, **kwargs)
        seen.bars.append(max(bar.ts for bar in result[0]))
        return result

    monkeypatch.setattr(_runner, "load_bars", wrapped)
    return seen


def _result_part(payload: dict[str, Any]) -> dict[str, Any]:
    skip = {"scan_id", "attempt_id", "result_digest", "reserve", "labels"}
    return {k: v for k, v in payload.items() if k not in skip}


def test_equity_scan_never_loads_a_held_back_bar_and_equals_the_cut_store(
    tmp_path: Path, latest: Latest, monkeypatch: pytest.MonkeyPatch
) -> None:
    poisoned = _equity_home(tmp_path / "poisoned", LONG, poisoned=True)
    cut = _equity_home(tmp_path / "cut", SHORT, poisoned=False)
    held = _scan(poisoned, monkeypatch, "2024-06-30")
    assert latest.bars and all(ts.date() < RESERVED_DAY for ts in latest.bars), latest.bars
    plain = _scan(cut, monkeypatch, "2024-06-30")
    assert held["reserve"] == {"reserved_start": RESERVED_START, "held_back_bars": HELD * 5}
    assert held["labels"] == [HELD_BACK]
    assert "reserve" not in plain and "labels" not in plain
    assert held["trials"] == plain["trials"] == 4
    assert max(held["dates"]) < RESERVED_START
    assert_equal_results(_result_part(held), _result_part(plain))
    spec = json.loads((poisoned / "scans/hypotheses/specs" / f"{held['scan_id']}.json").read_text())
    # The held-back count is a shown fact of the result, never part of the frozen spec (M97).
    assert "research_cutoff" not in spec and "reserve" not in spec


def test_text_replay_and_an_earlier_user_cutoff(
    tmp_path: Path, latest: Latest, monkeypatch: pytest.MonkeyPatch
) -> None:
    poisoned = _equity_home(tmp_path / "poisoned", LONG, poisoned=True)
    monkeypatch.setenv("ALPHA_DATA_DIR", str(poisoned))
    args = [a for a in SCAN if a != "--json"]
    text = CliRunner().invoke(app, [*args, "--as-of", "2024-06-30"])
    assert text.exit_code == 0, text.output
    sentence = f"Held back {HELD * 5} bars from {RESERVED_START} on"
    assert sentence in text.stdout
    scan_id = text.stdout.split()[2].removesuffix(":")
    replay = CliRunner().invoke(app, ["scan", "replay", scan_id, "--json"])
    assert replay.exit_code == 0, replay.output
    assert json.loads(replay.stdout)["reserve"]["held_back_bars"] == HELD * 5
    early = _scan(poisoned, monkeypatch, "2023-06-30")
    assert "reserve" not in early and "labels" not in early
    spec = json.loads(
        (poisoned / "scans/hypotheses/specs" / f"{early['scan_id']}.json").read_text()
    )
    assert "research_cutoff" not in spec
    assert all(ts.date() <= date(2023, 6, 30) for ts in latest.bars[-5:])


def test_a_store_with_no_held_back_bar_keeps_its_result_and_inputs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = _equity_home(tmp_path / "pre", PRE, poisoned=False)
    payload = _scan(home, monkeypatch, "2024-06-30")
    assert "reserve" not in payload and "labels" not in payload
    spec = json.loads((home / "scans/hypotheses/specs" / f"{payload['scan_id']}.json").read_text())
    assert "research_cutoff" not in spec and "reserve" not in spec
    inputs = {k: v for k, v in spec.items() if k not in {"code_hash", "lock_hash"}}
    digest = hashlib.sha256(_hypothesis_scan.canonical_bytes(inputs)).hexdigest()
    assert (payload["result_digest"], digest) == (PINNED_PRE_RESULT, PINNED_PRE_INPUTS)


def _crypto_rows(day: date, value: float, name: str, symbol: str) -> dict[str, Any]:
    return {
        "timestamp": datetime.combine(day, datetime.min.time(), tzinfo=UTC),
        "symbol": symbol,
        "category": "linear",
        name: value,
    }


def _crypto_home(root: Path, last: date) -> CryptoBulkStore:
    from alpha_cli._crypto_panel import FAMILIES

    store = crypto_store(root)
    days = (last - date(2023, 10, 1)).days + 1
    for column, symbol in enumerate(("AAAUSDT", "BBBUSDT", "CCCUSDT")):
        for family, (frequency, units, convention, name) in FAMILIES.items():
            dataset = {
                "schema_version": 1,
                "provider": "bybit",
                "venue": "bybit",
                "market_type": "linear",
                "family": family,
                "instrument": symbol,
                "base_asset": symbol[:-4],
                "quote_asset": "USDT",
                "frequency": frequency,
                "units": units,
                "timestamp_convention": convention,
            }
            rows = []
            for i in range(days):
                day = date(2023, 10, 1) + timedelta(days=i)
                base = 100.0 + i * (column + 1) + (i % (column + 2)) * (1 if i % 3 else -1) * 0.5
                late = 1000.0 if day >= RESERVED_DAY else 1.0
                rows.append(_crypto_rows(day, base * late, name, symbol))
            crypto_manifest(store, dataset, pl.DataFrame(rows))
    return store


def test_crypto_lane_reads_no_reserved_row_and_equals_the_cut_store(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from alpha_cli import _crypto_panel

    poisoned = _crypto_home(tmp_path / "poisoned", date(2024, 2, 27))
    cut = _crypto_home(tmp_path / "cut", date(2023, 12, 31))
    args = [
        "scan",
        "hypotheses",
        "--lane",
        "crypto",
        "--symbols",
        "AAAUSDT,BBBUSDT,CCCUSDT",
        "--as-of",
        "2024-02-20",
        "--horizons",
        "1,5",
        "--min-names",
        "3",
        "--quantiles",
        "3",
        "--json",
    ]
    outputs = []
    for home, store in ((tmp_path / "p", poisoned), (tmp_path / "c", cut)):
        monkeypatch.setenv("ALPHA_DATA_DIR", str(home))
        monkeypatch.setattr(_crypto_panel, "bulk_store", lambda _, s=store: s)
        result = CliRunner().invoke(app, args)
        assert result.exit_code == 0, result.output
        outputs.append(json.loads(result.stdout))
    held, plain = outputs
    # Bars through 2024-02-19, funding and open interest through 2024-02-20, three symbols.
    assert held["reserve"]["held_back_rows"] == 3 * (50 + 51 + 51)
    assert held["labels"] == [HELD_BACK] and "reserve" not in plain
    assert_equal_results(_result_part(held), _result_part(plain))
    assert max(held["dates"]) <= RESERVED_START


def _archive_store(root: Path, last: date) -> tuple[CryptoBulkStore, str]:
    store = CryptoBulkStore(
        bulk_root=root / "bulk",
        manifest_root=root / "crypto" / "manifests",
        expected_volume_uuid="FIXTURE",
        volume_uuid=lambda path: "FIXTURE",
    )
    days = (last - date(2023, 1, 1)).days + 1
    rng = np.random.default_rng(7)
    closes = 100.0 * np.cumprod(1.0 + 0.001 + rng.normal(0.0, 0.02, days))
    rows = []
    for i, c in enumerate(closes.tolist()):
        day = date(2023, 1, 1) + timedelta(days=i)
        k = 1000.0 if day >= RESERVED_DAY else 1.0
        rows.append(
            {
                "open_time": datetime(2023, 1, 1, tzinfo=UTC) + timedelta(days=i),
                "open": c * k,
                "high": c * 1.01 * k,
                "low": c * 0.99 * k,
                "close": c * k,
                "base_volume": 10.0,
            }
        )
    frame = pl.DataFrame(rows)
    buffer = io.BytesIO()
    frame.write_parquet(buffer)
    raw = buffer.getvalue()
    digest = hashlib.sha256(raw).hexdigest()
    key = f"fixtures/{digest}.parquet"
    (store.bulk_root / key).parent.mkdir(parents=True, exist_ok=True)
    (store.bulk_root / key).write_bytes(raw)
    parent = store._publish_manifest(
        {
            "artifact_kind": "raw",
            "artifact_key": key,
            "artifact_sha256": digest,
            "artifact_bytes": len(raw),
            "receipt": {"fetched_at": "2020-03-01T00:00:00Z"},
        }
    )
    dataset = {
        "schema_version": 1,
        "provider": "binance",
        "venue": "binance",
        "market_type": "spot",
        "family": "market_bars",
        "instrument": "BTCUSDT",
        "base_asset": "BTC",
        "quote_asset": "USDT",
        "frequency": "1d",
        "units": "provider_native_ohlcv",
        "timestamp_convention": "interval_start_utc",
    }
    manifest = store._publish_manifest(
        {
            "artifact_kind": "normalized",
            "artifact_key": key,
            "artifact_sha256": digest,
            "artifact_bytes": len(raw),
            "provider": "binance",
            "dataset": dataset,
            "input_manifest_ids": [parent["manifest_id"]],
            "quality": CryptoQualityReportV1(
                dataset_sha256=digest,
                method_version=QUALITY_METHOD_VERSION,
                state="qualified",
                failures=(),
                warnings=(),
                observed_start=None,
                observed_end=None,
                row_count=frame.height,
                correction_lineage=(),
            ).to_dict(),
        }
    )
    return store, str(manifest["manifest_id"])


def _replay(
    home: Path,
    store: CryptoBulkStore,
    manifest_id: str,
    monkeypatch: pytest.MonkeyPatch,
    *extra: str,
) -> tuple[str, dict[str, Any], list[datetime]]:
    returned: list[datetime] = []
    load = _archive_bars.load_archive_bars

    def wrapped(*args: Any, **kwargs: Any) -> list[Bar]:
        bars = load(*args, **kwargs)
        returned.extend(bar.ts for bar in bars)
        return bars

    monkeypatch.setattr(_archive_bars, "load_archive_bars", wrapped)
    monkeypatch.setattr(crypto_data_cmds, "_bulk_store", lambda: store)
    monkeypatch.setenv("ALPHA_DATA_DIR", str(home))
    args = ["backtest", "run", "BTCUSDT", "--manifest-id", manifest_id, "--timeframe", "1D"]
    args += ["--strategy", "ma_crossover", "--account-type", "MARGIN", *extra]
    result = CliRunner().invoke(app, args)
    assert result.exit_code == 0, result.output
    paths = list((home / "runs").glob("*/manifest.json"))
    assert len(paths) == 1
    return result.output, json.loads(paths[0].read_text()), returned


def test_manifest_replay_cuts_the_archive_and_discloses_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store, mid = _archive_store(tmp_path / "long", date(2024, 6, 30))
    cut_store, cut_mid = _archive_store(tmp_path / "short", date(2023, 12, 31))
    out, held, returned = _replay(tmp_path / "h", store, mid, monkeypatch)
    assert returned and max(returned).date() < RESERVED_DAY
    days = (date(2024, 6, 30) - RESERVED_DAY).days + 1
    assert f"Held back {days} bars from {RESERVED_START} on" in out
    assert held["reserve"] == {"reserved_start": RESERVED_START, "held_back_bars": days}
    assert HELD_BACK in held["labels"] and held["research_cutoff"] == "2023-12-31"
    _, plain, plain_returned = _replay(tmp_path / "c", cut_store, cut_mid, monkeypatch)
    assert "reserve" not in plain and max(plain_returned).date() == date(2023, 12, 31)
    assert max(returned) == max(plain_returned)
    assert held["final_equity"] == pytest.approx(plain["final_equity"], rel=1e-9, abs=1e-12)
    assert held["run_id"] != plain["run_id"]


def test_manifest_replay_with_an_earlier_user_cutoff_wins(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store, mid = _archive_store(tmp_path / "long", date(2024, 6, 30))
    _, manifest, returned = _replay(
        tmp_path / "h", store, mid, monkeypatch, "--as-of", "2023-06-30"
    )
    assert "reserve" not in manifest and manifest["research_cutoff"] == "2023-06-30"
    assert max(returned).date() < date(2023, 6, 30)


def test_a_manifest_replay_with_no_held_back_bar_keeps_its_run_id(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The run id hashes every source file; fix that one input so the pin tracks the rest.
    monkeypatch.setattr(_runner, "execution_fingerprint", lambda: "ab" * 32)
    store, mid = _archive_store(tmp_path / "short", date(2023, 12, 31))
    out, manifest, _ = _replay(tmp_path / "h", store, mid, monkeypatch)
    assert "Held back" not in out and "labels" not in manifest
    assert manifest["research_cutoff"] is None
    assert manifest["run_id"] == PINNED_PRE_ARCHIVE_RUN
