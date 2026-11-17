"""The top-third-versus-bottom-third spread check (ADR-0055): stricter, before the replay."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import patch

import numpy as np
import pandas as pd
import pytest

from alpha_cli import _rdagent_clocks as clocks
from alpha_cli import _rdagent_judge as judge
from alpha_cli import _rdagent_universe as universes
from alpha_cli import rdagent_factor_eval as ev
from alpha_core import DataError
from tests.unit.test_rdagent_factor_eval import evaluate, fixture

SYMBOLS = [f"C{i:02}USDT" for i in range(15)]


def test_spread_is_top_minus_bottom_mean_in_the_claimed_direction() -> None:
    signal = np.tile(np.arange(15.0), (4, 1))
    outcome = np.tile(np.linspace(-0.07, 0.07, 15), (4, 1)) * np.array([[1.0], [2.0], [1.0], [3.0]])
    up = ev.spread(signal, outcome, 1, SYMBOLS, "a" * 64, horizon=7, n_resamples=50)
    down = ev.spread(signal, outcome, -1, SYMBOLS, "a" * 64, horizon=7, n_resamples=50)
    top, bottom = outcome[:, 10:].mean(), outcome[:, :5].mean()
    assert up["mean_spread"] == pytest.approx(top - bottom)
    assert up["status"] == "PASS" and down["status"] == "FAIL"
    assert down["reason"] == "top-third-does-not-beat-bottom-third"
    assert up["decision_days"] == 4
    assert up["annualized_spread"] == pytest.approx(up["mean_spread"] * 365 / 7)


def test_a_rank_that_correlates_but_picks_the_losing_third_fails() -> None:
    """The health-check failure mode: rank IC positive, held top third loses to the bottom."""
    rng = np.random.default_rng(3)
    days = 200
    signal = rng.normal(size=(days, 15))
    order = np.argsort(np.argsort(signal, axis=1), axis=1)  # 0..14 per day
    outcome = 0.002 * order  # monotone: rank IC > 0
    outcome = np.where(order == 14, -0.2, outcome)  # but the top name crashes every period
    ic = np.nanmean(
        [np.corrcoef(order[d], np.argsort(np.argsort(outcome[d])))[0, 1] for d in range(days)]
    )
    assert ic > 0.5
    result = ev.spread(signal, outcome, 1, SYMBOLS, "c" * 64, horizon=1, n_resamples=50)
    assert result["status"] == "FAIL"
    assert result["top_third_mean_return"] < result["bottom_third_mean_return"]


def test_a_spread_that_exists_only_by_tie_order_fails() -> None:
    signal = np.zeros((30, 15))
    signal[:, 0] = 1.0  # one distinct name; everything else tied
    outcome = np.zeros((30, 15))
    outcome[:, 1:5] = 0.01 + np.linspace(0, 0.001, 30)[:, None]  # tied names that sort first win
    result = ev.spread(signal, outcome, 1, SYMBOLS, "d" * 64, horizon=1, n_resamples=50)
    assert result["mean_spread"] > 0 > result["alternate_tie_order_mean_spread"]
    assert result["status"] == "FAIL"


def test_missing_forward_return_of_a_ranked_name_fails_loud() -> None:
    signal = np.tile(np.arange(15.0), (5, 1))
    outcome = np.full((5, 15), 0.01)
    outcome[2, 14] = np.nan  # a held name has no exit price: never silently dropped
    with pytest.raises(DataError, match="forward return"):
        ev.spread(signal, outcome, 1, SYMBOLS, "e" * 64, horizon=1, n_resamples=50)


def test_no_direction_or_one_day_fails_loud() -> None:
    signal = np.tile(np.arange(15.0), (5, 1))
    with pytest.raises(DataError):
        ev.spread(signal, np.zeros((5, 15)), 0, SYMBOLS, "f" * 64, horizon=1)
    with pytest.raises(DataError):
        ev.spread(signal[:1], np.ones((1, 15)), 1, SYMBOLS, "f" * 64, horizon=1)


def test_spread_selection_matches_the_replays_top_third() -> None:
    rng = np.random.default_rng(11)
    row = rng.normal(size=15)
    row[[2, 9]] = row[4]  # ties
    for direction in (1, -1):
        top, _ = ev._thirds(row, direction, SYMBOLS, reverse_ties=False)
        ranked = sorted(range(15), key=lambda j: (-direction * row[j], SYMBOLS[j]))
        assert top == ranked[:5]


def test_spread_failure_is_recorded_and_never_passes(tmp_path: Path) -> None:
    run = tmp_path / "run"
    req = fixture(run)

    def failing(*args: Any, **kwargs: Any) -> dict[str, Any]:
        return {**_real(*args, **kwargs), "status": "FAIL", "reason": ev.SPREAD_REASON}

    with patch.object(judge, "spread", side_effect=failing):
        record = evaluate(run, req, tmp_path / "ledger.jsonl")
    factor = record["factors"][0]
    assert factor["status"] == "SPREAD_FAIL"
    assert record["decision"] is False
    # The planted factor's replays are profitable, yet no clock may pass once its spread failed.
    assert {t["status"] for t in factor["clocks"].values()} == {"SPREAD_FAIL", "DIAGNOSTIC"}
    assert all(
        t["replay"]["net"]["annualized_return"] > 0 for t in ev.trial_clocks(factor).values()
    )
    assert "top-third-does-not-beat-bottom-third" in record["feedback_text"]
    row = json.loads((tmp_path / "ledger.jsonl").read_text().splitlines()[0])
    assert row["clocks"]["weekly"]["spread"]["reason"] == ev.SPREAD_REASON
    ev._read_ledger(tmp_path / "ledger.jsonl")  # the new status validates


_real = ev.spread


def test_spread_never_turns_a_failure_into_a_pass(tmp_path: Path) -> None:
    """With the check passing, the verdicts equal the judge without it (replay decides)."""
    run = tmp_path / "run"
    req = fixture(run)
    record = evaluate(run, req, tmp_path / "ledger.jsonl")
    factor = record["factors"][0]
    assert factor["status"] == "CANDIDATE"
    assert factor["replay"]["deflated_sharpe"]["passed"] is True
    for trial in ev.trial_clocks(factor).values():
        assert trial["spread"]["status"] == "PASS"
        assert trial["status"] == ("PASS" if trial["replay"]["net"]["annualized_return"] > 0
                                   else "REPLAY_FAIL")  # fmt: skip


def test_overall_status_prefers_replay_fail_then_spread_fail() -> None:
    def trial(status: str, q: float) -> dict[str, object]:
        return {"status": status, "q": q}

    assert clocks.overall_status(
        {"daily": trial("REPLAY_FAIL", 0.01), "weekly": trial("SPREAD_FAIL", 0.01),
         "monthly": trial("SCREEN_FAIL", 0.5)}
    )[0] == "REPLAY_FAIL"  # fmt: skip
    assert clocks.overall_status(
        {"daily": trial("SPREAD_FAIL", 0.01), "weekly": trial("SCREEN_FAIL", 0.5),
         "monthly": trial("SCREEN_FAIL", 0.5)}
    )[0] == "SPREAD_FAIL"  # fmt: skip


def _universe(**changes: object) -> dict[str, object]:
    return {**universes.DEFAULT, "name": "test", **changes}


def test_universe_file_validation() -> None:
    universes.validate(_universe())
    bad: dict[str, Any]
    for bad in (
        {"annual_periods": 252},
        {"calendar": "lunar"},
        {"min_universe": 9},
        {"liquidity": {"lookback_days": 0, "min_median_quote_volume": 1, "max_names": 10}},
        {"instruments": []},
    ):
        with pytest.raises(DataError):
            universes.validate(_universe(**bad))
    with pytest.raises(DataError, match="not yet evaluable"):
        universes.evaluable(_universe(calendar="exchange-sessions", annual_periods=252))


def test_alpaca_universe_with_too_few_names_is_refused(tmp_path: Path) -> None:
    data = tmp_path / "data"
    data.mkdir()
    bars = tmp_path / "alpaca" / "store" / "bars"
    bars.mkdir(parents=True)
    for name in ("AAPL", "MSFT", "SPY"):
        pd.DataFrame({"x": [1]}).to_parquet(bars / f"{name}.parquet")
    (data / "stores.toml").write_text('alpaca = "../alpaca"\n')
    spec = tmp_path / "u.json"
    spec.write_text(json.dumps(_universe(
        source="alpaca-us-equities", calendar="exchange-sessions", annual_periods=252,
        instruments=["AAPL", "MSFT", "NVDA"])))  # fmt: skip
    with pytest.raises(DataError, match="has 2 of its names"):
        ev.freeze(data, tmp_path / "out", spec)


def _bind_universe(run: Path, spec: dict[str, object]) -> None:
    """What freeze does: write the file and bind its hash into the panel receipt."""
    (run / "panel" / "universe.json").write_bytes(ev.canonical(spec))
    receipt = json.loads((run / "panel" / "panel-receipt.json").read_text())
    receipt["universe_sha256"] = ev.sha(ev.canonical(spec))
    (run / "panel" / "panel-receipt.json").write_text(json.dumps(receipt))


def test_liquidity_rule_masks_names_and_is_recorded(tmp_path: Path) -> None:
    import shutil

    run = tmp_path / "run"
    req = fixture(run)
    # Fixture quote volume is 10,000 per day: a 20,000 threshold leaves nobody, so every clock
    # becomes DEGENERATE and says the universe caused it; 5,000 keeps all fifteen. The fixture
    # has no history before 2021, so the look-back is one day.
    for threshold, expected in ((5000, "CANDIDATE"), (20000, "DEGENERATE")):
        target = tmp_path / f"run-{threshold}"
        shutil.copytree(run, target)
        rule = {"lookback_days": 1, "min_median_quote_volume": threshold, "max_names": 15}
        _bind_universe(target, _universe(liquidity=rule))
        record = evaluate(target, target / req.name, tmp_path / f"ledger-{threshold}.jsonl")
        factor = record["factors"][0]
        assert factor["status"] == expected
        assert record["disclosures"]["universe"]["liquidity"] == rule
        if expected == "DEGENERATE":
            assert "liquidity rule" in factor["clocks"]["weekly"]["screen"]["reason"]


def test_coverage_is_judged_over_the_names_the_universe_let_rank(tmp_path: Path) -> None:
    """A rule keeping 10 of 15 names must not make every factor 'degenerate' (review finding)."""
    run = tmp_path / "run"
    req = fixture(run)
    rule = {"lookback_days": 1, "min_median_quote_volume": 0, "max_names": 10}
    _bind_universe(run, _universe(liquidity=rule))
    factor = evaluate(run, req, tmp_path / "ledger.jsonl")["factors"][0]
    assert factor["status"] != "DEGENERATE"
    assert factor["clocks"]["daily"]["screen"]["coverage"] == 1.0


@pytest.mark.parametrize("defect", ["unbound", "edited"])
def test_a_universe_file_not_bound_by_the_freeze_is_refused(tmp_path: Path, defect: str) -> None:
    run = tmp_path / "run"
    req = fixture(run)
    if defect == "unbound":
        (run / "panel" / "universe.json").write_bytes(ev.canonical(_universe()))
    else:
        _bind_universe(run, _universe())
        (run / "panel" / "universe.json").write_bytes(ev.canonical(_universe(name="other")))
    with pytest.raises(DataError, match="bound in the panel receipt"):
        evaluate(run, req, tmp_path / "ledger.jsonl")


def test_universe_values_the_evaluator_does_not_apply_are_refused(tmp_path: Path) -> None:
    run = tmp_path / "run"
    req = fixture(run)
    _bind_universe(run, _universe(min_names=6, min_universe=18))
    with pytest.raises(DataError, match="only values the evaluator applies"):
        evaluate(run, req, tmp_path / "ledger.jsonl")


def _forced(status: str) -> Any:
    def forced(*args: Any, **kwargs: Any) -> dict[str, Any]:
        result = _real(*args, **kwargs)
        if status == "FAIL":
            return {**result, "status": "FAIL", "reason": ev.SPREAD_REASON}
        return {k: v for k, v in result.items() if k != "reason"} | {"status": "PASS"}

    return forced


def test_spread_stopped_factors_still_count_as_trials_exactly_as_before(tmp_path: Path) -> None:
    """An earlier, cheaper rejection must never lower the attempts the Deflated Sharpe counts.

    The same run with every spread check failing must give the same trial count, the same trial
    Sharpes and the same deflated values as with every check passing (the judge before ADR-0055,
    where every screened clock was replayed); only the statuses differ.
    """
    records = {}
    for status in ("PASS", "FAIL"):
        run = tmp_path / status
        req = fixture(run)
        with patch.object(judge, "spread", side_effect=_forced(status)):
            records[status] = evaluate(run, req, tmp_path / f"ledger-{status}.jsonl")
    before, after = records["PASS"], records["FAIL"]
    assert after["replayed_trials"] == before["replayed_trials"] == 1
    assert after["family_size"] == before["family_size"]
    for clock in ("weekly",):
        old, new = before["factors"][0]["clocks"][clock], after["factors"][0]["clocks"][clock]
        assert new["status"] == "SPREAD_FAIL" and old["status"] in ("PASS", "REPLAY_FAIL")
        for key in ("deflated_sharpe", "deflated_sharpe_family"):
            assert new["replay"][key] == old["replay"][key]
        assert new["replay"]["net"] == old["replay"]["net"]
    assert after["decision"] is False and after["factors"][0]["status"] == "SPREAD_FAIL"


def test_a_spread_error_still_counts_its_clock_as_a_trial(tmp_path: Path) -> None:
    """Review finding: a spread check that cannot be computed must not lower the trial count."""

    def weekly_error(*args: Any, **kwargs: Any) -> dict[str, Any]:
        if kwargs.get("horizon") == 7:
            raise DataError("spread check needs at least two decision days with varying spreads")
        result: dict[str, Any] = _forced("PASS")(*args, **kwargs)
        return result

    records = {}
    for name, side_effect in (("pass", _forced("PASS")), ("error", weekly_error)):
        run = tmp_path / name
        req = fixture(run)
        with patch.object(judge, "spread", side_effect=side_effect):
            records[name] = evaluate(run, req, tmp_path / f"ledger-{name}.jsonl")
    assert records["error"]["replayed_trials"] == records["pass"]["replayed_trials"] == 1
    weekly = records["error"]["factors"][0]["clocks"]["weekly"]
    assert weekly["status"] == "ERROR" and "counted_only" in weekly["replay"]
    for clock in ("daily", "monthly"):
        new = records["error"]["factors"][0]["clocks"][clock]["replay"]
        assert new == records["pass"]["factors"][0]["clocks"][clock]["replay"] == {}


def test_a_receipt_bound_universe_file_cannot_be_removed(tmp_path: Path) -> None:
    run = tmp_path / "run"
    req = fixture(run)
    _bind_universe(run, _universe())
    (run / "panel" / "universe.json").unlink()
    with pytest.raises(DataError, match="bound in the panel receipt"):
        evaluate(run, req, tmp_path / "ledger.jsonl")


def test_feedback_never_shows_a_failed_clocks_replay_as_a_result(tmp_path: Path) -> None:
    run = tmp_path / "run"
    req = fixture(run)
    with patch.object(judge, "spread", side_effect=_forced("FAIL")):
        record = evaluate(run, req, tmp_path / "ledger.jsonl")
    text = record["feedback_text"]
    assert "net annual excess counted only, not a result" in text
    assert "net annual excess 5." not in text
