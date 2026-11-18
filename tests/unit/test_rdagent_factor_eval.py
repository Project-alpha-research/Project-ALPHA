"""Synthetic screening/replay and cross-run ledger contracts (no market data)."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any
from unittest.mock import patch

import numpy as np
import pandas as pd
import polars as pl
import pytest
from typer.testing import CliRunner

from alpha_cli import _rdagent_judge as judge
from alpha_cli import rdagent_factor_eval as ev
from alpha_cli.ledger_cmds import ledger_app
from alpha_cli.spine.trial_reader import LedgerSource, read_ledgers, trials_for_deflation
from alpha_core import DataError
from alpha_data.crypto.contracts import CryptoDatasetIdentityV1
from alpha_data.crypto.ingestion import ingest_provider_payload
from alpha_data.crypto.providers.binance import parse_binance_klines
from alpha_data.crypto.storage import Capacity, CryptoBulkStore


@pytest.fixture
def recorded_time(monkeypatch: pytest.MonkeyPatch) -> None:
    """Fix the recording clock so byte comparisons still check every result field."""

    class Clock:
        @staticmethod
        def now(zone: object) -> datetime:
            assert zone is UTC
            return datetime(2026, 11, 17, tzinfo=UTC)

    monkeypatch.setattr(ev, "datetime", Clock)


def fixture(run: Path, *, seed: int = 42, noise: bool = False) -> Path:
    (run / "panel").mkdir(parents=True)
    dates = pd.date_range("2021-01-01", "2023-12-31", tz="UTC")
    rng = np.random.default_rng(42)
    component = rng.normal(0, 0.018, (len(dates), 15))
    returns = component + rng.normal(0, 0.006, component.shape)
    opens = 100 * np.cumprod(1 + returns, axis=0)
    index = pd.MultiIndex.from_product(
        [dates.date, [f"C{i:02}USDT" for i in range(15)]], names=["date", "instrument"]
    )
    panel = pd.DataFrame(
        {
            "open": opens.ravel(),
            "close": opens.ravel(),
            "high": opens.ravel() * 1.01,
            "low": opens.ravel() * 0.99,
            "volume": 100.0,
            "quote_volume": 10000.0,
        },
        index=index,
    ).reset_index()
    panel.to_parquet(run / "panel/panel.parquet", index=False)
    (run / "panel/panel-receipt.json").write_text(
        json.dumps(
            {
                "panel_sha256": hashlib.sha256(
                    (run / "panel/panel.parquet").read_bytes()
                ).hexdigest(),
                "instruments": {s: {"last_day": "2023-12-31"} for s in panel.instrument.unique()},
            }
        )
    )
    signal = np.roll(component, -2, axis=0) + np.random.default_rng(seed).normal(
        0, 0.003, component.shape
    )
    if noise:
        signal = np.random.default_rng(seed).normal(size=component.shape)
    pd.DataFrame({"factor": signal.ravel()}, index=index).reset_index().to_parquet(
        run / "factors.parquet", index=False
    )
    req = run / "request.json"
    req.write_text(
        json.dumps(
            {
                "schema": "AlphaRdagentFactorRequestV1",
                "iteration": 0,
                "hypothesis_sha256": "b" * 64,
                "values_file": "factors.parquet",
                "factors": [
                    {
                        "name": "factor",
                        "declared_direction": 1,
                        "primary_clock": "weekly",
                        "direction_reason": "Persistent demand rewards this ranking.",
                        "code_sha256": hashlib.sha256(str(seed).encode()).hexdigest(),
                        "status": "OK",
                        "lookahead": {"status": "PASS"},
                    }
                ],
            }
        )
    )
    return req


def evaluate(run: Path, req: Path, ledger: Path) -> dict[str, Any]:
    return ev.evaluate(run, req, run / "result.json", ledger)


def test_unknown_ledger_rows_count_conservatively_and_do_not_repeat(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    ledger = tmp_path / "ledger"
    first = tmp_path / "first"
    req = fixture(first)
    request = json.loads(req.read_bytes())
    request["factors"][0]["status"] = "FAILED"
    req.write_text(json.dumps(request))
    evaluate(first, req, ledger)
    old = ev._read_ledger(ledger)[0]
    digest = hashlib.sha256(b"43").hexdigest()
    unknown = {
        "schema": "FutureTrial",
        "trial_index": 2,
        "code_sha256": digest,
        "status": "CANDIDATE",
        "p": 0.0,
    }
    ledger.write_text(
        "".join(json.dumps(r) + "\n" for r in [old, unknown, {**old, "trial_index": 3}])
    )
    run = tmp_path / "new"
    req = fixture(run, seed=43)
    with (
        patch.object(
            judge,
            "screen",
            side_effect=[{"status": "OK", "p": p, "direction": 1} for p in (1.0, 0.05, 1.0)],
        ),
        patch.object(ev, "replay", side_effect=AssertionError("must not replay")),
    ):
        result = evaluate(run, req, ledger)
    assert result["ledger_unknown_rows"] == {"count": 1, "schemas": ["FutureTrial"]}
    assert "1" in capsys.readouterr().err and result["factors"][0]["status"] == "SCREEN_FAIL"
    assert result["family_size"] == 3  # two primary-clock entries and one unknown
    assert result["factors"][0]["q"] == pytest.approx(0.15)
    assert result["distinct_factors"] == 2
    assert result["factors"][0]["distinct_factors"] == 2
    assert result["factors"][0]["trial_index"] == 4
    assert result["ledger_trials_all_families"] == 4


@pytest.mark.parametrize(
    "row",
    [
        [],
        {},
        {"schema": None},
        {"schema": "Future", "trial_index": 2},
        {"schema": "AlphaRdagentFactorTrialV1", "trial_index": 1},
    ],
)
def test_ledger_malformed_known_or_untyped_rows_fail(tmp_path: Path, row: Any) -> None:
    ledger = tmp_path / "ledger"
    ledger.write_text(json.dumps(row) + "\n")
    with pytest.raises(DataError, match="invalid trial ledger line 1"):
        ev._read_ledger(ledger)


def test_ledger_unknown_rows_kept_and_partial_line_fails_loud(tmp_path: Path) -> None:
    ledger = tmp_path / "ledger"
    row = {"schema": "Future", "trial_index": 1}
    ledger.write_text(json.dumps(row) + "\n")
    assert ev._read_ledger(ledger).unknown_rows == [row]
    # Writers append under the lock: a partial last line is a crashed writer, not a reader race.
    ledger.write_text(json.dumps(row) + '\n{"schema":')
    with pytest.raises(DataError, match="incomplete trial ledger line"):
        ev._read_ledger(ledger)
    ledger.write_text('{"schema":\n')
    with pytest.raises(DataError, match="invalid trial ledger line 1"):
        ev._read_ledger(ledger)


def test_known_only_evaluation_bytes_match_declared_primary_baseline(
    tmp_path: Path, recorded_time: None
) -> None:
    run = tmp_path / "baseline"
    req = fixture(run)
    request, panel, values, _ = ev._inputs(run, req)
    request["factors"][0]["status"] = "FAILED"
    # Fixed inputs exclude source fingerprints; the honesty rule changes counts and declarations.
    record = ev._evaluate_locked(
        run,
        request,
        panel,
        values,
        {
            "panel_sha256": "0" * 64,
            "factor_values_path": "/recorded/factors.parquet",
            "factors_sha256": "a" * 64,
        },
        tmp_path / "ledger",
    )
    # Retain the earlier presentation projection, pinning the complete new rule record below.
    # The baseline changes deliberately: one primary look, declarations, cutoffs and chance fields
    # (chance rate re-measured 2026-11-17: 0.004 -> 0.001).
    row = record["factors"][0]
    assert record["lead_factor"] is None
    record["lead_factor"] = "factor"  # earlier output incorrectly selected this failed factor
    assert row.pop("universe_includes_delisted") is False
    assert row.pop("writeoff_count") == 0
    message = row.pop("writeoff_message")
    # Item 8 (fixups 4): the sentence names only replayed clocks; this failed factor has none.
    assert message == "factor: no holding clock was replayed, so nothing was written off."
    assert message in record["feedback_text"]
    record["feedback_text"] = record["feedback_text"].replace(" " + message, "")
    current = row["survivorship"]
    assert current == (
        "15 instruments, 0 later delisted declared; survivors-only selection; "
        "survivorship can bias results upward"
    )
    assert record["disclosures"]["survivorship"] == current
    row["survivorship"] = record["disclosures"]["survivorship"] = ev.SURVIVORSHIP
    record["feedback_text"] = record["feedback_text"].replace(current, ev.SURVIVORSHIP)
    assert record["disclosures"].pop("spread_check").startswith("ADR-0055")
    # Recording metadata and presentation are checked before the pinned byte projection.
    assert record["factors"][0].pop("recorded_at") == "2026-11-17T00:00:00+00:00"
    looks = (
        "looks so far across all ideas: 1 (sets the screen cutoff); "
        "primary clocks now; legacy clocks and unreadable rows included;"
    )
    assert looks in record["feedback_text"]
    assert "Factor-family trials" not in record["feedback_text"]
    # This request predates proposal summaries. Verify both additive fields before comparing
    # every previously recorded byte against the existing digest.
    assert row.pop("plain_summary") is None
    assert row.pop("plain_summary_status") == "missing"
    # Input-column disclosure is add-only: removing it must leave the pinned bytes unchanged.
    assert record["factors"][0].pop("input_columns_method").startswith("fallback:")
    assert "Ledger rows, all families (rules, repeats too): 1" in record["feedback_text"]
    assert "Factor failed: reason not recorded." in record["feedback_text"]
    record["feedback_text"] = (
        record["feedback_text"]
        .replace(looks, "Ledger trials: 1;")
        .replace(
            "Ledger rows, all families (rules, repeats too)",
            "ledger_trials_all_families",
        )
    )
    cutoff = "(0 confirmed); looks so far across all ideas: 1 (sets the screen cutoff)."
    for container, key in ((record, "feedback_text"), (record["legacy_result"], "factor.feedback")):
        assert cutoff in container[key]
        container[key] = (
            container[key]
            .replace("Factor failed: reason not recorded. ", "Factor execution failed.")
            .replace(cutoff, "(1 looks, 0 confirmed).")
        )
    # Assert every added field and phrase before reproducing the immutable baseline.
    assert "family" not in row  # this request names no family; the judge always sends one
    assert row.pop("critic_status") == "unavailable"
    assert row.pop("critic_reason") == "no code critic opinion recorded"
    for container, key in ((record, "feedback_text"), (record["legacy_result"], "factor.feedback")):
        for added in (
            "failed: coding or execution; spread status: not recorded. ",
            "Code critic unavailable: no code critic opinion recorded. ",
            "Ledger screen cutoff: 0.1. ",
        ):
            assert container[key].count(added) == 1
            container[key] = container[key].replace(added, "")
    # Keep explicit unavailable-value assertions before the byte projection.
    for container, key in ((record, "feedback_text"), (record["legacy_result"], "factor.feedback")):
        assert "None" not in container[key]
        for field in ("mean rank IC", "net annual excess", "turnover per day"):
            assert f"{field} not available" in container[key]
            container[key] = container[key].replace(f"{field} not available", f"{field} None")
    # Shortlist bookkeeping is add-only: removing it must leave the pinned bytes unchanged.
    assert record["factors"][0].pop("shortlist") is False
    # Clock-labelled presentation is tested separately; pin all new counting fields.
    for row in record["factors"]:
        for key in ("reason", "figures_clock", "mean_ic", "spread"):
            row.pop(key, None)
    assert ev.sha(ev.canonical(record)) == (
        "f52128980a352b3eebe36b8f1c917fbf4fdc0ceb9e270dfc4eed56e8fa189590"
    )


def test_unknown_rows_never_reach_external_ledger_consumers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    import sys

    from alpha_cli import rdagent_exposure

    ledger = tmp_path / "ledger"
    ledger.write_text('{"schema":"Future", "trial_index":1}\n')
    rows = ev._read_ledger(ledger)
    # Rule-family callers use length for the next line index; exposure callers iterate.
    assert len(rows) == 1
    assert list(rows) == []
    monkeypatch.setattr(sys, "argv", ["exposure", "list", "--ledger", str(ledger), "--json"])
    rdagent_exposure.main()
    captured = capsys.readouterr()
    assert json.loads(captured.out)["trials"] == []
    assert "1 ledger rows of other kinds were skipped (Future)" in captured.err


@pytest.mark.parametrize("unknown_code", [None, b"historical", b"other"])
def test_import_ignores_unknown_identity_and_counts_unknown_trial(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, unknown_code: bytes | None
) -> None:
    ledger, source = tmp_path / "ledger", tmp_path / "import.json"
    _, item = historical(tmp_path, code=b"historical")
    unknown: dict[str, Any] = {"schema": "Future", "trial_index": 1}
    if unknown_code:
        unknown["code_sha256"] = ev.sha(unknown_code)
    ledger.write_text(json.dumps(unknown) + "\n")
    source.write_text(json.dumps([item]))
    import_command(ledger, source, monkeypatch)
    imported = ev._read_ledger(ledger)[1]
    assert imported["trial_index"] == 2
    assert imported["distinct_factors"] == 1
    assert imported["total_trials"] == imported["family_size"] == 2


def test_planted_primary_factor_passes_floor_deflation_and_is_deterministic(
    tmp_path: Path, recorded_time: None
) -> None:
    run = tmp_path / "run"
    req = fixture(run)
    ledger = tmp_path / "trials.jsonl"
    result = evaluate(run, req, ledger)
    factor = result["factors"][0]
    assert factor["status"] == "CANDIDATE"
    assert (
        factor["replay"]["deflated_sharpe"]["dsr"]
        >= factor["replay"]["deflated_sharpe"]["threshold"]
    )
    assert factor["q"] < 0.10
    assert factor["replay"]["net"]["annualized_return"] > 0
    assert result["decision"] is True
    assert result["label"] == ev.LABEL
    assert (
        "15 instruments, 0 later delisted declared; survivors-only selection"
        in result["feedback_text"]
    )
    assert factor["universe_includes_delisted"] is False
    assert all(v is False for v in result["authority"].values())
    original = (run / "result.json").read_bytes()
    original_lines = ledger.read_bytes()
    other = tmp_path / "empty-ledger.jsonl"
    ev.evaluate(run, req, run / "second-result.json", other)
    assert (run / "second-result.json").read_bytes() == original
    assert other.read_bytes() == original_lines


@pytest.mark.parametrize("seed", [19, 81])
def test_noise_never_replayed(tmp_path: Path, seed: int) -> None:
    run = tmp_path / "run"
    req = fixture(run, seed=seed, noise=True)
    with patch.object(
        judge, "run_weight_replay", side_effect=AssertionError("screen failed but replay called")
    ):
        record = evaluate(run, req, tmp_path / "ledger.jsonl")
    assert record["decision"] is False
    assert record["factors"][0]["status"] == "SCREEN_FAIL"
    assert record["factors"][0]["q"] >= ev.Q_THRESHOLD


def test_noise_screen_is_calibrated() -> None:
    # Pure noise passes a 10% screen about 10% of the time (seed 7 of the fixture is one such
    # chance pass, q 0.01); a much higher rate would mean the inference is anti-conservative.
    first, last = (pd.Timestamp(d) for d in ev.EXPLORATION)
    shape = ((last - first).days + 1, 15)
    outcome = np.random.default_rng(42).normal(0, 0.02, shape)
    passes = 0
    for seed in range(80):
        signal = np.random.default_rng(1000 + seed).normal(size=shape)
        passes += ev.screen(signal, outcome, f"{seed:064x}")["p"] < ev.Q_THRESHOLD
    assert passes / 80 <= 0.2


def test_repeat_across_runs_and_append_only(tmp_path: Path) -> None:
    first, second = tmp_path / "first", tmp_path / "second"
    ledger = tmp_path / "ledger.jsonl"
    evaluate(first, fixture(first), ledger)
    before = ledger.read_bytes()
    result = evaluate(second, fixture(second), ledger)
    assert ledger.read_bytes().startswith(before)
    assert result["family_size"] == 1
    assert result["distinct_factors"] == 1
    assert result["total_trials"] == 2
    repeated = result["factors"][0]
    assert repeated["status"] == "REPEAT"
    assert repeated["first_trial"]["run_id"] == "first"
    assert not result["decision"]


def test_failures_and_degenerate_count_in_family(tmp_path: Path) -> None:
    run = tmp_path / "run"
    req = fixture(run)
    frame = pd.read_parquet(run / "factors.parquet")
    frame["factor"] = 1.0
    frame.to_parquet(run / "factors.parquet", index=False)
    value = json.loads(req.read_bytes())
    value["factors"] += [
        {**value["factors"][0], "name": s, "code_sha256": h * 64, "status": s, "lookahead": {}}
        for s, h in [("FAILED", "c"), ("LOOKAHEAD", "d")]
    ]
    req.write_text(json.dumps(value))
    result = evaluate(run, req, tmp_path / "ledger.jsonl")
    assert result["family_size"] == 3
    assert result["distinct_factors"] == 3
    assert [f["status"] for f in result["factors"]] == ["DEGENERATE", "FAILED", "LOOKAHEAD"]
    assert all(f["p"] == pytest.approx(1) for f in result["factors"])


@pytest.mark.parametrize("kind", ["values", "panel", "tamper", "ledger"])
def test_invalid_inputs_refused(tmp_path: Path, kind: str) -> None:
    run = tmp_path / "run"
    req = fixture(run)
    ledger = tmp_path / "ledger.jsonl"
    if kind == "values":
        frame = pd.read_parquet(run / "factors.parquet")
        frame.loc[0, "date"] = pd.Timestamp("2024-01-01").date()
        frame.to_parquet(run / "factors.parquet", index=False)
    elif kind == "panel":
        receipt = json.loads((run / "panel/panel-receipt.json").read_bytes())
        receipt["instruments"]["C00USDT"]["last_day"] = "2024-01-01"
        (run / "panel/panel-receipt.json").write_text(json.dumps(receipt))
    elif kind == "tamper":
        with (run / "panel/panel.parquet").open("ab") as stream:
            stream.write(b"tamper")
    else:
        ledger.write_text('{"schema": "wrong"}\n')
    with pytest.raises(DataError):
        evaluate(run, req, ledger)


def test_one_failing_factor_is_recorded_as_error_and_the_rest_still_land(tmp_path: Path) -> None:
    run = tmp_path / "run"
    req = fixture(run)
    value = json.loads(req.read_bytes())
    value["factors"].append(
        {
            **value["factors"][0],
            "name": "broken",
            "code_sha256": "e" * 64,
            "status": "OK",
            "lookahead": {},
        }
    )
    frame = pd.read_parquet(run / "factors.parquet")
    frame["broken"] = np.random.default_rng(94).normal(size=len(frame))
    frame.to_parquet(run / "factors.parquet", index=False)
    req.write_text(json.dumps(value))
    real = ev.screen

    def flaky(
        signal: np.ndarray,
        outcome: np.ndarray,
        digest: str,
        *,
        series: dict[str, Any] | None = None,
        declared_direction: int | None = None,
    ) -> dict[str, Any]:
        if digest in {"e" * 64, *(ev.sha(("e" * 64 + c).encode()) for c in ("weekly", "monthly"))}:
            raise ZeroDivisionError("planted")
        return real(signal, outcome, digest, series=series, declared_direction=declared_direction)

    ledger = tmp_path / "ledger.jsonl"
    with patch.object(judge, "screen", flaky):
        result = evaluate(run, req, ledger)
    statuses = {f["name"]: f["status"] for f in result["factors"]}
    assert statuses == {"factor": "CANDIDATE", "broken": "ERROR"}
    assert result["family_size"] == 2
    assert result["distinct_factors"] == 2
    assert len(ledger.read_bytes().splitlines()) == 2


def test_a_day_with_too_few_names_is_degenerate_not_a_crash(tmp_path: Path) -> None:
    run = tmp_path / "run"
    req = fixture(run)
    frame = pd.read_parquet(run / "factors.parquet")
    day = frame["date"] == frame["date"].iloc[15 * 400]
    frame.loc[day & ~frame["instrument"].isin(["C00USDT", "C01USDT"]), "factor"] = float("nan")
    frame.to_parquet(run / "factors.parquet", index=False)
    result = evaluate(run, req, tmp_path / "ledger.jsonl")
    factor = result["factors"][0]
    assert factor["clocks"]["daily"]["screen"]["status"] == "DEGENERATE"
    assert factor["clocks"]["daily"]["screen"]["thin_days"] == 1
    assert factor["clocks"]["weekly"]["screen"]["thin_days"] == 0
    assert factor["clocks"]["monthly"]["screen"]["thin_days"] == 0
    assert factor["status"] == "CANDIDATE"
    assert (
        factor["replay"]["deflated_sharpe"]["dsr"]
        >= factor["replay"]["deflated_sharpe"]["threshold"]
    )


# --- freeze: real store API on synthetic provider payloads (no market data) ------------------

FREEZE_START = datetime(2023, 12, 26, tzinfo=UTC)
UUID = "758CBD77-1003-3BA3-AD28-1D647F5E2A08"


def _bulk_store(root: Path) -> CryptoBulkStore:
    (root / "bulk").mkdir(parents=True, exist_ok=True)
    return CryptoBulkStore(
        bulk_root=root / "bulk",
        manifest_root=root / "control" / "crypto" / "manifests",
        expected_volume_uuid=UUID,
        volume_uuid=lambda _: UUID,
        capacity=lambda _: Capacity(total_bytes=20_000_000, free_bytes=10_000_000),
        minimum_free_bytes=100,
    )


def _publish(
    store: CryptoBulkStore,
    instrument: str,
    closes: tuple[float, ...],
    *,
    start: datetime = FREEZE_START,
    skip: int | None = None,
    fetched: datetime | None = None,
) -> None:
    day = timedelta(days=1)
    dataset = CryptoDatasetIdentityV1(
        provider="binance",
        venue="binance",
        market_type="spot",
        family="market_bars",
        instrument=instrument,
        base_asset=instrument.removesuffix("USDT"),
        quote_asset="USDT",
        frequency="1d",
        units="provider_native_ohlcv",
        timestamp_convention="interval_start_utc",
    )
    rows = [
        [
            int((start + i * day).timestamp() * 1000),
            c,
            c + 1,
            c - 1,
            c,
            100.0,
            int((start + (i + 1) * day).timestamp() * 1000) - 1,
            1000.0,
            10,
            50.0,
            500.0,
            0,
        ]
        for i, c in enumerate(closes)
        if i != skip
    ]
    ingest_provider_payload(
        store,
        dataset=dataset,
        payload=json.dumps(rows).encode(),
        request=(("symbol", instrument), ("interval", "1d"), ("startTime", str(rows[0][0]))),
        fetched_at=fetched or datetime(2026, 1, 1, tzinfo=UTC),
        provider_schema="binance-public-rest-v1",
        parser_version="binance-archive-rest-v1",
        logical_name="daily.json",
        parser=lambda raw: parse_binance_klines(raw, source="rest_json"),
        observed_column="open_time",
        key_columns=("open_time",),
    )


def _freeze(tmp_path: Path, store: CryptoBulkStore) -> dict[str, Any]:
    with patch.object(judge, "configured_crypto_bulk_store", lambda _: store):
        return ev.freeze(tmp_path / "control", tmp_path / "out")


def test_freeze_two_coins_stops_before_the_reserved_window(tmp_path: Path) -> None:
    store = _bulk_store(tmp_path)
    _publish(store, "BTCUSDT", (10.0, 11.0, 12.0, 13.0, 14.0, 15.0, 16.0, 17.0))
    _publish(store, "ETHUSDT", (5.0, 6.0, 7.0, 8.0, 9.0, 10.0, 11.0, 12.0))
    _publish(  # an equal recapture counts once
        store,
        "ETHUSDT",
        (5.0, 6.0, 7.0, 8.0, 9.0, 10.0, 11.0, 12.0),
        fetched=datetime(2026, 2, 1, tzinfo=UTC),
    )
    receipt = _freeze(tmp_path, store)
    panel = pd.read_parquet(tmp_path / "out/panel.parquet")
    assert receipt["rows"] == len(panel) == 12  # 2023-12-26..31 for two coins; 2024 dropped
    assert {i["last_day"] for i in receipt["instruments"].values()} == {"2023-12-31"}
    assert len(receipt["manifests"]) == 3
    digest = hashlib.sha256((tmp_path / "out/panel.parquet").read_bytes()).hexdigest()
    assert receipt["panel_sha256"] == digest


def test_freeze_records_an_interior_gap_instead_of_refusing_it(tmp_path: Path) -> None:
    # A missing instrument-day is recorded, never bridged and never a reason to drop the coin
    # (dropping gapped coins would bring survivorship bias back).
    store = _bulk_store(tmp_path)
    _publish(store, "BTCUSDT", (10.0, 11.0, 12.0, 13.0), skip=1)
    receipt = _freeze(tmp_path, store)
    assert receipt["missing_instrument_days"] == 1
    assert receipt["instruments"]["BTCUSDT"]["longest_gap"] == 1
    assert receipt["rows"] == 3


@pytest.mark.parametrize("defect", ["overlap", "empty"])
def test_freeze_refuses_overlaps_and_nothing(tmp_path: Path, defect: str) -> None:
    store = _bulk_store(tmp_path)
    if defect == "overlap":
        _publish(store, "BTCUSDT", (10.0, 11.0, 12.0))
        _publish(store, "BTCUSDT", (10.0, 11.5, 12.0), fetched=datetime(2026, 3, 1, tzinfo=UTC))
    with pytest.raises(DataError):
        _freeze(tmp_path, store)


def test_validate_panel_refuses_invalid_prices_and_reserved_dates() -> None:
    base = pl.DataFrame(
        {
            "date": [date(2023, 1, 1), date(2023, 1, 2)],
            "instrument": ["A", "A"],
            "open": [1.0, 1.0],
            "high": [2.0, 2.0],
            "low": [0.5, 0.5],
            "close": [1.5, 1.5],
            "volume": [1.0, 1.0],
            "quote_volume": [1.0, 1.0],
        }
    )
    assert ev.validate_panel(base).height == 2
    for column, value in (("open", -1.0), ("high", 0.6), ("volume", float("nan"))):
        with pytest.raises(DataError):
            ev.validate_panel(base.with_columns(pl.lit(value).alias(column)))
    with pytest.raises(DataError):
        ev.validate_panel(base.with_columns(pl.lit(date(2024, 1, 1)).alias("date")))
    with pytest.raises(DataError):
        ev.validate_panel(base.head(0))


def historical(tmp_path: Path, *, code: bytes = b"42") -> tuple[Path, dict[str, Any]]:
    path = tmp_path / "factor.py"
    path.write_bytes(code)
    return path, {
        "name": "historical",
        "code_path": str(path),
        "run_id": "old-run",
        "iteration": 2,
        "windows": ev.WINDOWS,
        "evaluated_by": "external judge",
        "result_summary": "The result was previously viewed",
        "source": "/old/run/result.json",
    }


def import_command(ledger: Path, source: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "sys.argv",
        [
            "rdagent_factor_eval",
            "import-historical",
            "--ledger",
            str(ledger),
            "--file",
            str(source),
        ],
    )
    ev.main()


def test_evaluation_exposure_and_mixed_schema_ledger(tmp_path: Path) -> None:
    from alpha_cli import rdagent_exposure as ex

    ledger = tmp_path / "trials.jsonl"
    # A legacy line remains byte-for-byte valid and contributes one daily trial.
    legacy = {
        "schema": "AlphaRdagentFactorTrialV1",
        "trial_index": 1,
        "name": "legacy",
        "code_sha256": "a" * 64,
        "run_id": "old",
        "iteration": 0,
        "panel_sha256": "0" * 64,
        "windows": ev.WINDOWS,
        "stage": "none",
        "status": "FAILED",
        "p": 1.0,
        "q": 1.0,
        "family_size": 1,
        "total_trials": 1,
        "screen": {},
        "replay": {},
        "label": ev.LABEL,
        "survivorship": ev.SURVIVORSHIP,
        "authority": ev.AUTHORITY,
    }
    original = ev.canonical(legacy)
    ledger.write_bytes(original)
    entry = {
        "schema": "AlphaExposureEntryV1",
        "entry_index": 1,
        "family": {"id": "xs-range", "definition": "Cross-sectional differences in trading range"},
        "match": {"name_regex": "factor", "instruments": ["*"]},
        "instruments": ["BTCUSDT"],
        "window": {"start": "2024-01-01", "end": "2024-04-01"},
        "statistic_released": "Rank correlation",
        "seen_by": ["owner"],
        "seen_on": "2026-11-14",
        "source": "/old/result.json",
        "status": "known",
        "note": "",
        "label": ev.LABEL,
    }
    log_bytes = ev.canonical(entry)
    ex.exposure_log_path(ledger).write_bytes(log_bytes)
    run = tmp_path / "run"
    result = evaluate(run, fixture(run), ledger)
    row = result["factors"][0]
    assert row["schema"] == "AlphaRdagentFactorTrialV3"
    assert result["family_size"] == row["family_size"] == 2
    assert result["distinct_factors"] == row["distinct_factors"] == 2
    assert row["instruments"] == [f"C{i:02}USDT" for i in range(15)]
    assert row["exposure"]["previously_exposed"] is True
    assert result["inputs"]["exposure_log_sha256"] == ev.sha(log_bytes)
    assert (
        "factor: protected window 2024-01-01+ previously exposed for family xs-range (known); "
        "it cannot give fresh confirmation." in result["feedback_text"]
    )
    assert ledger.read_bytes().startswith(original)
    assert ev._read_ledger(ledger) == [legacy, row]
    for key in ("instruments", "exposure"):
        broken = dict(row)
        del broken[key]
        ledger.write_bytes(original + ev.canonical(broken))
        with pytest.raises(DataError):
            ev._read_ledger(ledger)


def test_imported_identity_is_never_re_evaluated(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ledger, source = tmp_path / "trials.jsonl", tmp_path / "import.json"
    code_path, item = historical(tmp_path)
    source.write_text(json.dumps([item]))
    import_command(ledger, source, monkeypatch)
    before = ledger.read_bytes()
    row = ev._read_ledger(ledger)[0]
    assert row["schema"] == "AlphaRdagentFactorTrialV2"
    assert row["code_sha256"] == ev.sha(code_path.read_bytes())
    assert row["status"] == "IMPORTED" and row["stage"] == "none"
    assert row["p"] == row["q"] == 1.0
    assert row["screen"] == row["replay"] == {}
    assert row["panel_sha256"] == "0" * 64
    assert row["instruments"] == list(ev.LOOP_UNIVERSE)
    assert row["imported"] == {
        k: item[k] for k in ("evaluated_by", "result_summary", "source", "code_path")
    }
    assert row["authority"] == ev.AUTHORITY
    assert row["exposure"] == {
        "previously_exposed": None,
        "worst_status": "no exposure log",
        "matches": [],
    }
    run = tmp_path / "repeat"
    req = fixture(run)
    with (
        patch.object(judge, "screen", side_effect=AssertionError("import screened")),
        patch.object(ev, "replay", side_effect=AssertionError("import replayed")),
    ):
        result = evaluate(run, req, ledger)
    assert ledger.read_bytes().startswith(before)
    assert result["inputs"]["exposure_log_sha256"] is None
    assert result["factors"][0]["status"] == "REPEAT"
    assert result["factors"][0]["first_trial"]["status"] == "IMPORTED"
    assert result["family_size"] == 1
    assert result["replayed_trials"] == 0
    assert not result["decision"]
    del row["imported"]
    ledger.write_bytes(ev.canonical(row))
    with pytest.raises(DataError):
        ev._read_ledger(ledger)


@pytest.mark.parametrize("defect", ["existing", "batch_duplicate", "missing", "invalid_metadata"])
def test_import_refuses_whole_batch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, defect: str
) -> None:
    ledger, source = tmp_path / "trials.jsonl", tmp_path / "import.json"
    _, item = historical(tmp_path)
    source.write_text(json.dumps([item]))
    import_command(ledger, source, monkeypatch)
    before = ledger.read_bytes()
    different = tmp_path / "different.py"
    different.write_bytes(b"different")
    new = {**item, "code_path": str(different)}
    bad = {**new}
    if defect == "existing":
        bad = item
    elif defect == "missing":
        bad["code_path"] = str(tmp_path / "missing.py")
    elif defect == "invalid_metadata":
        bad["evaluated_by"] = ""
    source.write_text(json.dumps([new, bad]))
    with pytest.raises(DataError):
        import_command(ledger, source, monkeypatch)
    assert ledger.read_bytes() == before


def test_imported_rows_count_in_bh_family(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    ledger, source = tmp_path / "trials.jsonl", tmp_path / "import.json"
    _, item = historical(tmp_path, code=b"older code")
    other_path = tmp_path / "other.py"
    other_path.write_bytes(b"other code")
    source.write_text(json.dumps([item, {**item, "code_path": str(other_path)}]))
    import_command(ledger, source, monkeypatch)
    imported = ev._read_ledger(ledger)
    assert [r["trial_index"] for r in imported] == [1, 2]
    assert all(r["family_size"] == r["total_trials"] == 2 for r in imported)
    before = ledger.read_bytes()
    run = tmp_path / "new-run"
    req = fixture(run)
    with (
        patch.object(
            judge,
            "screen",
            side_effect=[
                {"status": "OK", "p": 1.0, "direction": 1},
                {"status": "OK", "p": 0.05, "direction": 1},
                {"status": "OK", "p": 1.0, "direction": 1},
            ],
        ),
        patch.object(ev, "replay", side_effect=AssertionError("BH should prevent replay")),
    ):
        result = evaluate(run, req, ledger)
    assert result["family_size"] == 3
    assert result["distinct_factors"] == result["total_trials"] == 3
    assert result["factors"][0]["q"] == pytest.approx(0.15)
    assert result["factors"][0]["status"] == "SCREEN_FAIL"
    assert ledger.read_bytes().startswith(before)


def test_import_refuses_a_different_reserved_start(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The exposure label is computed from reserved_start, so it must be the ledger's own.
    _, item = historical(tmp_path)
    item["windows"] = {**ev.WINDOWS, "reserved_start": "2030-01-01"}
    source, ledger = tmp_path / "items.json", tmp_path / "trials.jsonl"
    source.write_text(json.dumps([item]))
    with pytest.raises(DataError):
        import_command(ledger, source, monkeypatch)
    assert not ledger.exists() or not ledger.read_bytes()


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("range_fraction_7d", "Range fraction over 7 days"),
        ("VOL_ret_21d", "Volatility return over 21 days"),
        (
            "vwap_ic_xs_ma_sma_std_atr_pct_zscore",
            "VWAP distance information coefficient cross-sectional "
            "moving average moving average standard deviation average true range percent z-score",
        ),
        ("7d_ret", "7d return"),
    ],
)
def test_plain_names(name: str, expected: str) -> None:
    assert ev.plain_name(name) == expected


def trial_series(run: Path) -> tuple[Path, dict[str, Any]]:
    folder = run / "evaluations/iter-0/series"
    return folder, json.loads((folder / "series.json").read_bytes())


def test_series_reproduce_metrics_hashes_and_are_byte_identical(tmp_path: Path) -> None:
    run = tmp_path / "run"
    result = evaluate(run, fixture(run), tmp_path / "ledger.jsonl")
    factor = result["factors"][0]
    digest = factor["code_sha256"]
    folder, manifest = trial_series(run)
    assert manifest["schema"] == "AlphaRdagentTrialSeriesV1"
    assert manifest["factors"][0]["code_sha256"] == digest
    assert {f["name"] for f in manifest["factors"][0]["files"]} == {
        f"{digest}.{kind}.parquet"
        for kind in ("screen", "buckets", "buckets_daily", "replay", "holdings")
    }
    for item in manifest["factors"][0]["files"]:
        assert ev.sha((folder / item["name"]).read_bytes()) == item["sha256"]
    expected_hash = ev.sha((folder / "series.json").read_bytes())
    assert result["inputs"]["series_sha256"] == expected_hash
    assert factor["evidence"] == {
        "series_manifest": "evaluations/iter-0/series/series.json",
        "sha256": expected_hash,
    }
    ledger_row = json.loads((tmp_path / "ledger.jsonl").read_bytes())
    assert ledger_row["evidence"] == factor["evidence"]
    assert ledger_row["plain_name"] == "Factor"
    screen = pl.read_parquet(folder / f"{digest}.screen.parquet")
    assert screen.columns == ["clock", "date", "rank_ic", "names"]
    assert set(screen["clock"].unique()) == set(ev.CLOCKS)
    assert screen["names"].to_list() == [15] * screen.height
    buckets = pl.read_parquet(folder / f"{digest}.buckets.parquet")
    daily = pl.read_parquet(folder / f"{digest}.buckets_daily.parquet")
    assert buckets.columns == ["clock", "bucket", "mean_outcome", "observations"]
    assert daily.columns == ["clock", "date", "bucket", "mean_outcome"]
    replay = pl.read_parquet(folder / f"{digest}.replay.parquet")
    assert replay.columns == [
        "clock",
        "target_ts",
        "exit_ts",
        "gross_return",
        "net_return",
        "benchmark_return",
        "excess_return",
        "turnover",
        "fees",
        "slippage_cost",
    ]
    holdings = pl.read_parquet(folder / f"{digest}.holdings.parquet")
    assert holdings.columns == ["clock", "date", "instrument", "target_weight", "score"]
    for clock, trial in factor["clocks"].items():
        scored = screen.filter(pl.col("clock") == clock)
        assert scored["rank_ic"].mean() == pytest.approx(trial["screen"]["mean_ic"])
        clock_buckets = buckets.filter(pl.col("clock") == clock)
        clock_days = daily.filter(pl.col("clock") == clock)
        assert clock_buckets["observations"].sum() == scored.height * 15
        for row in clock_buckets.iter_rows(named=True):
            assert clock_days.filter(pl.col("bucket") == row["bucket"])[
                "mean_outcome"
            ].mean() == pytest.approx(row["mean_outcome"])
        periods = replay.filter(pl.col("clock") == clock)
        targets = holdings.filter(pl.col("clock") == clock)
        if trial["replay"]:
            mean_excess = periods["excess_return"].mean()
            assert isinstance(mean_excess, float)
            assert mean_excess * 365 == pytest.approx(trial["replay"]["net"]["annualized_return"])
            assert periods["turnover"].mean() == pytest.approx(trial["replay"]["mean_turnover"])
            assert periods["excess_return"].to_numpy() == pytest.approx(
                (periods["net_return"] - periods["benchmark_return"]).to_numpy()
            )
            assert targets.group_by("date").agg(pl.col("target_weight").sum())[
                "target_weight"
            ].to_numpy() == pytest.approx(np.ones(1088))
        else:
            assert periods.is_empty() and targets.is_empty()
    # Preserve the prior direct reconstruction of daily top-third outcomes.
    panel = pl.read_parquet(run / "panel/panel.parquet")
    outcomes = (
        panel.select("date", "instrument", "open")
        .sort(["instrument", "date"])
        .with_columns(
            (
                pl.col("open").shift(-2).over("instrument")
                / pl.col("open").shift(-1).over("instrument")
                - 1
            ).alias("outcome")
        )
    )
    top = (
        pl.read_parquet(run / "factors.parquet")
        .sort(["date", "factor", "instrument"], descending=[False, True, False])
        .group_by("date", maintain_order=True)
        .head(5)
        .filter(pl.col("date").is_in(screen.filter(pl.col("clock") == "daily")["date"].implode()))
        .join(outcomes, on=["date", "instrument"])
        .group_by("date")
        .agg(pl.col("outcome").mean())
        .sort("date")
    )
    assert top["outcome"].to_numpy() == pytest.approx(
        daily.filter((pl.col("clock") == "daily") & (pl.col("bucket") == 3))[
            "mean_outcome"
        ].to_numpy()
    )
    fresh = tmp_path / "fresh" / "run"
    evaluate(fresh, fixture(fresh), tmp_path / "fresh-ledger.jsonl")
    other_folder, _ = trial_series(fresh)
    assert {p.name: p.read_bytes() for p in folder.iterdir()} == {
        p.name: p.read_bytes() for p in other_folder.iterdir()
    }


def test_series_failure_changes_no_metrics_or_decisions(
    tmp_path: Path, recorded_time: None
) -> None:
    run = tmp_path / "run"
    req = fixture(run)
    good = evaluate(run, req, tmp_path / "good.jsonl")
    with patch.object(ev, "_write_series", side_effect=OSError("evidence disk unavailable")):
        failed = ev.evaluate(run, req, run / "other.json", tmp_path / "failed.jsonl")
    assert "evidence disk unavailable" in failed["series_note"]
    good["inputs"].pop("series_sha256")
    for row in good["factors"]:
        row.pop("evidence", None)
    failed.pop("series_note")
    assert ev.canonical(good) == ev.canonical(failed)


def test_degenerate_and_unscreened_factors_have_no_series(tmp_path: Path) -> None:
    run = tmp_path / "run"
    req = fixture(run)
    frame = pl.read_parquet(run / "factors.parquet").with_columns(pl.lit(1.0).alias("factor"))
    frame.write_parquet(run / "factors.parquet")
    result = evaluate(run, req, tmp_path / "ledger.jsonl")
    folder, manifest = trial_series(run)
    assert manifest["factors"] == []
    assert [p.name for p in folder.iterdir()] == ["series.json"]
    assert "evidence" not in result["factors"][0]


def test_same_request_repeat_has_no_evidence(tmp_path: Path) -> None:
    run = tmp_path / "run"
    req = fixture(run)
    request = json.loads(req.read_bytes())
    request["factors"].append({**request["factors"][0], "name": "repeat"})
    req.write_text(json.dumps(request))
    record = evaluate(run, req, tmp_path / "ledger.jsonl")
    assert record["factors"][1]["status"] == "REPEAT"
    assert "evidence" not in record["factors"][1]
    _, manifest = trial_series(run)
    assert len(manifest["factors"]) == 1


def test_screen_error_retains_computed_daily_ic_only(tmp_path: Path) -> None:
    run = tmp_path / "run"
    req = fixture(run)
    with patch.object(judge, "block_bootstrap_ci", side_effect=DataError("inference failed")):
        record = evaluate(run, req, tmp_path / "ledger.jsonl")
    factor = record["factors"][0]
    assert factor["status"] == "ERROR"
    folder, manifest = trial_series(run)
    files = manifest["factors"][0]["files"]
    assert [f["name"] for f in files] == [f"{factor['code_sha256']}.screen.parquet"]
    assert pl.read_parquet(folder / files[0]["name"])["rank_ic"].null_count() == 0


def test_partial_series_write_failure_is_not_a_scoring_failure(tmp_path: Path) -> None:
    run = tmp_path / "run"
    req = fixture(run)
    original = ev._series_file

    def fail_buckets(path: Path, payload: bytes) -> None:
        if path.name.endswith(".buckets.parquet"):
            raise OSError("bucket write failed")
        original(path, payload)

    with patch.object(ev, "_series_file", fail_buckets):
        record = evaluate(run, req, tmp_path / "ledger.jsonl")
    factor = record["factors"][0]
    assert factor["status"] == "CANDIDATE" and record["decision"] is True
    assert "bucket write failed" in factor["series_note"]
    folder, manifest = trial_series(run)
    assert [f["name"] for f in manifest["factors"][0]["files"]] == [
        f"{factor['code_sha256']}.screen.parquet"
    ]
    assert len(list(folder.iterdir())) == 2


@pytest.mark.parametrize("direction", [1, -1])
def test_bucket_three_matches_replay_ties_and_direction(tmp_path: Path, direction: int) -> None:
    run = tmp_path / "run"
    req = fixture(run)
    request, panel, values, _ = ev._inputs(run, req)
    days = [date(2021, 1, 1) + timedelta(days=n) for n in range(4)]
    symbols = sorted(panel["instrument"].unique().to_list())
    signal = np.zeros((len(days), len(symbols)))
    signal[:, :7] = 1
    data: dict[str, Any] = {}
    ev.replay(panel, signal, days, direction, series=data)
    outcomes = ev.matrix(panel, "open", [days[0] + timedelta(days=n) for n in range(6)], symbols)
    outcomes = outcomes[2:] / outcomes[1:-1] - 1
    buckets, daily = ev._bucket_frames(signal, outcomes, days, symbols, direction)
    assert buckets["observations"].sum() == len(days) * len(symbols)
    held = {
        t.symbol: t.target_weight
        for t in data["targets"]
        if t.origin_ts.date() == days[0] and t.target_weight > 0
    }
    # Five slots shared equally by the whole tied group: 7 names at 1/7, or 8 names at 1/8.
    tied = symbols[:7] if direction == 1 else symbols[7:]
    assert held == pytest.approx(dict.fromkeys(tied, 1 / len(tied)))
    for i, day in enumerate(days):
        weights = np.array([t.target_weight for t in data["targets"] if t.origin_ts.date() == day])
        assert daily.filter((pl.col("date") == day) & (pl.col("bucket") == 3))["mean_outcome"][
            0
        ] == pytest.approx(float(weights @ outcomes[i]))


def test_bucket_table_keeps_empty_days_and_null_means() -> None:
    days = [date(2021, 1, 1), date(2021, 1, 2)]
    scores = np.tile(np.arange(6), (2, 1)).astype(float)
    outcomes = np.ones((2, 6))
    outcomes[1] = np.nan
    summary, daily = ev._bucket_frames(scores, outcomes, days, list("ABCDEF"), 1)
    assert daily.height == 6
    assert daily.filter(pl.col("date") == days[1])["mean_outcome"].to_list() == [None] * 3
    assert summary["observations"].to_list() == [2, 2, 2]


def rule_row(index: int = 1) -> dict[str, Any]:
    return {
        "schema": "AlphaRuleTrialV1",
        "trial_index": index,
        "name": "own_trend_20d_SPY",
        "plain_name": "Hold SPY only while its 20-day trend is up",
        "code_sha256": "f" * 64,
        "run_id": "human",
        "iteration": 0,
        "panel_sha256": "a" * 64,
        "windows": {
            "history_start": "2020-01-01",
            "scored_start": "2021-01-01",
            "scored_end": "2023-12-31",
            "exploration_end": "2023-12-31",
            "reserved_start": "2024-01-01",
        },
        "family_id": "human-family",
        "family_size": 1,
        "total_trials": index,
        "stage": "replay",
        "status": "SUPPORT",
        "p": 0.001,
        "q": 0.001,
        "screen": {},
        "replay": {},
        "instruments": ["SPY"],
        "exposure": {"previously_exposed": None, "worst_status": "no exposure log", "matches": []},
        "evidence": {"trial": "trials/SPY-N20/trial.json", "sha256": "b" * 64},
        "label": ev.LABEL,
        "survivorship": "synthetic",
        "authority": ev.AUTHORITY,
        "warnings": [],
    }


def test_rule_ledger_schema_and_statuses(tmp_path: Path) -> None:
    ledger = tmp_path / "ledger"
    row = rule_row()
    ledger.write_bytes(ev.canonical(row))
    assert ev._read_ledger(ledger) == [row]
    for key in ("family_id", "plain_name", "evidence", "warnings", "instruments", "exposure"):
        broken = {k: v for k, v in row.items() if k != key}
        ledger.write_bytes(ev.canonical(broken))
        with pytest.raises(DataError):
            ev._read_ledger(ledger)
    for schema, status in (
        ("AlphaRuleTrialV1", "CANDIDATE"),
        ("AlphaRdagentFactorTrialV1", "SUPPORT"),
    ):
        ledger.write_bytes(ev.canonical({**row, "schema": schema, "status": status}))
        with pytest.raises(DataError):
            ev._read_ledger(ledger)


def test_rule_family_excluded_from_factor_statistics_and_repeats(tmp_path: Path) -> None:
    run = tmp_path / "run"
    req = fixture(run)
    clean = evaluate(run, req, tmp_path / "clean")
    ledger = tmp_path / "mixed"
    # A hash collision must not make this RD-Agent factor a repeat of a human rule.
    row = {**rule_row(), "code_sha256": json.loads(req.read_bytes())["factors"][0]["code_sha256"]}
    ledger.write_bytes(ev.canonical(row))
    mixed = ev.evaluate(run, req, run / "mixed.json", ledger)
    assert mixed["qvalues"] == clean["qvalues"]
    assert mixed["family_size"] == clean["family_size"]
    assert mixed["factors"][0]["replay"] == clean["factors"][0]["replay"]
    assert mixed["factors"][0]["status"] == clean["factors"][0]["status"]
    assert mixed["ledger_trials_all_families"] == 2
    assert mixed["factors"][0]["ledger_trials_all_families"] == 2
    assert mixed["factors"][0]["trial_index"] == 2
    assert "Ledger rows, all families (rules, repeats too): 2" in mixed["feedback_text"]
    assert len(ev._read_ledger(ledger)) == 2


@pytest.mark.parametrize("reason", ["critic_rejected", "cap_reached", "exception", "bad_output"])
def test_failure_reason_reaches_ledger_and_proposer(tmp_path: Path, reason: str) -> None:
    run = tmp_path / "run"
    request_path = fixture(run)
    request = json.loads(request_path.read_text())
    request["factors"][0].update(
        status="FAILED", failure_reason=reason, failure_detail="first error line"
    )
    request_path.write_text(json.dumps(request))
    ledger = tmp_path / "ledger.jsonl"
    result = ev.evaluate(run, request_path, run / "result.json", ledger)
    row = json.loads(ledger.read_text())
    assert row["failure_reason"] == reason
    assert reason in result["feedback_text"]
    assert "first error line" in result["feedback_text"]


def test_evaluation_uses_receipt_identity_and_records_utc(tmp_path: Path) -> None:
    run = tmp_path / "different-folder-name"
    request_path = fixture(run)
    (run / "run-identity.json").write_text(json.dumps({"run_id": "receipt-id"}))
    request = json.loads(request_path.read_text())
    request["factors"][0].update(status="FAILED", failure_reason="critic_rejected")
    request_path.write_text(json.dumps(request))
    result = ev.evaluate(run, request_path, run / "result.json", tmp_path / "ledger")
    row = result["factors"][0]
    assert row["run_id"] == "receipt-id"
    assert datetime.fromisoformat(row["recorded_at"]).tzinfo == UTC


def test_proposer_counts_have_plain_labels(tmp_path: Path) -> None:
    run = tmp_path / "run"
    request_path = fixture(run)
    request: dict[str, Any] = json.loads(request_path.read_text())
    request["factors"][0].update(status="FAILED", failure_reason="critic_rejected")
    request_path.write_text(json.dumps(request))
    result = ev.evaluate(run, request_path, run / "result.json", tmp_path / "ledger")
    assert (
        "looks so far across all ideas: 1 (sets the screen cutoff); "
        "primary clocks now; legacy clocks and unreadable rows included;"
    ) in result["feedback_text"]
    assert "Ledger rows, all families (rules, repeats too): 1" in result["feedback_text"]
    assert "ledger_trials_all_families:" not in result["feedback_text"]


@pytest.mark.parametrize("status", ["LOOKAHEAD", "UNSTABLE"])
def test_invalid_trials_keep_counts_reason_and_have_no_lead(tmp_path: Path, status: str) -> None:
    run = tmp_path / "run"
    path = fixture(run)
    request = json.loads(path.read_text())
    request["factors"][0].update(
        status=status,
        lookahead={
            "status": status,
            "first_mismatch": {
                "cut": "2021-03-31",
                "date": "2021-03-01",
                "instrument": "C0USDT",
                "absolute_difference": 0.25,
                "reason": "value changed",
            },
        },
    )
    path.write_text(json.dumps(request))
    ledger = tmp_path / "ledger"
    result = ev.evaluate(run, path, run / "result.json", ledger)
    assert result["lead_factor"] is None
    assert result["family_size"] == 1 and result["total_trials"] == 1
    snapshot = read_ledgers([LedgerSource("rdagent", str(ledger))])
    assert not snapshot.unknown
    record = snapshot.records[0]
    assert record.outcome == "invalid"
    assert record.reason and "2021-03-01" in record.reason and "0.25" in record.reason
    assert "C0USDT" in result["feedback_text"]
    if status == "UNSTABLE":
        assert "different answers on the same data" in result["feedback_text"]
    assert trials_for_deflation(snapshot, "rdagent-factors")["all_trials"] == 1
    assert ev._read_ledger(ledger)[0]["status"] == status
    output = CliRunner().invoke(ledger_app, ["list", "--rdagent-ledger", str(ledger)])
    assert output.exit_code == 0 and "0.25" in output.output


def test_plain_factor_stems() -> None:
    from alpha_cli.rdagent_factor_eval import plain_name

    assert (
        plain_name("ltr_mdd_vwap_60d")
        == "Long-term reversal max drawdown VWAP distance over 60 days"
    )


def test_feedback_records_failed_screen_even_when_spread_passed(tmp_path: Path) -> None:
    from alpha_cli._rdagent_clocks import clock_feedback

    run = tmp_path / "noise"
    req = fixture(run, noise=True)
    result = evaluate(run, req, tmp_path / "ledger")
    row = json.loads((tmp_path / "ledger").read_text())
    assert row["status"] == "SCREEN_FAIL"
    row["clocks"][row["lead_clock"]]["spread"] = {"status": "PASS"}
    row["screen_cutoff"] = 0.000123456789
    text = clock_feedback(row)
    assert "failed: rank screen" in text
    assert "spread status: PASS" in text
    assert "screen cutoff: 0.000123456789" in text
    assert f"screen cutoff: {result['factors'][0]['screen_cutoff']}" in result["feedback_text"]


def test_factor_ledger_stores_the_judges_family_and_critic_status(tmp_path: Path) -> None:
    run = tmp_path / "mix"
    req = fixture(run)
    request = json.loads(req.read_text())
    request["factors"][0].update(
        name="ml_mix",
        variables={"funding_7d": "", "drawdown_60d": ""},
        status="FAILED",
        family="drawdown; futures funding",
        critic_status="skipped",
        critic_reason="earlier provider timeout in this round",
    )
    req.write_text(json.dumps(request))
    result = evaluate(run, req, tmp_path / "ledger")
    row = json.loads((tmp_path / "ledger").read_text())
    assert row == result["factors"][0]
    assert row["family"] == "drawdown; futures funding"
    assert (row["critic_status"], row["critic_reason"]) == (
        "skipped",
        "earlier provider timeout in this round",
    )
    assert "Code critic skipped: earlier provider timeout in this round." in result["feedback_text"]
