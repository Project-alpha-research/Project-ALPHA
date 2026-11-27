"""Declared choices, conservative counting and unchanged historical records."""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from alpha_cli import _rdagent_clocks as clocks
from alpha_cli import _rdagent_judge as judge
from alpha_cli import rdagent_factor_eval as ev
from alpha_cli._rdagent_stability import deflation_note
from alpha_cli.spine.trial_record import map_row
from alpha_core import DataError
from tests.unit._rdagent_support import clock_rows, judge_namespace
from tests.unit.test_trial_record import factor


@pytest.mark.parametrize("m", [1, 10, 237])
@pytest.mark.parametrize("confirmed", [0, 1])
def test_screen_cutoff_counts_looks_without_failed_pass_credit(m: int, confirmed: int) -> None:
    from alpha_cli._rdagent_stats import screen_cutoff

    assert screen_cutoff(m, confirmed) == pytest.approx(0.1 * (1 + confirmed) / m)
    if m == 237:
        assert screen_cutoff(m, confirmed) < 0.0083


@pytest.mark.parametrize(
    "sharpes,term", [([0.1, 0.1], "sampling_floor"), ([-1.0, 1.0], "sample_variance")]
)
def test_deflation_counts_every_look_and_records_floor(sharpes: list[float], term: str) -> None:
    from alpha_cli._rdagent_stats import FACTOR_DEFLATION_RULE, factor_deflation
    from alpha_validation.dsr import expected_max_sharpe, probabilistic_sharpe_ratio

    returns = np.array([0.01, -0.02, 0.03, 0.04, -0.01])
    result = factor_deflation(returns, sharpes, 237)
    variance = max(float(np.var(sharpes, ddof=1)), 0.25)
    assert result["n_trials"] == result["deflation_n"] == 474
    assert result["deflation_variance"] == pytest.approx(variance)
    assert result["deflation_variance_term"] == term
    assert result["deflation_rule"] == FACTOR_DEFLATION_RULE == "family-looks-x2-floor-1"
    assert result["dsr"] == pytest.approx(
        probabilistic_sharpe_ratio(returns, benchmark_sr=expected_max_sharpe(variance, 474))
    )


def test_missing_declaration_refused_before_panel_read(tmp_path: Path) -> None:
    request = tmp_path / "request.json"
    request.write_text(
        json.dumps(
            {
                "schema": "AlphaRdagentFactorRequestV1",
                "iteration": 0,
                "factors": [{"name": "x", "status": "OK", "code_sha256": "a" * 64}],
            }
        )
    )
    with pytest.raises(DataError, match="declared_direction.*primary_clock.*direction_reason"):
        ev._inputs(tmp_path, request)


def test_undeclared_sign_cannot_pass() -> None:
    rng = np.random.default_rng(812)
    signal = rng.normal(size=(80, 12))
    outcome = -signal + rng.normal(size=signal.shape)
    result = judge.screen(signal, outcome, "a" * 64, declared_direction=1, n_resamples=20)
    assert result["p"] > 0.5
    assert result["direction"] == 1
    assert result["diagnostics"]["opposite_direction_p"] < 0.05


def test_nonprimary_pass_cannot_select_clock() -> None:
    from tests.unit._rdagent_support import clock_rows

    trials = clock_rows(0.99)
    assert clocks.overall_status(trials, primary_clock="monthly") == ("SCREEN_FAIL", "monthly")


def test_newey_west_uses_all_lags_even_after_negative_correlation() -> None:
    from alpha_cli._rdagent_stats import newey_west

    rng = np.random.default_rng(14)
    values = np.empty(600)
    values[0] = 0
    for i in range(1, len(values)):
        values[i] = 0.7 * values[i - 1] + rng.normal()
    lag = math.ceil(4 * (len(values) / 100) ** (2 / 9))
    centered = values - values.mean()
    gamma = [
        float(centered[k:] @ centered[: len(values) - k]) / len(values) for k in range(lag + 1)
    ]
    variance = gamma[0] + 2 * sum((1 - k / (lag + 1)) * gamma[k] for k in range(1, lag + 1))
    result = newey_west(values)
    assert result["lag"] == lag
    assert result["long_run_variance"] == pytest.approx(variance)
    assert result["effective_n"] == pytest.approx(len(values) * gamma[0] / variance)


def test_cluster_sandwich_known_cell_scores() -> None:
    from alpha_cli._rdagent_stats import clustered_mean_variance

    cells = np.array([[1.0, 2.0, 3.0], [2.0, 4.0, 6.0], [3.0, 6.0, 9.0], [4.0, 8.0, 12.0]])
    influence = (cells - cells.mean()) / cells.size
    expected = (
        4 / 3 * np.square(influence.sum(axis=1)).sum()
        + 3 / 2 * np.square(influence.sum(axis=0)).sum()
        - 12 / 11 * np.square(influence).sum()
    )
    assert clustered_mean_variance(cells) == pytest.approx(expected)


def test_twin_negation_has_signed_correlation() -> None:
    from alpha_cli._rdagent_twins import rank_twin

    values = np.random.default_rng(19).normal(size=(80, 12))
    result = rank_twin(values, -values)
    assert result["is_twin"]
    assert result["mean_correlation"] == pytest.approx(-1)
    assert result["mean_absolute_correlation"] == pytest.approx(1)


def test_old_deflation_is_labelled_without_recalculation() -> None:
    replay: dict[str, Any] = {"deflated_sharpe": {"dsr": 0.04, "threshold": 0.95, "n_trials": 36}}
    text = deflation_note(replay)
    assert "0.04" in text and "36 trials" in text
    assert "old rule (fewer looks counted)" in text


def test_web_and_ledger_derive_same_old_status(tmp_path: Path) -> None:
    from alpha_cli.spine.trial_record import map_row
    from alpha_web._rdagent_runs import _factor
    from tests.unit._rdagent_support import clock_rows
    from tests.unit.test_trial_record import factor

    row = factor(clocks=clock_rows(0.04))
    assert _factor(row).status == map_row("rdagent", tmp_path / "ledger", 1, row).raw_status
    assert "derived" in _factor(row).sentence


def worker_module(name: str) -> Any:
    import importlib.util

    spec = importlib.util.spec_from_file_location(name, Path("workers/rdagent") / f"{name}.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_sign_families_merge_and_declarations_parse() -> None:
    module = worker_module("idea_families")
    assert (
        module.name_family("ltr_60d")
        == module.name_family("momentum_60d")
        == "past return (momentum or reversal)"
    )
    assert module.name_family("negative_unfamiliar_signal_60d") == module.name_family(
        "unfamiliar_signal_60d"
    )
    text = (
        "Economic argument. declared_direction: -1; primary_clock: "
        "monthly; direction_reason: Buying losers benefits from recovery."
    )
    assert module.declaration(text) == {
        "declared_direction": -1,
        "primary_clock": "monthly",
        "direction_reason": "Buying losers benefits from recovery.",
    }
    with pytest.raises(ValueError, match="declared_direction.*primary_clock.*direction_reason"):
        module.declaration("Buying losers benefits from recovery.")


@pytest.mark.parametrize(
    "code,ending", [("provider_timeout", "timeout"), ("provider_error", "error")]
)
def test_proposal_provider_failures_advance_without_trial(
    tmp_path: Path, code: str, ending: str
) -> None:
    from types import SimpleNamespace

    guards = worker_module("loop_guard")
    calls = tmp_path / "calls.jsonl"

    def propose() -> None:
        with calls.open("a") as stream:
            stream.write(
                json.dumps(
                    {
                        "run_id": "run",
                        "endpoint": "/v1/chat/completions",
                        "error_code": code,
                        "attempts": 2,
                        "latency_ms": 4000,
                    }
                )
                + "\n"
            )
        raise RuntimeError("Failed to create chat completion")

    loop = SimpleNamespace(loop_idx=2, _propose=propose)
    guards.ProviderGuard(object(), loop, "coding", tmp_path, calls, "run", ValueError, object)
    with pytest.raises(ValueError, match="proposal_failed_provider_" + ending):
        loop._propose()
    row = json.loads((tmp_path / "rounds.jsonl").read_text())
    assert row["trial_created"] is False and row["iteration"] == 2


def declared_fixture(
    run: Path, *, direction: int = 1, primary: str = "weekly", seed: int = 42
) -> Path:
    from tests.unit.test_rdagent_factor_eval import fixture

    request = fixture(run, seed=seed)
    obj = json.loads(request.read_text())
    obj["factors"][0].update(
        declared_direction=direction,
        primary_clock=primary,
        direction_reason="Persistent demand rewards this ranking.",
    )
    request.write_text(json.dumps(obj))
    return request


def test_primary_only_replay_and_negation_repeat(tmp_path: Path) -> None:
    import polars as pl

    first, second = tmp_path / "first", tmp_path / "second"
    ledger = tmp_path / "ledger.jsonl"
    record = ev.evaluate(first, declared_fixture(first), first / "result.json", ledger)
    row = record["factors"][0]
    assert row["family_size"] == row["replayed_trials"] == 1
    assert row["clocks"]["daily"]["status"] == row["clocks"]["monthly"]["status"] == "DIAGNOSTIC"
    assert not row["clocks"]["daily"]["replay"] and not row["clocks"]["monthly"]["replay"]
    assert row["replay"]["deflated_sharpe"]["deflation_n"] == 2
    assert "Expected chance passes:" in record["feedback_text"]
    request = declared_fixture(second, direction=-1, seed=99)
    values = pl.read_parquet(first / "factors.parquet").with_columns(-pl.col("factor"))
    values.write_parquet(second / "factors.parquet")
    repeated = ev.evaluate(second, request, second / "result.json", ledger)["factors"][0]
    assert repeated["status"] == "REPEAT"
    assert repeated["twin"]["mean_correlation"] == pytest.approx(-1)
    assert repeated["first_trial"]["run_id"] == row["run_id"]
    assert repeated["family_size"] == repeated["distinct_factors"] == 1
    assert len(ev._read_ledger(ledger)) == 2


def test_real_stored_old_figure_is_not_recomputed(tmp_path: Path) -> None:
    from alpha_cli.spine.trial_record import map_row
    from alpha_web._rdagent_runs import _factor
    from tests.unit._rdagent_support import clock_rows
    from tests.unit.test_trial_record import factor

    # Read-only ledger observation, 2026-11-17: ltr_189d_skip21d, weekly.
    stored = {
        "dsr": 0.040068639719771273,
        "expected_max_sharpe": 0.07149487681249725,
        "n_trials": 36,
        "passed": False,
        "psr": 0.7358810618979239,
        "sharpe": 0.018941406261531745,
        "threshold": 0.95,
    }
    trials = clock_rows(stored["dsr"])
    trials["weekly"]["replay"]["deflated_sharpe"] = stored
    row = factor(clocks=trials, name="ltr_189d_skip21d")
    record = map_row("rdagent", tmp_path / "ledger", 1, row)
    web = _factor(row)
    assert record.raw_status == web.status == "DEFLATION_FAIL"
    assert record.measures["dsr"] == pytest.approx(stored["dsr"])
    assert web.clocks["weekly"].deflation["dsr"].value == pytest.approx(stored["dsr"])
    assert "old rule (fewer looks counted)" in web.sentence
    assert row["status"] == "CANDIDATE" and stored["n_trials"] == 36


def test_merged_family_closes_for_either_sign(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from tests.unit._rdagent_support import judge_namespace

    rows = [
        {
            "schema": "AlphaRdagentFactorTrialV2",
            "name": name,
            "code_sha256": str(i),
            "status": "SCREEN_FAIL",
            "screen": {},
        }
        for i, name in enumerate(
            ["mom_60d", "mom_90d", "mom_120d", "ltr_60d", "ltr_90d", "ltr_120d"]
        )
    ]
    ledger = tmp_path / "ledger"
    ledger.write_text("".join(json.dumps(row) + "\n" for row in rows))
    monkeypatch.setenv("ALPHA_FACTOR_TRIAL_LEDGER", str(ledger))
    ns = judge_namespace()
    assert ns["closed_families"]() == {"past return (momentum or reversal)"}
    assert "6 tries" in ns["family_summary"](rows, 3)


def test_missing_proposal_fields_use_same_reask_limit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from types import SimpleNamespace
    from unittest.mock import Mock

    from tests.unit._rdagent_support import ProposingLoop, judge_namespace, proposal

    ns = judge_namespace()
    monkeypatch.setenv("ALPHA_FACTOR_RUN_DIR", str(tmp_path))
    monkeypatch.delenv("ALPHA_FACTOR_TRIAL_LEDGER", raising=False)
    proposed = [proposal("new_mechanism", "economic reasoning") for _ in range(3)]
    for exp in proposed:
        exp.sub_tasks[0].description = "economic reasoning without declarations"
    loop = ProposingLoop(ns, proposed[1:])
    coder = SimpleNamespace(develop=Mock())
    with pytest.raises(
        ValueError, match="Add declared_direction:.*primary_clock:.*direction_reason:"
    ):
        ns["FamilyGuard"](coder, loop).develop(proposed[0])
    coder.develop.assert_not_called()
    records = [json.loads(line) for line in (tmp_path / "rounds.jsonl").read_text().splitlines()]
    assert len(records) == 3 and len(loop.shown) == 2
    assert records[0]["status"] == "refused_missing_declaration"
    assert all(row["trial_created"] is False for row in records)


def test_every_new_status_has_a_web_sentence() -> None:
    from alpha_web._rdagent_run_words import status_sentence

    for status in (
        "DIAGNOSTIC",
        "refused_missing_declaration",
        "proposal_failed_provider_timeout",
        "proposal_failed_provider_error",
    ):
        assert status_sentence(status, None)


def test_small_p_with_many_looks_cannot_replay(monkeypatch: pytest.MonkeyPatch) -> None:
    from unittest.mock import Mock

    import polars as pl

    from alpha_cli._rdagent_stats import SCREEN_RULE

    replay = Mock(side_effect=AssertionError("failed screen must not replay"))
    monkeypatch.setattr(ev, "replay", replay)
    trials: dict[str, dict[str, Any]] = {
        c: {
            "status": "OK" if c == "weekly" else "DIAGNOSTIC",
            "p": 0.0083 if c == "weekly" else 0.0,
            "q": 1.0,
            "screen": {"direction": 1},
            "replay": {},
        }
        for c in ev.CLOCKS
    }
    row: dict[str, Any] = {
        "code_sha256": "new",
        "primary_clock": "weekly",
        "lead_clock": "weekly",
        "screen_rule": SCREEN_RULE,
        "status": "OK",
        "clocks": trials,
    }
    family = {(str(i), "weekly"): {"p": 0.0001, "replay": {}} for i in range(236)}
    family[("new", "weekly")] = trials["weekly"]
    returns, _ = ev._replay_clocks([row], pl.DataFrame(), {}, [], {}, family, 237)
    assert row["status"] == "SCREEN_FAIL" and returns == {}
    assert row["screen_m"] == 237 and row["screen_confirmed"] == 0
    assert trials["weekly"]["bh_q_diagnostic"] < 0.1
    replay.assert_not_called()


def test_opposite_sign_is_screen_fail_in_real_evaluation(tmp_path: Path) -> None:
    run = tmp_path / "wrong_sign"
    result = ev.evaluate(
        run, declared_fixture(run, direction=-1), run / "result.json", tmp_path / "ledger"
    )
    row = result["factors"][0]
    assert row["status"] == "SCREEN_FAIL" and row["replayed_trials"] == 0
    assert row["screen"]["diagnostics"]["opposite_direction_p"] < 0.05


@pytest.mark.parametrize("error", [ValueError("programming"), RuntimeError("unattested error")])
def test_proposal_guard_does_not_catch_programming_errors(tmp_path: Path, error: Exception) -> None:
    from types import SimpleNamespace

    guards = worker_module("loop_guard")

    def propose() -> None:
        raise error

    loop = SimpleNamespace(loop_idx=0, _propose=propose)
    guards.ProviderGuard(
        object(), loop, "coding", tmp_path, tmp_path / "calls", "run", KeyError, object
    )
    with pytest.raises(type(error), match=str(error)):
        loop._propose()
    assert not (tmp_path / "rounds.jsonl").exists()


def test_newey_west_short_series_keeps_declared_lag() -> None:
    from alpha_cli._rdagent_stats import newey_west

    assert newey_west(np.array([0.1, 0.2]))["lag"] == math.ceil(4 * (2 / 100) ** (2 / 9))


def test_effective_size_reports_newey_west_estimate() -> None:
    from alpha_cli._rdagent_stats import autocorrelation_effective_size, newey_west

    values = np.cumsum(np.random.default_rng(41).normal(size=600))
    assert autocorrelation_effective_size(values) == newey_west(values)["effective_n"]


def test_web_derivation_matches_ledger_for_nonfinite_old_figure() -> None:
    from alpha_cli._rdagent_stability import recorded_status
    from alpha_web._rdagent_runs import _derived_status
    from tests.unit._rdagent_support import clock_rows
    from tests.unit.test_trial_record import factor

    row = factor(clocks=clock_rows(float("nan")))
    assert _derived_status(row) == recorded_status(row) == "DEFLATION_FAIL"


def test_repeat_pointer_has_final_same_batch_status(tmp_path: Path) -> None:
    run = tmp_path / "repeat"
    path = declared_fixture(run)
    request = json.loads(path.read_text())
    request["factors"].append({**request["factors"][0], "name": "same_code"})
    path.write_text(json.dumps(request))
    rows = ev.evaluate(run, path, run / "result.json", tmp_path / "ledger")["factors"]
    assert rows[0]["status"] == "CANDIDATE"
    assert rows[1]["first_trial"]["status"] == rows[0]["status"]


@pytest.mark.parametrize(
    "value,status", [(0.04, "DEFLATION_FAIL"), (0.95, "CANDIDATE"), (0.96, "CANDIDATE")]
)
def test_candidate_requires_recorded_deflation(value: float, status: str) -> None:
    assert clocks.overall_status(clock_rows(value)) == (status, "weekly")


def test_missing_deflation_cannot_be_candidate() -> None:
    trials = clock_rows(0.99)
    trials["weekly"]["replay"] = {}
    assert clocks.overall_status(trials)[0] != "CANDIDATE"


def test_old_candidate_derived_without_rewriting_and_counts(tmp_path: Path) -> None:
    row = factor(clocks=clock_rows(0.04))
    record = map_row("rdagent", tmp_path / "ledger", 1, row)
    assert record.raw_status == "DEFLATION_FAIL" and record.outcome == "rejected"
    assert record.counts_for_deflation and row["status"] == "CANDIDATE"
    assert record.reason is not None
    assert all(s in record.reason for s in ("derived", "0.04", "0.95", "42 trials"))


def test_ledger_proposer_text_reports_deflation() -> None:
    trials = clock_rows(0.04)
    trials["weekly"]["replay"].update(gross={}, net={})
    row = {
        "schema": "AlphaRdagentFactorTrialV3",
        "name": "idea",
        "status": "DEFLATION_FAIL",
        "clocks": trials,
        "lead_clock": "weekly",
    }
    assert all(s in judge_namespace()["ledger_summary"](row) for s in ("0.04", "0.95", "42 trials"))


def test_new_round_outcomes_have_plain_sentences() -> None:
    from alpha_web._rdagent_run_words import STATUS_SENTENCES

    for step in ("proposal_failed", "critic_unavailable"):
        for failure in ("provider_timeout", "provider_error"):
            assert STATUS_SENTENCES[f"{step}_{failure}"]
