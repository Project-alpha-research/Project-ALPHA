"""A quick screen counts its tries in the one trial ledger (M84)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from alpha_cli import _hypothesis_scan as scan
from alpha_cli.spine import diagnose
from alpha_cli.spine.ledger import read_trials
from alpha_cli.spine.trial_reader import spine_snapshot
from tests.fixtures.hypothesis_scan_fixtures import frozen_equities

HORIZONS = list(range(1, 41))


def request(horizons: list[int] | None = None) -> dict[str, object]:
    return {
        "lane": "equity",
        "symbols": list("ABCDE"),
        "universe": None,
        "snapshot": "frozen",
        "as_of": "2020-04-09",
        "signals": ["rev_1m"],
        "horizons": horizons or [1, 5],
        "min_names": 5,
        "quantiles": 5,
        "cost_bps": 2.0,
        "category": "linear",
    }


def screen_rows(home: Path) -> list[dict[str, Any]]:
    return [r for r in read_trials(home) if r["kind"] == "screen_trial"]


def returns() -> np.ndarray:
    z = np.random.default_rng(7).standard_normal(300)
    scaled: np.ndarray = 0.0005 + 0.01 * (z - z.mean()) / z.std(ddof=1)
    return scaled


def test_each_hypothesis_on_each_asset_appends_one_trial(tmp_path: Path) -> None:
    frozen_equities(tmp_path)
    result = scan.run_hypotheses(tmp_path, request())
    rows = screen_rows(tmp_path)
    assert len(rows) == 2 * 5
    assert {r["symbol"] for r in rows} == set("ABCDE")
    assert all(r["spec_sha256"] and r["idea_id"] and r["first_ts"] and r["last_ts"] for r in rows)
    assert len({r["spec_sha256"] for r in rows}) == 2
    assert result["counted"]["tries_added"] == 10
    assert result["counted"]["hypotheses"] == 2


def test_same_screen_on_same_data_counts_once(tmp_path: Path) -> None:
    frozen_equities(tmp_path)
    scan.run_hypotheses(tmp_path, request())
    again = scan.run_hypotheses(tmp_path, request())
    assert again["counted"]["tries_added"] == 0
    snapshot = spine_snapshot(tmp_path)
    from alpha_cli.spine.deflation import same_asset_tests

    assert same_asset_tests(snapshot, "A") == (2, 2, False)


def test_replay_adds_no_trials(tmp_path: Path) -> None:
    frozen_equities(tmp_path)
    first = scan.run_hypotheses(tmp_path, request())
    before = read_trials(tmp_path)
    replay = scan.replay_hypotheses(tmp_path, first["scan_id"])
    assert read_trials(tmp_path) == before
    assert replay["counted"]["tries_added"] == 0
    assert first["result_digest"] == replay["result_digest"]


def test_test_reading_states_m_of_at_least_40_after_a_screen_of_40(tmp_path: Path) -> None:
    frozen_equities(tmp_path)
    scan.run_hypotheses(tmp_path, request(HORIZONS))
    result = diagnose.trials(
        tmp_path, "A", returns(), 252, [], "ma_cross", snapshot=spine_snapshot(tmp_path)
    )
    assert result["family"]["same_asset_tests"] == 40
    assert result["family"]["n_trials_used"] >= 40
    alone = diagnose.trials(tmp_path / "empty", "A", returns(), 252, [], "ma_cross", snapshot=None)
    assert alone["family"]["n_trials_used"] == 1
    assert result["dsr"] < alone["dsr"]


def test_failed_screen_records_nothing(tmp_path: Path) -> None:
    frozen_equities(tmp_path)
    with pytest.raises(Exception, match="snapshot"):
        scan.run_hypotheses(tmp_path, {**request(), "snapshot": None})
    assert screen_rows(tmp_path) == []


def test_counted_words_are_plain_and_not_a_verdict(tmp_path: Path) -> None:
    frozen_equities(tmp_path)
    counted = scan.run_hypotheses(tmp_path, request())["counted"]
    text = counted["sentence"].lower()
    assert "10 tries" in text and "first look, not a test" in text
    for word in ("pass", "fail", "best", "winner"):
        assert word not in text
    assert json.dumps(counted)
