"""Idea family classification, closure and proposal admission."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import Mock

import pytest

from alpha_cli import _rdagent_judge as judge
from tests.unit._rdagent_support import (
    ProposingLoop,
    closed_volatility_ledger,
    judge_namespace,
    proposal,
    universe_run,
)
from workers.rdagent import factor_loop_launch as launch


def test_feedback_separates_global_looks_from_family_failures(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("ALPHA_FACTOR_TRIAL_LEDGER", raising=False)
    ns = judge_namespace()
    rows = [
        {
            "schema": "AlphaRdagentFactorTrialV1",
            "name": f"funding_{i}d",
            "status": "SCREEN_FAIL",
            "screen": {},
            "q": 1.0,
            "run_id": "r",
            "code_sha256": str(i),
            "family_size": 240,
            "screen_m": 240,
        }
        for i in range(2)
    ]
    text = ns["family_summary"](rows, 3)
    assert "failed tries in this idea family (futures funding): 2 of the limit 3" in text
    line = ns["ledger_summary"](rows[0])
    assert "looks so far across all ideas: 240 (sets the screen cutoff)" in line


@pytest.mark.parametrize("source,offered", [("binance-spot", False), ("alpaca-us-equities", True)])
def test_proposer_families_follow_universe_source(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, source: str, offered: bool
) -> None:
    monkeypatch.setenv("ALPHA_FACTOR_RUN_DIR", str(tmp_path))
    monkeypatch.delenv("ALPHA_FACTOR_TRIAL_LEDGER", raising=False)
    (tmp_path / "panel").mkdir()
    spec = {"source": source}
    (tmp_path / "panel/universe.json").write_bytes(judge.canonical(spec))
    (tmp_path / "panel/panel-receipt.json").write_text(
        json.dumps(
            {
                "instruments": {"A": {}},
                "universe_text": "synthetic",
                "universe_sha256": judge.sha(judge.canonical(spec)),
            }
        )
    )
    ns = judge_namespace()
    families = {
        "other: overnight_drift",
        "other: intraday_drift",
        "other: overnight_minus_intraday",
    }
    text = ns["family_permissions"](set(), families)
    opened = text.split("open families: ")[1].split(". ")[0]
    for family in families:
        assert (family in opened) is offered
    if not offered:
        assert "24/7" in text and "midnight" in text


def test_rendered_ledger_row_has_both_counts_without_recounting_failures(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("ALPHA_FACTOR_RUN_DIR", raising=False)
    ns = judge_namespace()
    rows = [
        {
            "schema": "AlphaRdagentFactorTrialV1",
            "name": f"funding_{i}d",
            "status": status,
            "screen": {},
            "q": 1.0,
            "run_id": "r",
            "code_sha256": str(i),
            "family_size": 240,
            "screen_m": 240,
        }
        for i, status in enumerate(["SCREEN_FAIL", "SPREAD_FAIL", "FAILED", "CANDIDATE"])
    ]
    rows += [dict(rows[0]), {**rows[0], "status": "REPEAT"}]
    ledger = tmp_path / "ledger.jsonl"
    ledger.write_text("".join(json.dumps(row) + "\n" for row in rows))
    monkeypatch.setenv("ALPHA_FACTOR_TRIAL_LEDGER", str(ledger))
    monkeypatch.setenv("ALPHA_FACTOR_FAMILY_SWITCH_AFTER", "3")
    context: dict[str, Any] = {"hypothesis_and_feedback": ""}
    ns["append_ledger_context"](context, str(ledger), "synthetic", 0)
    line = next(
        line
        for line in context["hypothesis_and_feedback"].splitlines()
        if line.startswith("funding_1d:")
    )
    assert "looks so far across all ideas: 240 (sets the screen cutoff)" in line
    assert "failed tries in this idea family (futures funding): 2 of the limit 3" in line
    assert ns["closed_families"]() == set()


def test_unknown_trial_schema_does_not_enter_family_failure_counts() -> None:
    ns = judge_namespace()
    assert (
        ns["family_definitions"]().family_failure_counts(
            [{"schema": "AlphaRdagentFactorTrialV999"}]
        )
        == {}
    )


def test_family_permissions_without_source_keep_existing_suggestions(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ALPHA_FACTOR_RUN_DIR", str(tmp_path))
    monkeypatch.delenv("ALPHA_FACTOR_TRIAL_LEDGER", raising=False)
    ns = judge_namespace()
    family = "other: overnight_drift"
    assert family in ns["family_permissions"](set(), {family})
    (tmp_path / "panel").mkdir()
    (tmp_path / "panel/universe.json").write_text(json.dumps({"survivorship": "survivors only"}))
    (tmp_path / "panel/panel-receipt.json").write_text(json.dumps({"instruments": {"A": {}}}))
    assert family in ns["family_permissions"](set(), {family})


def test_family_filter_rejects_changed_frozen_source(tmp_path: Path) -> None:
    ns = judge_namespace()
    (tmp_path / "panel").mkdir()
    spec = {"source": "binance-spot"}
    (tmp_path / "panel/panel-receipt.json").write_text(
        json.dumps({"universe_sha256": judge.sha(judge.canonical(spec))})
    )
    (tmp_path / "panel/universe.json").write_text(json.dumps({"source": "alpaca-us-equities"}))
    with pytest.raises(ValueError, match="differs from the frozen receipt"):
        ns["family_definitions"]().universe_source(str(tmp_path))


@pytest.mark.parametrize("status", ["LOOKAHEAD", "UNSTABLE", "FAILED"])
def test_code_failures_do_not_close_idea_family(status: str) -> None:
    ns = judge_namespace()
    rows = [
        {
            "name": f"volatility_{i}",
            "status": status,
            "schema": "AlphaRdagentFactorTrialV2",
            "screen": {},
            "failure_reason": "exception",
        }
        for i in range(3)
    ]
    summary = ns["family_summary"](rows, 3)
    assert "Do not propose another" not in summary
    for row in rows:
        row["status"] = "SCREEN_FAIL"
    assert "Do not propose another" in ns["family_summary"](rows, 3)


def test_closed_composite_is_refused_before_coding_without_trial(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ns = judge_namespace()
    ledger = closed_volatility_ledger(tmp_path, monkeypatch)
    before = ledger.read_bytes()
    task = SimpleNamespace(
        factor_name="ridge_composite",
        description=(
            "volatility and momentum\ndeclared_direction: +1; "
            "primary_clock: weekly; direction_reason: Demand persists."
        ),
        factor_formulation="regression",
        variables={"volatility": "input", "momentum": "input"},
    )
    coder = SimpleNamespace(develop=Mock())
    exp = SimpleNamespace(sub_tasks=[task], hypothesis=SimpleNamespace(hypothesis="idea"))
    guard = ns["FamilyGuard"](coder)
    with pytest.raises(ValueError, match="closed families.*volatility.*open families"):
        guard.develop(exp)
    coder.develop.assert_not_called()
    records = [json.loads(line) for line in (tmp_path / "rounds.jsonl").read_text().splitlines()]
    assert records[-1]["status"] == "no_admissible_idea"
    assert records[-1]["reason"] == "refused_closed_family"
    assert records[-1]["trial_created"] is False
    assert ledger.read_bytes() == before


def test_closed_family_refusal_asks_the_proposer_again_within_the_round(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ledger = closed_volatility_ledger(tmp_path, monkeypatch)
    before = ledger.read_bytes()
    ns = judge_namespace()
    admissible = proposal("liquidity_gap", "turnover and illiquidity")
    loop = ProposingLoop(ns, [proposal("vol_two", "volatility again"), admissible])
    coder = SimpleNamespace(develop=Mock(return_value="coded"))
    guard = ns["FamilyGuard"](coder, loop)
    assert guard.develop(proposal("vol_one", "volatility")) == "coded"
    coder.develop.assert_called_once_with(admissible)
    assert admissible.base_features == ["f"] and admissible.base_feature_codes == {"f.py": "code"}
    # The proposer saw every refusal of this round, and the next round starts clean.
    assert len(loop.shown) == 2 and len(loop.shown[0]) == 1 and len(loop.shown[1]) == 2
    assert "volatility" in loop.shown[0][0] and "asked again" in loop.shown[0][0]
    assert ns["FAMILY_REFUSALS"] == []
    records = [json.loads(line) for line in (tmp_path / "rounds.jsonl").read_text().splitlines()]
    assert [(r["status"], r["attempt"]) for r in records] == [
        ("refused_closed_family", 1),
        ("refused_closed_family", 2),
    ]
    assert all(r["trial_created"] is False for r in records)
    assert ledger.read_bytes() == before


def test_third_closed_family_refusal_ends_the_round_without_a_trial(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ledger = closed_volatility_ledger(tmp_path, monkeypatch)
    before = ledger.read_bytes()
    ns = judge_namespace()
    loop = ProposingLoop(
        ns, [proposal("vol_two", "volatility"), proposal("vol_three", "volatility")]
    )
    coder = SimpleNamespace(develop=Mock())
    guard = ns["FamilyGuard"](coder, loop)
    with pytest.raises(ValueError, match="No admissible idea"):
        guard.develop(proposal("vol_one", "volatility"))
    coder.develop.assert_not_called()
    assert ns["FAMILY_REFUSALS"] == []
    records = [json.loads(line) for line in (tmp_path / "rounds.jsonl").read_text().splitlines()]
    assert [r["status"] for r in records] == [
        "refused_closed_family",
        "refused_closed_family",
        "no_admissible_idea",
    ]
    assert ledger.read_bytes() == before


def test_refusals_reach_the_proposer_context_before_the_universe_correction(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    universe_run(tmp_path, monkeypatch)
    ns = judge_namespace()
    ns["FAMILY_REFUSALS"].append("Refused closed families: volatility. open families: momentum.")
    context = {"hypothesis_and_feedback": ""}
    ns["append_swing_context"](context, None)
    text = context["hypothesis_and_feedback"]
    assert "ALPHA refused this round's earlier proposal: Refused closed families" in text
    assert text.endswith("earlier text saying otherwise is out of date")


def test_new_loop_installs_family_guard_before_any_coder_call(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from types import ModuleType

    from tests.unit.test_rdagent_research_memory import memory

    universe_run(tmp_path, monkeypatch)
    ns = judge_namespace()
    boundary = ModuleType("alpha_factor_judge")
    monkeypatch.setattr(boundary, "FamilyGuard", ns["FamilyGuard"], raising=False)
    monkeypatch.setattr(boundary, "current_universe", ns["current_universe"], raising=False)
    monkeypatch.setitem(sys.modules, "alpha_factor_judge", boundary)
    original = SimpleNamespace(develop=Mock())
    factory = Mock(return_value=SimpleNamespace(coder=original))
    loop, count = memory.open_factor_loop(factory, "settings", 2, os.environ)
    assert isinstance(loop.coder, ns["FamilyGuard"])
    assert loop.coder.coder is original and count == 2
    assert loop.coder.loop is loop


def test_refused_round_feedback_reaches_trace_without_model_call() -> None:
    ns = judge_namespace()
    message = "Refused closed families: volatility. open families: momentum."
    exp = SimpleNamespace(alpha_family_refusal={"message": message})
    backend = Mock(side_effect=AssertionError("a refused round must not ask a feedback model"))
    ns["APIBackend"] = backend
    result = ns["AlphaFactorFeedback"]().generate_feedback(exp, None)
    assert result.decision is False
    assert message in result.observations
    backend.assert_not_called()


@pytest.mark.parametrize("name", ["long-term reversal", "Long Term Reversal", "long_term_reversal"])
def test_name_normalisation(name: str) -> None:
    assert judge_namespace()["idea_family"](name) == "past return (momentum or reversal)"


def test_estimator_words_are_not_family_keywords() -> None:
    ns = judge_namespace()
    generic = {
        "beta",
        "slope",
        "regression",
        "ols",
        "ridge",
        "huber",
        "lasso",
        "lightgbm",
        "gbm",
        "model",
        "residual",
        "rank",
        "zscore",
    }
    assert ns["GENERIC_ESTIMATOR_WORDS"] == generic
    assert not generic & {word for _, words in ns["FAMILY_KEYWORDS"] for word in words}
    assert ns["idea_family"]("market_beta_30d") == "volatility and beta"
    assert ns["input_families"]("volume weighted average price distance", "long-term reversal") == {
        "VWAP distance",
        "past return (momentum or reversal)",
    }


def test_refusal_records_round_names_and_all_closed_and_labels_reasks(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    closed_volatility_ledger(tmp_path, monkeypatch)
    ns = judge_namespace()
    ns["closed_families"] = lambda: {"volatility and beta", "volume level and trend"}
    loop: Any = ProposingLoop(ns, [proposal("price_delay_120d", "OLS volatility")])
    loop.loop_idx = 4
    coder = SimpleNamespace(develop=Mock(return_value="coded"))
    assert ns["FamilyGuard"](coder, loop).develop(proposal("volatility_30d", "")) == "coded"
    row = json.loads((tmp_path / "rounds.jsonl").read_text())
    assert row["iteration"] == 4 and row["attempt"] == 1
    assert row["factor_names"] == ["volatility_30d"]
    assert row["refused_families"] == ["volatility and beta"]
    assert row["all_closed_families"] == ["volatility and beta", "volume level and trend"]
    assert "closed_families" not in row
    assert "A mechanism that belongs to none of the closed families is allowed." in row["message"]
    steps = [json.loads(line) for line in (tmp_path / "steps.jsonl").read_text().splitlines()]
    calls = [{"ts": steps[0]["ts"], "endpoint": "/v1/chat/completions", "attempts": 1, "usd": 0.2}]
    labelled = launch.label_calls(calls, steps)
    assert labelled[0]["step"] == "proposal_reask"
    split = launch.call_split(calls, labelled)
    assert split["reask_calls"] == 1 and split["reask_usd"] == 0.2
    assert "proposal_reask" in split["chat_usage"]["by_step"]


def test_feedback_prompt_has_closed_and_open_family_context(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    universe_run(tmp_path, monkeypatch)
    closed_volatility_ledger(tmp_path, monkeypatch)
    ns = judge_namespace()
    backend = Mock(return_value="{}")
    ns["APIBackend"] = lambda: SimpleNamespace(build_messages_and_create_chat_completion=backend)
    ns["T"] = lambda _: SimpleNamespace(r=lambda **kw: json.dumps(kw))
    exp = SimpleNamespace(
        hypothesis=SimpleNamespace(hypothesis="idea"),
        sub_tasks=[],
        stdout="",
        alpha_evaluation={"iteration": 0, "decision": False, "factors": []},
    )
    feedback = ns["AlphaFactorFeedback"]()
    feedback.scen = SimpleNamespace(get_scenario_all_desc=lambda: "scenario")
    feedback.generate_feedback(exp, None)
    prompt = backend.call_args.kwargs["system_prompt"]
    assert "Closed families: volatility and beta" in prompt
    assert "open families:" in prompt and "A mechanism that belongs to none" in prompt


def test_only_refused_task_names_are_recorded(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    closed_volatility_ledger(tmp_path, monkeypatch)
    ns = judge_namespace()
    exp = proposal("volatility_30d", "")
    exp.sub_tasks += proposal("price_delay_120d", "").sub_tasks
    with pytest.raises(ValueError, match="No admissible idea"):
        ns["FamilyGuard"](SimpleNamespace(develop=Mock())).develop(exp)
    row = json.loads((tmp_path / "rounds.jsonl").read_text())
    assert row["factor_names"] == ["volatility_30d"]


def test_math_symbols_and_numbers_never_become_families() -> None:
    ns = judge_namespace()
    symbols = dict.fromkeys(["m(t)", "m_s", "ret_{i,t}", "C_{i,s}", "120", "max_depth"], "x")
    assert ns["idea_family"]("ml_mix", "machine learning", "", symbols) == (
        "composite: unknown inputs"
    )
    assert ns["idea_family"]("m_s") == "other: m_s"
    for name, family in (("m20", "momentum"), ("ret_60d", "momentum"), ("hp126", "high")):
        assert family in ns["idea_family"](name)


def test_prose_only_composite_is_unknown_inputs_not_an_open_other() -> None:
    family = judge_namespace()["idea_family"]
    assert family("swing_alpha_v1", "LightGBM over momentum and volatility") == (
        "composite: unknown inputs"
    )
    assert family("factor_a", "A blend of momentum and volatility ranks") == (
        "composite: unknown inputs"
    )


def test_regression_is_one_construct_unless_it_lists_two_known_features() -> None:
    family = judge_namespace()["idea_family"]
    inputs = {"m20": "momentum", "vol60": "volatility"}
    assert family("xs_reg", "cross-sectional regression", "", inputs) == (
        "past return (momentum or reversal); volatility and beta"
    )
    assert family("lag_slope_60d", "OLS regression on lagged BTC", "", {"m20": "x"}) == (
        "other: lag_slope"
    )


def test_composite_history_adds_no_symbol_families() -> None:
    ns = judge_namespace()
    rows = [
        {
            "schema": "AlphaRdagentFactorTrialV2",
            "name": f"ml_mix_{i}",
            "status": "SCREEN_FAIL",
            "description": "machine learning",
            "variables": {"C_{i,s}": "close", "jv60": "jump", "m(t)": "month"},
            "screen": {},
            "q": 1.0,
            "run_id": "test",
        }
        for i in range(3)
    ]
    summary = ns["family_summary"](rows, 3)
    assert "other:" not in summary
    assert "no candidate: composite: unknown inputs." in summary


def test_refusal_message_has_no_doubled_full_stop(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    closed_volatility_ledger(tmp_path, monkeypatch)
    ns = judge_namespace()
    with pytest.raises(ValueError, match="No admissible idea"):
        ns["FamilyGuard"](SimpleNamespace(develop=Mock())).develop(proposal("volatility_30d", ""))
    message = json.loads((tmp_path / "rounds.jsonl").read_text())["message"]
    assert ".." not in message and "allowed. No admissible idea" in message


def test_proposer_admission_instructions() -> None:
    ns = judge_namespace()
    assert "single mechanisms" in ns["SWING_BRIEF"].lower()
    assert "each input feature by name" in ns["SWING_BRIEF"]


def test_unknown_refusal_explains_input_names(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ALPHA_FACTOR_RUN_DIR", str(tmp_path))
    ns = judge_namespace()
    ns["closed_families"] = lambda: {"composite: unknown inputs"}
    with pytest.raises(
        ValueError, match="List each input feature by name in the variables, then it can be judged"
    ):
        ns["FamilyGuard"](None).develop(proposal("ridge_mix", ""))


def test_old_failed_deflation_does_not_keep_family_open() -> None:
    from tests.unit._rdagent_support import clock_rows

    trials = clock_rows(0.04)
    trials["weekly"]["replay"].update(gross={}, net={})
    row = {
        "schema": "AlphaRdagentFactorTrialV3",
        "name": "momentum_60d",
        "status": "CANDIDATE",
        "clocks": trials,
        "lead_clock": "weekly",
    }
    ns = judge_namespace()
    assert "derived" in ns["ledger_summary"](row)
    assert "no candidate: past return (momentum or reversal)" in ns["family_summary"]([row] * 3, 3)
    assert row["status"] == "CANDIDATE"


def test_all_greek_symbols_are_ignored() -> None:
    from workers.rdagent.idea_families import input_names

    assert input_names(dict.fromkeys(["iota", "chi", "upsilon", "omicron"], "symbol")) == []


def test_logistic_mix_name_identifies_composite() -> None:
    from workers.rdagent.idea_families import idea_family

    assert idea_family("logistic_mix", variables={"price_delay": "feature"}) == "other: price_delay"


@pytest.mark.parametrize("crypto", [True, False])
def test_session_families_absent_from_all_crypto_tallies(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, crypto: bool
) -> None:
    universe_run(tmp_path, monkeypatch)
    if crypto:
        (tmp_path / "panel/universe.json").unlink()  # legacy Binance spot panel
    else:
        spec = {"source": "alpaca-us-equities", "survivorship": "141 instruments, survivors only"}
        (tmp_path / "panel/universe.json").write_bytes(judge.canonical(spec))
        receipt = json.loads((tmp_path / "panel/panel-receipt.json").read_text())
        receipt["universe_sha256"] = judge.sha(judge.canonical(spec))
        (tmp_path / "panel/panel-receipt.json").write_text(json.dumps(receipt))
    names = ["overnight_drift", "intraday_drift", "overnight_minus_intraday"]
    rows = [
        {
            "schema": "AlphaRdagentFactorTrialV1",
            "name": name,
            "screen": {},
            "q": 1,
            "run_id": "r",
            "code_sha256": name,
            "status": "SCREEN_FAIL",
        }
        for name in names
    ]
    path = tmp_path / "ledger"
    path.write_text("".join(json.dumps(row) + "\n" for row in rows))
    monkeypatch.setenv("ALPHA_FACTOR_TRIAL_LEDGER", str(path))
    ns = judge_namespace()
    context = {"hypothesis_and_feedback": ""}
    ns["append_swing_context"](context, str(path))
    text = context["hypothesis_and_feedback"] + ns["family_permissions"](
        {"other: intraday_drift"}, include_counts=True
    )
    # Stock universes keep every session family and its count; nothing on disk changes.
    assert all((name in text) is not crypto for name in names)
    assert len(path.read_text().splitlines()) == len(names)


def test_over_limit_count_respects_candidate_exception(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rows = [
        {
            "schema": "AlphaRdagentFactorTrialV1",
            "name": f"funding_{i}",
            "screen": {},
            "q": 1,
            "run_id": "r",
            "code_sha256": str(i),
            "status": "SCREEN_FAIL",
        }
        for i in range(27)
    ]
    path = tmp_path / "ledger"
    path.write_text("".join(json.dumps(row) + "\n" for row in rows))
    monkeypatch.setenv("ALPHA_FACTOR_TRIAL_LEDGER", str(path))
    ns = judge_namespace()
    context = {"hypothesis_and_feedback": ""}
    ns["append_ledger_context"](context, str(path), "synthetic", 0)
    for text in (
        context["hypothesis_and_feedback"],
        ns["family_permissions"](ns["closed_families"](), include_counts=True),
    ):
        assert "closed: 27 failed tries (limit 3)" in text
        assert "27 of the limit" not in text
    summary = ns["family_summary"]([*rows, {**rows[0], "status": "CANDIDATE"}], 3)
    assert "closed: 27" not in summary and "27 failed tries (limit 3)" in summary
