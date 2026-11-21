"""Golden pins for the three old rule kinds: identity bytes that no later change may move.

Written against the behaviour before owner rules were added. Run ids are not pinned: they hash
the code, so every code change moves them. What stays fixed is the canonical spec, its hash, the
test key, the identity payload (with fingerprints replaced by fixed values) and the ledger keys.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from alpha_cli import _gauntlet, _identity, _runner
from alpha_cli.spine import run
from alpha_cli.spine.deflation import spine_test_key
from alpha_cli.spine.spec import IdeaSpec, load_spec
from alpha_core import Bar, DataError
from alpha_data.store import ParquetStore
from tests.fixtures.cli_fixtures import seed_store

KINDS: dict[str, tuple[list[str], str, str]] = {
    "ma_cross": (
        ["fast=5", "slow=20"],
        '{"assets":["SPY"],"costs":{"fee_bps":1.0,"slippage_bps":2.0},"idea":"",'
        '"name":"ma_cross-5-20","rule":{"fast":5,"kind":"ma_cross","slow":20}}',
        "2668857e7aa7c8b17bcb3ece3f17cdfbc2f6e80fc361721a689a5b4bdf9fbb8b",
    ),
    "breakout": (
        ["window=20"],
        '{"assets":["SPY"],"costs":{"fee_bps":1.0,"slippage_bps":2.0},"idea":"",'
        '"name":"breakout-20","rule":{"kind":"breakout","window":20}}',
        "cf609eb87036468a0aa9d16e732f54c84c880b72f3cc500df13153f3417b8d1e",
    ),
    "tsmom": (
        ["lookback=20", "skip=5"],
        '{"assets":["SPY"],"costs":{"fee_bps":1.0,"slippage_bps":2.0},"idea":"",'
        '"name":"tsmom-20-5","rule":{"kind":"tsmom","lookback":20,"skip":5}}',
        "8e8a4a02d0840279a62f2856f50ceaee1d22e56c0e3887dffcff199c87cf16b9",
    ),
}
FIXED = "f" * 64
LEDGER_KEYS = [
    "aim_relation",
    "benchmark_sharpe",
    "costs",
    "data_health",
    "deflation",
    "dsr",
    "evidence",
    "first_ts",
    "flags",
    "idea",
    "idea_id",
    "kind",
    "labels",
    "last_ts",
    "n_bars",
    "name",
    "oos_sharpe",
    "params",
    "periods_per_year",
    "periods_per_year_basis",
    "recorded_at",
    "resized_entries",
    "rule",
    "run_id",
    "schema",
    "sentence",
    "source",
    "spec_sha256",
    "store",
    "symbol",
    "test_id",
    "total_trials",
    "trial_index",
    "variants_evaluated",
    "verdict",
]

ERROR_KEYS = [key for key in LEDGER_KEYS if key not in {"deflation", "resized_entries", "sentence"}]


def _idea(kind: str) -> IdeaSpec:
    return load_spec(None, rule=kind, param=KINDS[kind][0], asset=["SPY"])


@pytest.mark.parametrize("kind", sorted(KINDS))
def test_canonical_bytes_and_hash_are_pinned(kind: str) -> None:
    _, canonical, digest = KINDS[kind]
    idea = _idea(kind)
    assert idea.canonical() == canonical
    assert idea.spec_sha256 == digest


def test_test_key_is_pinned() -> None:
    key = spine_test_key(
        KINDS["ma_cross"][2],
        "SPY",
        "2020-01-01T00:00:00+00:00",
        "2023-12-29T00:00:00+00:00",
        252,
        store="home",
        data_id="d" * 16,
    )
    assert key == (
        KINDS["ma_cross"][2],
        ("SPY",),
        "2020-01-01T00:00:00+00:00",
        "2023-12-29T00:00:00+00:00",
        "1D",
        "home",
        "d" * 16,
    )


def _store(home: Path, bars: int) -> None:
    seed_store(home, symbol="SPY", n=bars)
    ParquetStore(home / "store").write_provenance(
        "SPY", source="alpaca", adapter_version="1", parser_version="1"
    )


def _payload(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, kind: str) -> dict[str, Any]:
    """The identity payload ``prepare_asset`` hands to ``run_identity_for``."""
    _store(tmp_path, 400)
    seen: dict[str, Any] = {}

    def capture(
        payload: dict[str, Any], *, source_fingerprint: str | None = None, **_: object
    ) -> _identity.RunIdentity:
        seen["payload"] = dict(payload)
        seen["source_fingerprint"] = source_fingerprint
        return _identity.RunIdentity("r" * 16, FIXED, FIXED, FIXED, None)

    monkeypatch.setattr(_runner, "run_identity_for", capture)
    monkeypatch.setattr(_runner, "source_fingerprint", lambda *a, **k: FIXED)
    result: dict[str, Any] = {"labels": ["all-in"]}
    run.prepare_asset(
        _idea(kind),
        "SPY",
        tmp_path,
        _gauntlet.GauntletParams(seed=7),
        result,
        report_time=datetime(2024, 1, 4, tzinfo=UTC),
    )
    return {**seen["payload"], "_source_fingerprint": seen["source_fingerprint"]}


COMMON = {
    "account_type": "CASH",
    "allow_short": False,
    "anchored": True,
    "command": "validate",
    "confidence": 0.95,
    "cpcv_groups": 6,
    "cpcv_test_groups": 2,
    "dsr_threshold": 0.95,
    "embargo": 5,
    "fee_bps": 1.0,
    "forecast_cache": None,
    "halt_drawdown": None,
    "labels": ["all-in", "data-health-unchecked", "short-history"],
    "max_leverage": 1.0,
    "mean_block": 5.0,
    "n_resamples": 2000,
    "null_model": "bootstrap",
    "periods_per_year": 365,
    "rebalance_every": 1,
    "research_cutoff": None,
    "rules_spec": None,
    "seed": 7,
    "size_on_equity": False,
    "sizing": "all_in",
    "slippage_bps": 2.0,
    "snapshot_id": None,
    "source": "alpaca",
    "starting_cash": 1000000.0,
    "store": "home",
    "symbol": "SPY",
    "target_vol": 0.15,
    "threshold": 0.95,
    "tier1_divergence_tol": 0.25,
    "tier1_paths": 1000,
    "tier2_mode": "replay",
    "tier2_paths": 64,
    "tier3_paths": 64,
    "vol_window": 63,
    "_source_fingerprint": FIXED,
}
PER_KIND: dict[str, dict[str, Any]] = {
    "ma_cross": {
        "lookback": 252,
        "skip": 21,
        "strategy_name": "ma_crossover",
        "strategy_params": [["fast", 5.0], ["slow", 20.0]],
        "train_size": 20,
        "test_size": 187,
    },
    "breakout": {
        "lookback": 252,
        "skip": 21,
        "strategy_name": "breakout",
        "strategy_params": [["window", 20.0]],
        "train_size": 21,
        "test_size": 186,
    },
    "tsmom": {
        "lookback": 20,
        "skip": 5,
        "strategy_name": "ts_momentum",
        "strategy_params": [],
        "train_size": 26,
        "test_size": 184,
    },
}


@pytest.mark.parametrize("kind", sorted(KINDS))
def test_identity_payload_is_pinned(
    kind: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    payload = _payload(tmp_path, monkeypatch, kind)
    # The tuple pairs of strategy_params travel as lists in JSON; compare in that form.
    payload = json.loads(json.dumps(payload, default=str))
    assert payload.pop("spec_sha256") == KINDS[kind][2]
    assert payload.pop("data_health")["verdict"] == "unchecked"
    assert payload == {**COMMON, **PER_KIND[kind]}


def test_ledger_row_keys_and_rule_fields_are_pinned(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _store(tmp_path, 400)
    idea = _idea("ma_cross")
    out = run.run_idea(idea, home=tmp_path, quick=True)
    rows = [
        json.loads(line) for line in (tmp_path / "ledger/trials.jsonl").read_text().splitlines()
    ]
    assert len(rows) == out["trials_total"] == 1
    row = rows[0]
    assert sorted(row) == LEDGER_KEYS
    assert (row["kind"], row["rule"], row["params"]) == (
        "rule_test",
        "ma_cross",
        {"fast": 5, "slow": 20},
    )
    assert row["spec_sha256"] == KINDS["ma_cross"][2]
    assert row["name"] == "ma_cross-5-20"


def test_error_row_keys_are_pinned(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _store(tmp_path, 100)

    def fail(
        bars: Sequence[Bar], spec: _runner.RunSpec, knobs: _gauntlet.GauntletParams, **_: object
    ) -> None:
        raise DataError("injected")

    monkeypatch.setattr(_gauntlet, "run_gauntlet", fail)
    for kind in sorted(KINDS):
        run.run_idea(_idea(kind), home=tmp_path, quick=True)
    rows = [
        json.loads(line) for line in (tmp_path / "ledger/trials.jsonl").read_text().splitlines()
    ]
    assert [row["rule"] for row in rows] == sorted(KINDS)
    assert sorted(rows[0]) == ERROR_KEYS
