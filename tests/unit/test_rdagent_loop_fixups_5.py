"""Provider failures, named composite inputs and process-local embedding reuse."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import Mock

import pytest

from tests.unit.test_rdagent_embedding_cap import model, rows
from tests.unit.test_rdagent_loop_fixups_3 import judge_namespace
from workers.rdagent import gateway_usage
from workers.rdagent import model_gateway as gw

__all__ = ["model"]


def test_real_logistic_inputs_stay_open() -> None:
    names = [
        "price_delay",
        "lead_lag_score",
        "lag_lag_score",
        "delay_beta_ratio",
        "hurst",
        "entropy",
    ]
    family = judge_namespace()["idea_family"](
        "logistic_mix", "mix of features", "", dict.fromkeys(names, "feature")
    )
    assert set(family.split("; ")) == {"other: " + name for name in names}


def test_placeholder_values_name_real_inputs() -> None:
    inputs = [
        "ltr_189d_skip21d",
        "max_drawdown_252d",
        "vwap_distance_189d",
        "overnight_drift_60d",
        "variance_ratio_5_120d",
    ]
    variables = {
        f"x{i}_i_s": f"feature {name}, ranked at close" for i, name in enumerate(inputs, 1)
    }
    family = judge_namespace()["idea_family"]("ridge_mix", variables=variables)
    assert set(family.split("; ")) == {
        "long-term reversal",
        "drawdown",
        "VWAP distance",
        "other: overnight_drift",
        "other: variance_ratio",
    }


def test_math_symbols_ignored_and_closed_input_retained() -> None:
    family = judge_namespace()["idea_family"]
    symbols = dict.fromkeys(["C", "O", "r", "m_s", "c_i_s", "sigma", "beta"], "momentum prose")
    assert family("ridge_mix", variables=symbols) == "composite: unknown inputs"
    assert family("ridge_mix", variables={**symbols, "mom_60d": "x"}) == "momentum and trend"


def test_proposer_admission_instructions() -> None:
    ns = judge_namespace()
    assert "single mechanisms" in ns["SWING_BRIEF"].lower()
    assert "each input feature by name" in ns["SWING_BRIEF"]


def test_cache_mixed_order_cost_and_fresh_process(model: gw.Gateway) -> None:
    backend = Mock(spec=["embed"])
    backend.embed.side_effect = lambda texts: gw.EmbeddingResult(
        [[float(ord(t))] for t in texts], "fake", tokens=len(texts)
    )
    model.embedding_backend = backend
    first = model.embeddings({"model": "alpha-embed", "input": ["a", "b", "a"]})
    before = model.budget.status()
    second = model.embeddings({"model": "alpha-embed", "input": ["b", "a"]})
    assert model.budget.status() == before
    third = model.embeddings({"model": "alpha-embed", "input": ["b", "c", "a"]})
    assert [d["embedding"] for d in third["data"]] == [[98.0], [99.0], [97.0]]
    assert backend.embed.call_args_list[0].args[0] == ["a", "b"]
    assert backend.embed.call_count == 2
    assert first["data"][0]["embedding"] == second["data"][1]["embedding"]
    assert sum(row.get("embedding_cache_hits", 0) for row in rows(model)) == 5
    fresh = gw.Gateway(model.settings, embedding_backend=backend)
    fresh.embeddings({"model": "alpha-embed", "input": ["a"]})
    assert backend.embed.call_count == 3


def test_timeout_reservation_is_not_reported_as_confirmed_usage() -> None:
    row = gateway_usage.record_defaults()
    gateway_usage.record_attempt(row, error="provider_timeout")
    assert row["usage_known"] is False
    assert (
        row["attempt_usage"][0]["cost_basis"] == "reserved estimate, not confirmed by the provider"
    )


def test_provider_guard_records_failure_then_next_round_runs(tmp_path: Path) -> None:
    from workers.rdagent.loop_guard import ProviderGuard

    calls = tmp_path / "calls.jsonl"
    loop = SimpleNamespace(loop_idx=0, loop_prev_out={0: {}}, EXCEPTION_KEY="exception")

    def failed(exp: Any) -> Any:
        calls.write_text(
            json.dumps(
                {
                    "run_id": "test",
                    "endpoint": "/v1/chat/completions",
                    "error_code": "provider_timeout",
                    "attempts": 2,
                    "latency_ms": 360000,
                }
            )
            + "\n"
        )
        raise RuntimeError("Failed to create chat completion after 1 retries.")

    component = SimpleNamespace(develop=Mock(side_effect=failed))
    guard = ProviderGuard(
        component, loop, "coding", tmp_path, calls, "test", ValueError, SimpleNamespace
    )
    with pytest.raises(ValueError, match="coding_failed_provider_timeout"):
        guard.develop(SimpleNamespace())
    row = json.loads((tmp_path / "rounds.jsonl").read_text())
    assert row["attempts"] == 2 and row["provider_wait_seconds"] == 360
    assert row["trial_created"] is False
    component.develop.side_effect = None
    component.develop.return_value = "next"
    loop.loop_idx = 1
    assert guard.develop(SimpleNamespace()) == "next"


def test_budget_refusal_not_converted_to_failed_round(tmp_path: Path) -> None:
    from workers.rdagent.loop_guard import ProviderGuard

    calls = tmp_path / "calls.jsonl"

    def refused(exp: Any) -> Any:
        calls.write_text(
            json.dumps(
                {
                    "run_id": "test",
                    "endpoint": "/v1/chat/completions",
                    "error_code": "budget_exhausted",
                }
            )
            + "\n"
        )
        raise RuntimeError("Failed to create chat completion after 1 retries.")

    guard = ProviderGuard(
        SimpleNamespace(develop=refused),
        SimpleNamespace(loop_idx=0),
        "coding",
        tmp_path,
        calls,
        "test",
        ValueError,
        SimpleNamespace,
    )
    with pytest.raises(SystemExit, match="budget"):
        guard.develop(None)
    assert not (tmp_path / "rounds.jsonl").exists()


def test_round_history_uses_admitted_proposal_and_names_refusals(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from tests.unit.test_rdagent_loop_fixups_3 import (
        ProposingLoop,
        closed_volatility_ledger,
        proposal,
    )

    closed_volatility_ledger(tmp_path, monkeypatch)
    ns = judge_namespace()
    admitted = proposal("price_delay", "")

    class RecordingLoop(ProposingLoop):
        loop_prev_out: dict[int, dict[str, Any]]

    loop = RecordingLoop(ns, [admitted])
    loop.loop_prev_out = {0: {}}
    ns["FamilyGuard"](SimpleNamespace(develop=lambda exp: exp), loop).develop(
        proposal("vol_60d", "")
    )
    assert loop.loop_prev_out[0]["direct_exp_gen"]["exp_gen"] is admitted
    assert (
        "refused before coding: vol_60d (volatility and beta)"
        in admitted.alpha_refused_before_coding[0]
    )


def test_final_refusal_history_has_no_none_observation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from tests.unit.test_rdagent_loop_fixups_3 import closed_volatility_ledger, proposal
    from workers.rdagent.loop_guard import RoundFeedback

    closed_volatility_ledger(tmp_path, monkeypatch)
    ns = judge_namespace()
    exp = proposal("vol_60d", "")
    with pytest.raises(ValueError):
        ns["FamilyGuard"](None).develop(exp)
    previous = {"direct_exp_gen": {"exp_gen": exp}, "exception": ValueError("refused")}

    def original(prev: Any) -> Any:
        return SimpleNamespace(observations=None, reason="refused", decision=False)

    result = RoundFeedback(original)(previous)
    assert result.observations == ""
    assert "refused before coding: vol_60d (volatility and beta)" in result.reason


def test_unknown_refusal_explains_input_names(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from tests.unit.test_rdagent_loop_fixups_3 import proposal

    monkeypatch.setenv("ALPHA_FACTOR_RUN_DIR", str(tmp_path))
    ns = judge_namespace()
    ns["closed_families"] = lambda: {"composite: unknown inputs"}
    with pytest.raises(
        ValueError, match="List each input feature by name in the variables, then it can be judged"
    ):
        ns["FamilyGuard"](None).develop(proposal("ridge_mix", ""))


def test_ledger_proposer_text_reports_deflation() -> None:
    from tests.unit.test_rdagent_fixups_5 import clock_rows

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


def test_previous_run_judge_version_controls_warning(tmp_path: Path) -> None:
    from workers.rdagent import research_memory as memory

    root = tmp_path / "memory"
    first = memory.prepare(
        root, run_id="first", run_dir=tmp_path, source_sha256="source", judge_sha256="current"
    )
    manifest = json.loads((root / "memory.json").read_text())
    session = tmp_path / "old-session"
    (session / "0").mkdir(parents=True)
    (session / "0/4_record").touch()
    manifest["latest_session"] = {
        "run_id": "old",
        "run_dir": str(tmp_path),
        "session_dir": str(session),
        "completed_loops": 1,
        "judge_sha256": "old",
        "recorded_at": "date",
    }
    manifest["runs"] = [
        {
            "run_id": "previous",
            "run_dir": str(tmp_path),
            "started_at": "date",
            "ended_at": "date",
            "continued_from_run_id": None,
            "loops_before": 0,
            "loops_after": 0,
            "knowledge_sha256_before": None,
            "knowledge_sha256_after": None,
            "judge_sha256": first.judge_sha256,
            "warnings": [],
        }
    ]
    (root / "memory.json").write_text(json.dumps(manifest))
    plan = memory.prepare(
        root, run_id="next", run_dir=tmp_path, source_sha256="source", judge_sha256="current"
    )
    assert "judge-version-changed" not in {w["code"] for w in plan.warnings}


def test_resume_error_is_not_abandoned_at_cap(tmp_path: Path) -> None:
    from workers.rdagent.research_memory import close_unfinished_rounds

    session = tmp_path / "work/log/__session__"
    (session / "0").mkdir(parents=True)
    (session / "0/0_direct_exp_gen").touch()
    (tmp_path / "steps.jsonl").write_text(
        json.dumps({"loop": 0, "event": "end", "status": "error"}) + "\n"
    )
    close_unfinished_rounds(session)
    close_unfinished_rounds(session)
    assert json.loads((tmp_path / "rounds.jsonl").read_text())["status"] == "abandoned_after_error"


def test_old_failed_deflation_does_not_keep_family_open() -> None:
    from tests.unit.test_rdagent_fixups_5 import clock_rows

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
    assert "no candidate: momentum and trend" in ns["family_summary"]([row] * 3, 3)
    assert row["status"] == "CANDIDATE"


def test_timeout_attempt_booked_amount_is_labelled(model: gw.Gateway) -> None:
    from tests.unit.test_rdagent_embedding_cap import chat

    def fail(*args: Any) -> Any:
        raise gw.GatewayError(504, "provider_timeout", "timed out")

    model.chat_backend = SimpleNamespace(complete=fail)
    with pytest.raises(gw.GatewayError):
        model.chat(chat())
    logged = rows(model)[-1]
    assert logged["usage_known"] is False
    assert logged["cost_basis"] == "reserved estimate, not confirmed by the provider"
    assert logged["attempt_usage"][0]["booked_usd"] == 0


def test_successful_batch_is_cached_even_when_later_batch_hits_cap(
    model: gw.Gateway, monkeypatch: pytest.MonkeyPatch
) -> None:
    from tests.unit.test_rdagent_provider_embeddings import provider

    provider(model, monkeypatch)
    model.budget.write(
        {
            "schema_version": 1,
            "runs": {"test": {"calls": 0, "usd": 0, "local_embedding_calls": 1999}},
            "months": {},
        }
    )

    def post(url: str, body: dict[str, Any], *args: Any, **kwargs: Any) -> dict[str, Any]:
        return {
            "model": "model-a",
            "data": [{"index": i, "embedding": [float(t)]} for i, t in enumerate(body["input"])],
        }

    monkeypatch.setattr(gw, "post_json", post)
    with pytest.raises(gw.GatewayError, match="EMBEDDING_CALLS_PER_RUN"):
        model.embeddings({"model": "alpha-embed", "input": [str(i) for i in range(33)]})
    assert model.embeddings({"model": "alpha-embed", "input": "0"})["data"][0]["embedding"] == [0.0]


@pytest.mark.parametrize(
    "variables,refused",
    [
        (
            dict.fromkeys(
                [
                    "price_delay",
                    "lead_lag_score",
                    "lag_lag_score",
                    "delay_beta_ratio",
                    "hurst",
                    "entropy",
                ],
                "feature",
            ),
            False,
        ),
        (
            {
                f"x{i}_i_s": name
                for i, name in enumerate(
                    [
                        "ltr_189d_skip21d",
                        "max_drawdown_252d",
                        "vwap_distance_189d",
                        "overnight_drift_60d",
                        "variance_ratio_5_120d",
                    ],
                    1,
                )
            },
            False,
        ),
        ({"mom_60d": "momentum"}, True),
    ],
)
def test_third_run_proposals_at_coding_boundary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, variables: dict[str, str], refused: bool
) -> None:
    from tests.unit.test_rdagent_loop_fixups_3 import proposal
    from tests.unit.test_rdagent_loop_fixups_4 import WIDE_RUN_CLOSED

    monkeypatch.setenv("ALPHA_FACTOR_RUN_DIR", str(tmp_path))
    ns = judge_namespace()
    ns["closed_families"] = lambda: WIDE_RUN_CLOSED
    exp = proposal("ridge_mix", "")
    exp.sub_tasks[0].variables = variables
    coder = SimpleNamespace(develop=Mock(return_value="coded"))
    guard = ns["FamilyGuard"](coder)
    if refused:
        with pytest.raises(ValueError, match="momentum and trend"):
            guard.develop(exp)
        coder.develop.assert_not_called()
    else:
        assert guard.develop(exp) == "coded"
        coder.develop.assert_called_once_with(exp)


def test_provider_feedback_failure_retains_existing_trial_and_ends_round(tmp_path: Path) -> None:
    from workers.rdagent.loop_guard import ProviderGuard

    calls = tmp_path / "calls.jsonl"

    def failed(exp: Any, trace: Any, exception: Any) -> Any:
        calls.write_text(
            json.dumps(
                {
                    "run_id": "test",
                    "endpoint": "/v1/chat/completions",
                    "error_code": "provider_error",
                    "attempts": 2,
                    "latency_ms": 1000,
                }
            )
            + "\n"
        )
        raise RuntimeError("Failed to create chat completion after 1 retries.")

    guard = ProviderGuard(
        SimpleNamespace(generate_feedback=failed),
        SimpleNamespace(loop_idx=0),
        "feedback",
        tmp_path,
        calls,
        "test",
        ValueError,
        SimpleNamespace,
    )
    result = guard.generate_feedback(
        SimpleNamespace(alpha_evaluation={"factors": [{"name": "existing"}]}), None
    )
    assert result.decision is False
    row = json.loads((tmp_path / "rounds.jsonl").read_text())
    assert row["step"] == "feedback" and row["trial_created"] is True
    assert row["status"] == "coding_failed_provider_error"


def test_unrelated_error_cannot_be_hidden_by_stale_provider_receipt(tmp_path: Path) -> None:
    from workers.rdagent.loop_guard import ProviderGuard

    calls = tmp_path / "calls.jsonl"
    calls.write_text(
        json.dumps(
            {"run_id": "test", "endpoint": "/v1/chat/completions", "error_code": "provider_timeout"}
        )
        + "\n"
    )
    guard = ProviderGuard(
        SimpleNamespace(develop=Mock(side_effect=RuntimeError("code bug"))),
        SimpleNamespace(loop_idx=0),
        "coding",
        tmp_path,
        calls,
        "test",
        ValueError,
        SimpleNamespace,
    )
    with pytest.raises(RuntimeError, match="code bug"):
        guard.develop(None)
    assert not (tmp_path / "rounds.jsonl").exists()


@pytest.mark.parametrize("code", ["provider_unavailable", "rate_limit_exceeded"])
def test_other_attested_provider_failures_close_round(tmp_path: Path, code: str) -> None:
    from workers.rdagent.loop_guard import ProviderGuard

    calls = tmp_path / "calls.jsonl"

    def failed(exp: Any) -> Any:
        calls.write_text(
            json.dumps(
                {
                    "run_id": "test",
                    "endpoint": "/v1/chat/completions",
                    "error_code": code,
                    "provider_errors": [code],
                    "attempts": 1,
                    "latency_ms": 100,
                }
            )
            + "\n"
        )
        raise RuntimeError("Failed to create chat completion after 1 retries.")

    guard = ProviderGuard(
        SimpleNamespace(develop=failed),
        SimpleNamespace(loop_idx=0),
        "coding",
        tmp_path,
        calls,
        "test",
        ValueError,
        SimpleNamespace,
    )
    with pytest.raises(ValueError, match="coding_failed_provider_error"):
        guard.develop(None)


def test_receipt_end_event_and_plain_console_line(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from tests.unit.test_rdagent_factor_launch import args
    from workers.rdagent import factor_loop_launch as launch

    parsed = args(tmp_path)
    job = launch.Launch(
        parsed, {"ALPHA_RDAGENT_SOURCE": tmp_path, "ALPHA_FACTOR_PYTHON": tmp_path / "a/b/c/python"}
    )
    job.run.mkdir()
    monkeypatch.setattr(job, "gateway_status", lambda: {})
    monkeypatch.setattr(job, "write_call_labels", lambda: {})
    assert job.finish(1, "budget exhausted") == 1
    assert capsys.readouterr().out == "RD-Agent loop ended: budget exhausted.\n"
    end = json.loads((job.run / "launch.jsonl").read_text().splitlines()[-1])
    assert end["event"] == "end" and end["exit_reason"] == "budget exhausted"


def test_budget_finish_closes_round_at_cap_before_receipt_exists(tmp_path: Path) -> None:
    from workers.rdagent.research_memory import close_unfinished_rounds

    session = tmp_path / "work/log/__session__"
    (session / "0").mkdir(parents=True)
    (session / "0/0_direct_exp_gen").touch()
    (tmp_path / "steps.jsonl").write_text(
        json.dumps({"loop": 0, "event": "end", "status": "error"}) + "\n"
    )
    close_unfinished_rounds(session, exit_reason="budget exhausted")
    assert json.loads((tmp_path / "rounds.jsonl").read_text())["status"] == "abandoned_at_cap"


def test_all_greek_symbols_are_ignored() -> None:
    from workers.rdagent.idea_families import input_names

    assert input_names(dict.fromkeys(["iota", "chi", "upsilon", "omicron"], "symbol")) == []


def test_logistic_mix_name_identifies_composite() -> None:
    from workers.rdagent.idea_families import idea_family

    assert idea_family("logistic_mix", variables={"price_delay": "feature"}) == "other: price_delay"


def test_upstream_keeps_its_one_retry_for_unusable_replies(tmp_path: Path) -> None:
    # MAX_RETRY is upstream's attempt count for every chat failure, including a reply that fails
    # its own schema check (real runs retried 9 such replies); one attempt would crash the run.
    from workers.rdagent import factor_loop_launch as launch

    env = launch.loop_environment(
        base_url="http://127.0.0.1:1",
        token="t",
        run=tmp_path,
        factor_python=tmp_path / "py/bin/python",
        ledger=tmp_path / "trials.jsonl",
        home=str(tmp_path),
    )
    assert env["MAX_RETRY"] == "2"


def _failed_call(attempts: int, seconds: float, code: str = "provider_timeout") -> dict[str, Any]:
    return {
        "run_id": "test",
        "endpoint": "/v1/chat/completions",
        "error_code": code,
        "provider_errors": [code] * attempts,
        "attempts": attempts,
        "latency_ms": seconds * 1000,
    }


def test_failed_round_counts_every_attempt_of_the_failed_call(tmp_path: Path) -> None:
    from workers.rdagent.loop_guard import ProviderGuard

    calls = tmp_path / "calls.jsonl"
    ok = {"run_id": "test", "endpoint": "/v1/chat/completions", "error_code": None}

    def failed(exp: Any) -> Any:
        rows = [ok, _failed_call(2, 360), _failed_call(2, 360)]
        calls.write_text("".join(json.dumps(r) + "\n" for r in rows))
        raise RuntimeError("Failed to create chat completion after 2 retries.")

    guard = ProviderGuard(
        SimpleNamespace(develop=failed),
        SimpleNamespace(loop_idx=0),
        "coding",
        tmp_path,
        calls,
        "test",
        ValueError,
        SimpleNamespace,
    )
    with pytest.raises(ValueError, match="4 attempts, 720 seconds waited"):
        guard.develop(SimpleNamespace())
    row = json.loads((tmp_path / "rounds.jsonl").read_text())
    assert (row["attempts"], row["provider_wait_seconds"]) == (4, 720)


@pytest.mark.parametrize("stop", [KeyboardInterrupt, SystemExit])
def test_interrupts_pass_through_and_record_nothing(
    tmp_path: Path, stop: type[BaseException]
) -> None:
    from workers.rdagent.loop_guard import ProviderGuard

    calls = tmp_path / "calls.jsonl"
    calls.write_text(json.dumps(_failed_call(2, 360)) + "\n")
    guard = ProviderGuard(
        SimpleNamespace(develop=Mock(side_effect=stop())),
        SimpleNamespace(loop_idx=0),
        "coding",
        tmp_path,
        calls,
        "test",
        ValueError,
        SimpleNamespace,
    )
    with pytest.raises(stop):
        guard.develop(None)
    assert not (tmp_path / "rounds.jsonl").exists()
