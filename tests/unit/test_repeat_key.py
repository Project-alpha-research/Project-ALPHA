"""A repeated test is recognised by what was tested (the test key), never by the code version."""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from alpha_cli import _runner
from alpha_cli.spine import diagnose
from alpha_cli.spine.deflation import spine_test_key
from alpha_cli.spine.ledger import append_trial, read_trials
from alpha_cli.spine.trial_reader import spine_snapshot
from alpha_cli.spine.trial_record import row_test_key

SPEC = "a" * 64
END = "2026-11-13T00:00:00+00:00"
START = "2016-01-04T00:00:00+00:00"


def rule_row(
    run_id: str,
    *,
    spec: str | None = SPEC,
    symbol: str = "SPY",
    end: str | None = END,
    sharpe: float | None = 0.5,
    labels: list[str] | None = None,
    store: str | None = "home",
    data_id: str | None = "d" * 64,
) -> dict[str, Any]:
    row: dict[str, Any] = dict(
        kind="rule_test",
        run_id=run_id,
        test_id="t-" + run_id,
        symbol=symbol,
        rule="ma_cross",
        verdict="B",
        labels=labels or [],
        oos_sharpe=sharpe,
        periods_per_year=252,
        store=store,
        idea_id=data_id,
    )
    if spec is not None:
        row.update(spec_sha256=spec, first_ts=START, last_ts=end)
    return row


def returns() -> np.ndarray:
    z = np.random.default_rng(7).standard_normal(300)
    scaled: np.ndarray = 0.0005 + 0.01 * (z - z.mean()) / z.std(ddof=1)
    return scaled


def count(home: Path, current: Any = None) -> dict[str, Any]:
    result = diagnose.trials(
        home,
        "SPY",
        returns(),
        252,
        [],
        "ma_cross",
        snapshot=spine_snapshot(home),
        current_test=current,
    )
    family: dict[str, Any] = result["family"]
    return family


def test_new_code_same_test_is_labelled_repeat(tmp_path: Path) -> None:
    first = append_trial(tmp_path, rule_row("run-code-1"))
    second = append_trial(tmp_path, rule_row("run-code-2"))
    assert "repeat" not in first["labels"]
    assert "repeat" in second["labels"]
    assert second["repeat_of"] == "run-code-1"
    assert "repeat_of" not in first


def test_other_spec_or_longer_window_is_a_new_test(tmp_path: Path) -> None:
    append_trial(tmp_path, rule_row("r1"))
    other_spec = append_trial(tmp_path, rule_row("r2", spec="b" * 64))
    longer = append_trial(tmp_path, rule_row("r3", end="2026-11-16T00:00:00+00:00"))
    other_asset = append_trial(tmp_path, rule_row("r4", symbol="QQQ"))
    for row in (other_spec, longer, other_asset):
        assert "repeat" not in row["labels"]
        assert "repeat_of" not in row


def test_rows_without_key_fields_each_count_as_their_own_test(tmp_path: Path) -> None:
    append_trial(tmp_path, rule_row("old-1", spec=None))
    second = append_trial(tmp_path, rule_row("old-2", spec=None))
    assert "repeat" not in second["labels"]
    assert row_test_key(rule_row("old-2", spec=None)) is None
    family = count(tmp_path)
    assert family["same_asset_tests"] == 2


def test_an_error_row_does_not_make_a_later_run_a_repeat(tmp_path: Path) -> None:
    append_trial(tmp_path, rule_row("e1", sharpe=None, labels=["error"]))
    later = append_trial(tmp_path, rule_row("e2"))
    assert "repeat" not in later["labels"]


def test_one_test_key_definition() -> None:
    row = rule_row("x")
    assert row_test_key(row) == spine_test_key(
        SPEC, "SPY", START, END, 252, store="home", data_id="d" * 64
    )
    assert row_test_key({**row, "kind": "tool:monte-carlo"}) is None


def test_distinct_count_ignores_repeats_and_labelled_repeats(tmp_path: Path) -> None:
    append_trial(tmp_path, rule_row("r1"))
    append_trial(tmp_path, rule_row("r2"))
    append_trial(tmp_path, rule_row("r3", spec="b" * 64))
    # An older row, written before this rule, repeats r1's test but carries no label.
    path = tmp_path / "ledger/trials.jsonl"
    rows = read_trials(tmp_path)
    rows.append(
        {**rule_row("r9"), "schema": "AlphaTrialV1", "trial_index": 4, "total_trials": 4}
        | {"recorded_at": "2026-11-16T00:00:00+00:00"}
    )
    path.write_text("".join(json.dumps(row, sort_keys=True) + "\n" for row in rows))
    family = count(tmp_path)
    assert family["same_asset_tests"] == 2
    assert family["same_asset_repeats"] == 2


def test_repeat_never_raises_the_trials_used(tmp_path: Path) -> None:
    current = spine_test_key(SPEC, "SPY", START, END, 252, store="home", data_id="d" * 64)
    append_trial(tmp_path, rule_row("r1"))
    once = count(tmp_path, current)
    append_trial(tmp_path, rule_row("r2"))
    append_trial(tmp_path, rule_row("r3"))
    after = count(tmp_path, current)
    assert after["n_trials_used"] == once["n_trials_used"]
    assert after["available_sharpes"] == once["available_sharpes"]
    assert after["same_asset_tests"] == once["same_asset_tests"]
    assert after["same_asset_repeats"] == 2
    assert math.isfinite(after["n_trials_used"])


def test_same_spec_run_after_a_code_change_is_a_repeat_and_adds_no_count(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from alpha_cli._artifacts import read_manifest, run_dir
    from alpha_cli.spine.run import run_idea
    from alpha_cli.spine.spec import load_spec
    from alpha_data.store import ParquetStore
    from tests.fixtures.cli_fixtures import seed_store

    seed_store(tmp_path, symbol="SPY", n=150)
    monkeypatch.setenv("ALPHA_DATA_DIR", str(tmp_path))
    ParquetStore(tmp_path / "store").write_provenance(
        "SPY", source="alpaca", adapter_version="1", parser_version="1"
    )
    idea = load_spec(None, rule="ma_cross", param=["fast=5", "slow=20"], asset=["SPY"])
    first = run_idea(idea, home=tmp_path, quick=True)["results"][0]
    assert first["error"] is None, first["error"]
    monkeypatch.setattr(_runner, "execution_fingerprint", lambda: "9" * 64)
    second = run_idea(idea, home=tmp_path, quick=True)["results"][0]
    assert second["error"] is None, second["error"]
    assert second["run_id"] != first["run_id"]
    assert "repeat" in second["labels"] and "repeat" not in first["labels"]
    used = []
    for result in (first, second):
        manifest = read_manifest(run_dir(tmp_path, result["run_id"]))
        used.append(manifest["dsr"]["n_trials"])
    assert used[0] == used[1]
    diagnostics = [
        json.loads((run_dir(tmp_path, r["run_id"]) / "diagnostics.json").read_text())
        for r in (first, second)
    ]
    families = [d["trials"]["family"] for d in diagnostics]
    assert families[1]["n_trials_used"] == families[0]["n_trials_used"]
    assert families[1]["available_sharpes"] == families[0]["available_sharpes"]
    rows = read_trials(tmp_path)
    assert rows[1]["repeat_of"] == first["run_id"]
    # The label lives in the ledger row only: the stored manifest is not edited, and
    # `alpha results show` still names the second run a repeat and the first not.
    from alpha_cli.results_cmds import _show

    second_manifest = read_manifest(run_dir(tmp_path, second["run_id"]))
    assert "repeat" not in second_manifest["spine"]["labels"]
    assert "repeat" in _show(tmp_path, second["run_id"])["labels"]
    assert "repeat" not in _show(tmp_path, first["run_id"])["labels"]


def test_other_store_or_revised_data_is_a_new_test(tmp_path: Path) -> None:
    """Same spec, symbol, window and bar size, but other prices: never merged into one test."""
    append_trial(tmp_path, rule_row("s1"))
    other_store = append_trial(tmp_path, rule_row("s2", store="vendor-b"))
    revised = append_trial(tmp_path, rule_row("s3", data_id="e" * 64))
    for row in (other_store, revised):
        assert "repeat" not in row["labels"]
        assert "repeat_of" not in row
    family = count(tmp_path)
    assert family["same_asset_tests"] == 3
    assert family["prior_trials"] == 3


def test_an_error_row_of_the_same_run_never_hides_the_real_run(tmp_path: Path) -> None:
    """A failed attempt and its successful re-run share a run id; the real run still counts."""
    append_trial(tmp_path, rule_row("same-run", sharpe=None, labels=["error"]))
    real = append_trial(tmp_path, rule_row("same-run"))
    assert "repeat" not in real["labels"]
    family = count(tmp_path)
    assert family["prior_trials"] == 1
    assert family["same_asset_tests"] == 1


def test_a_labelled_repeat_counts_when_its_first_row_has_no_sharpe(tmp_path: Path) -> None:
    append_trial(tmp_path, rule_row("n1", sharpe=None))
    later = append_trial(tmp_path, rule_row("n2"))
    assert later["repeat_of"] == "n1"
    family = count(tmp_path)
    assert family["prior_trials"] == 1
    assert family["same_asset_tests"] == 1


def test_counts_do_not_depend_on_ledger_order(tmp_path: Path) -> None:
    for run_id, spec in (("o1", SPEC), ("o2", SPEC), ("o3", "b" * 64), ("o4", SPEC)):
        append_trial(tmp_path, rule_row(run_id, spec=spec))
    forward = count(tmp_path)
    path = tmp_path / "ledger/trials.jsonl"
    lines = path.read_text().splitlines(keepends=True)
    path.write_text("".join(reversed(lines)))
    backward = count(tmp_path)
    for name in ("prior_trials", "same_asset_tests", "n_trials_used", "available_sharpes"):
        assert forward[name] == backward[name], name


def wide(home: Path, extra: list[dict[str, Any]]) -> dict[str, Any]:
    """One ``ma_cross`` row plus same-asset rows of other rules, so the wider count is larger."""
    rows = [rule_row("w0")] + [
        {**rule_row(f"w{i}", spec=f"{i}" * 64), "rule": "breakout"} for i in range(1, 6)
    ]
    for row in [*rows, *extra]:
        append_trial(home, row)
    current = spine_test_key(SPEC, "SPY", START, END, 252, store="home", data_id="d" * 64)
    result = diagnose.trials(
        home,
        "SPY",
        returns(),
        252,
        [],
        "ma_cross",
        snapshot=spine_snapshot(home),
        current_test=current,
    )
    return result


def test_wider_count_and_deflated_sharpe_move_only_without_true_repeats(tmp_path: Path) -> None:
    """The full deflation path: true repeats change nothing; another store adds one try."""
    base = wide(tmp_path / "base", [])
    assert base["family"]["n_trials"] < base["family"]["available_sharpes"]
    repeats = [{**rule_row(f"r{i}", spec=f"{i}" * 64), "rule": "breakout"} for i in (1, 2, 3)]
    repeated = wide(tmp_path / "repeated", repeats)
    assert repeated["family"]["n_trials_used"] == base["family"]["n_trials_used"]
    assert repeated["dsr"] == base["dsr"]
    store = [{**rule_row("x1", spec="1" * 64, store="vendor-b"), "rule": "breakout"}]
    other = wide(tmp_path / "other", store)
    assert other["family"]["n_trials_used"] == base["family"]["n_trials_used"] + 1
    assert other["dsr"] < base["dsr"]
