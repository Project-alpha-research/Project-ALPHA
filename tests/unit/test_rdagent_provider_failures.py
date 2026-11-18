"""Provider failure recovery across proposal, coding and feedback."""

from __future__ import annotations

import asyncio
import json
import os
import re
from collections.abc import Callable
from contextlib import nullcontext
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import Mock

import pytest

from tests.unit._rdagent_support import failed_call, pinned_loop, upstream_class
from tests.unit.test_rdagent_factor_judge import RUNTIME, WORKER


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


def test_pinned_step_runner_recovers_proposal_timeout(tmp_path: Path) -> None:
    from workers.rdagent.loop_guard import ProviderGuard, RoundFeedback

    logger = SimpleNamespace(
        info=Mock(), warning=Mock(), log_object=Mock(), tag=lambda _: nullcontext()
    )
    ns: dict[str, Any] = {
        "asyncio": asyncio,
        "cast": cast,
        "Callable": Callable,
        "Any": Any,
        "datetime": datetime,
        "timezone": timezone,
        "logger": logger,
        "LoopTrace": Mock(),
        "HypothesisFeedback": SimpleNamespace,
        "RD_AGENT_SETTINGS": SimpleNamespace(get_max_parallel=lambda: 1),
    }
    loop = pinned_loop(tmp_path, ns, ValueError)
    calls = tmp_path / "calls.jsonl"
    proposed: list[int] = []

    def propose() -> Any:
        proposed.append(loop.loop_idx)
        if loop.loop_idx == 0:
            failed_call(calls)
        return "hypothesis"

    exp = SimpleNamespace(based_experiments=[], sub_tasks=[], sub_workspace_list=[])
    loop._propose, loop._exp_gen = propose, lambda hypothesis: exp
    loop._interact_feedback = lambda feedback: feedback
    loop.coder = ProviderGuard(
        SimpleNamespace(develop=lambda exp: exp),
        loop,
        "coding",
        tmp_path,
        calls,
        "test",
        ValueError,
        SimpleNamespace,
    )
    loop.runner = SimpleNamespace(develop=lambda exp: exp)
    loop.summarizer = SimpleNamespace(
        generate_feedback=lambda exp, trace: SimpleNamespace(reason="done")
    )
    loop.feedback = RoundFeedback(loop.feedback)

    async def run() -> None:
        for iteration in range(2):
            loop.loop_idx = iteration
            while loop.step_idx[iteration] < len(loop.steps):
                await loop._run_step(iteration)

    asyncio.run(run())
    assert proposed == [0, 1]
    assert loop.loop_prev_out[0]["direct_exp_gen"] is None
    assert loop.step_idx == {0: 5, 1: 5}
    loop.trace.sync_dag_parent_and_hist.assert_called_once_with(
        (exp, loop.loop_prev_out[1]["feedback"]), 1
    )


@pytest.mark.parametrize("value_decision", [None, False])
def test_pinned_evaluator_preserves_execution_and_value_verdict(
    tmp_path: Path, value_decision: bool | None
) -> None:
    from workers.rdagent.loop_guard import CriticEvaluator, ProviderGuard

    ns: dict[str, Any] = {"re": re, "FactorSingleFeedback": SimpleNamespace}
    cls = upstream_class(
        "components/coder/factor_coder/evaluators.py", "FactorEvaluatorForCoder", {"evaluate"}, ns
    )
    evaluator = cls()
    calls = tmp_path / "calls.jsonl"
    evaluator.code_evaluator = SimpleNamespace(
        evaluate=Mock(side_effect=lambda **kw: failed_call(calls))
    )
    evaluator.value_evaluator = SimpleNamespace(
        evaluate=Mock(return_value=("actual value check", value_decision))
    )
    evaluator.final_decision_evaluator = SimpleNamespace(
        evaluate=Mock(side_effect=AssertionError("model final opinion"))
    )
    guard = ProviderGuard(
        None, SimpleNamespace(loop_idx=0), "coding", tmp_path, calls, "test", ValueError, None
    )
    wrapped = CriticEvaluator(evaluator, guard)
    task = SimpleNamespace(factor_name="factor", get_task_information=lambda: "factor", version=1)
    workspace = SimpleNamespace(execute=Mock(return_value=("real execution", [1])))
    feedback = wrapped.evaluate(task, workspace)
    assert feedback.execution_feedback == "real execution"
    assert feedback.value_feedback == "actual value check"
    assert feedback.final_decision is (value_decision is not False)
    assert feedback.value_generated_flag is True
    workspace.execute.assert_called_once()
    evaluator.value_evaluator.evaluate.assert_called_once()
    evaluator.final_decision_evaluator.evaluate.assert_not_called()


@pytest.mark.parametrize("code", ["provider_timeout", "provider_error"])
def test_proposal_skip_finishes_feedback_record_and_starts_round_two(
    tmp_path: Path, code: str
) -> None:
    from workers.rdagent.loop_guard import ProviderGuard, RoundFeedback

    calls = tmp_path / "calls.jsonl"
    seen: list[str] = []

    class Loop:
        loop_idx = 0

        def _propose(self) -> Any:
            seen.append("proposal")
            if self.loop_idx == 0:
                failed_call(calls, code)
            return SimpleNamespace(sub_tasks=[])

        def record(self, previous: dict[str, Any]) -> None:
            exp = (
                previous.get("running")
                or previous.get("coding")
                or previous.get("direct_exp_gen", {}).get("exp_gen")
            )
            assert exp is not None  # no phantom experiment in the next proposal's trace
            seen.append("recorded experiment")

    loop = Loop()
    ProviderGuard(
        SimpleNamespace(), loop, "coding", tmp_path, calls, "test", ValueError, SimpleNamespace
    )
    feedback = RoundFeedback(lambda previous: SimpleNamespace(reason="failed", decision=False))
    for iteration in range(2):
        loop.loop_idx = iteration
        previous: dict[str, Any] = {}
        try:
            exp = loop._propose()
            previous["direct_exp_gen"] = {"exp_gen": exp}
            previous["coding"] = exp
            previous["running"] = exp
        except ValueError as error:
            # LoopBase._run_step's skip path stores None and jumps to feedback.
            previous.update(direct_exp_gen=None, exception=error)
        previous["feedback"] = feedback(previous)
        seen.append("feedback")
        loop.record(previous)
        seen.append("record")
    assert seen == [
        "proposal",
        "feedback",
        "record",
        "proposal",
        "feedback",
        "recorded experiment",
        "record",
    ]
    row = json.loads((tmp_path / "rounds.jsonl").read_text())
    assert row["status"] == "proposal_failed_" + code
    assert row["trial_created"] is False


def test_critic_timeout_retains_execution_and_skips_later_critics(tmp_path: Path) -> None:
    from workers.rdagent import loop_guard

    calls = tmp_path / "calls.jsonl"

    def critic(**kwargs: Any) -> tuple[str, None]:
        if kwargs["target_task"].factor_name == "two":
            failed_call(calls)
        return "normal critic", None

    class Evaluator:
        code_evaluator = SimpleNamespace(evaluate=Mock(side_effect=critic))
        value_evaluator = SimpleNamespace(evaluate=Mock(return_value=("real value checks", None)))
        final_decision_evaluator = SimpleNamespace(
            evaluate=Mock(return_value=(True, "normal final"))
        )

        def evaluate(self, target_task: Any, implementation: Any) -> Any:
            execution, values = implementation.execute()
            value, decision = self.value_evaluator.evaluate(implementation=implementation)
            code, _ = self.code_evaluator.evaluate(
                target_task=target_task,
                implementation=implementation,
                execution_feedback=execution,
                value_feedback=value,
            )
            final, note = self.final_decision_evaluator.evaluate(
                target_task=target_task, code_feedback=code
            )
            return SimpleNamespace(
                execution_feedback=execution,
                value_feedback=value,
                code_feedback=code,
                final_decision=final,
                final_feedback=note,
                value_generated_flag=values is not None,
            )

    evaluator = Evaluator()
    guard = loop_guard.ProviderGuard(
        None,
        SimpleNamespace(loop_idx=0),
        "coding",
        tmp_path,
        calls,
        "test",
        ValueError,
        SimpleNamespace,
    )
    wrapped = loop_guard.CriticEvaluator(evaluator, guard)
    runner = Mock()
    for name in ("one", "two", "three"):
        workspace = SimpleNamespace(execute=Mock(return_value=("real execution " + name, [1])))
        runner(name, wrapped.evaluate(SimpleNamespace(factor_name=name), workspace))
        workspace.execute.assert_called_once()
    assert evaluator.code_evaluator.evaluate.call_count == 2
    assert evaluator.final_decision_evaluator.evaluate.call_count == 1
    assert runner.call_count == 3
    first, second, third = [call.args[1] for call in runner.call_args_list]
    assert first.code_feedback == "normal critic"
    note = "code critic unavailable (provider timeout); judged on execution only"
    assert second.code_feedback == third.code_feedback == note
    for name, feedback in zip(("one", "two", "three"), (first, second, third), strict=True):
        assert feedback.execution_feedback == "real execution " + name
        assert feedback.value_feedback == "real value checks"
        assert feedback.final_decision is True
    wrapped.record()
    row = json.loads((tmp_path / "rounds.jsonl").read_text())
    assert row["critic_unavailable"] == 1 and row["critic_skipped"] == 1
    assert row["critic_unavailable_factor_names"] == ["two"]
    assert row["critic_skipped_factor_names"] == ["three"]
    # The circuit belongs to a round, never the whole run.
    next_round = loop_guard.CriticEvaluator(evaluator, guard)
    next_round.evaluate(
        SimpleNamespace(factor_name="four"),
        SimpleNamespace(execute=Mock(return_value=("new round execution", [1]))),
    )
    assert evaluator.code_evaluator.evaluate.call_count == 3


@pytest.mark.parametrize(
    "error", [RuntimeError("unattested"), ValueError("bug"), KeyboardInterrupt(), SystemExit()]
)
def test_critic_does_not_swallow_unattested_errors_or_interrupts(
    tmp_path: Path, error: BaseException
) -> None:
    from workers.rdagent.loop_guard import CriticEvaluator, ProviderGuard

    critic = Mock(side_effect=error)
    evaluator = SimpleNamespace(
        code_evaluator=SimpleNamespace(evaluate=critic),
        value_evaluator=SimpleNamespace(evaluate=Mock()),
        final_decision_evaluator=SimpleNamespace(evaluate=Mock()),
    )
    evaluator.evaluate = lambda *args: evaluator.code_evaluator.evaluate()
    guard = ProviderGuard(
        None,
        SimpleNamespace(loop_idx=0),
        "coding",
        tmp_path,
        tmp_path / "calls.jsonl",
        "test",
        ValueError,
        None,
    )
    wrapped = CriticEvaluator(evaluator, guard)
    with pytest.raises(type(error)):
        wrapped.evaluate(SimpleNamespace(factor_name="factor"), None)
    wrapped.record()
    assert evaluator.code_evaluator.evaluate is critic
    assert not (tmp_path / "rounds.jsonl").exists()


def test_provider_losses_are_proposed_factors(tmp_path: Path) -> None:
    from alpha_web import _rdagent_runs as reader

    folder = tmp_path / "run"
    folder.mkdir()
    (folder / "receipt.json").write_text(
        json.dumps({"schema": reader.RECEIPT_SCHEMA, "run_id": "run", "rounds_completed": 2})
    )
    ledger = tmp_path / "ledger.jsonl"
    ledger.touch()
    (folder / "rounds.jsonl").write_text(
        "".join(
            json.dumps(
                {
                    "iteration": iteration,
                    "status": "coding_failed_provider_timeout",
                    "factor_names": names,
                    "trial_created": False,
                }
            )
            + "\n"
            for iteration, names in enumerate((["a", "b", "c"], ["d", "e", "f", "g"]))
        )
    )
    detail = reader.read_run(tmp_path, ledger, "run")
    assert detail.run.rounds_completed.value == 2
    assert detail.funnel["proposed"].value == 7
    assert detail.funnel["stopped_by_provider"].value == 7
    assert "stopped by the model provider" in str(detail.funnel["stopped_by_provider"].basis)
    assert detail.funnel["code_ran"].value == 0
    assert detail.factors == []


def test_old_refusal_counts_are_unchanged_and_provider_losses_are_added() -> None:
    from alpha_web import _rdagent_runs as reader

    # Run-3 shape: two refused proposals of two factors each, plus two judged factors.
    refused = [
        {"status": "refused_closed_family", "factor_names": ["a", "b"], "trial_created": False},
        {"status": "refused_closed_family", "factor_names": ["c", "d"], "trial_created": False},
    ]
    trials = [{"status": "SCREEN_FAIL"}, {"status": "SCREEN_FAIL"}]
    funnel = reader._funnel({}, trials, refused)
    assert (funnel["proposed"].value, funnel["refused_closed_family"].value) == (4, 2)
    assert funnel["stopped_by_provider"].value == 0
    lost = {"status": "coding_failed_provider_timeout", "factor_names": ["e", "f", "g"]}
    critic = {"status": "critic_unavailable_provider_timeout", "factor_names": ["h"]}
    funnel = reader._funnel({}, trials, [*refused, lost, critic])
    assert (funnel["proposed"].value, funnel["stopped_by_provider"].value) == (7, 3)


def test_critic_row_does_not_claim_the_round_created_no_trial(tmp_path: Path) -> None:
    from workers.rdagent.loop_guard import CriticEvaluator, ProviderGuard

    calls = tmp_path / "calls.jsonl"
    evaluator = SimpleNamespace(
        code_evaluator=SimpleNamespace(evaluate=lambda: failed_call(calls)),
        value_evaluator=SimpleNamespace(evaluate=Mock()),
        final_decision_evaluator=SimpleNamespace(evaluate=Mock()),
    )
    evaluator.evaluate = lambda *args: evaluator.code_evaluator.evaluate()
    guard = ProviderGuard(
        None, SimpleNamespace(loop_idx=0), "coding", tmp_path, calls, "test", ValueError, None
    )
    wrapped = CriticEvaluator(evaluator, guard)
    wrapped.evaluate(SimpleNamespace(factor_name="factor"), None)
    wrapped.record()
    row = json.loads((tmp_path / "rounds.jsonl").read_text())
    # The critic row is written before the runner; whether a trial is created is not known yet.
    assert row["status"] == "critic_unavailable_provider_timeout"
    assert "trial_created" not in row


REAL_LOOP = r"""
import asyncio, json, sys
from pathlib import Path
from types import SimpleNamespace
sys.path[:0] = [sys.argv[1], sys.argv[2]]
from rdagent.app.qlib_rd_loop.factor import FactorRDLoop
from rdagent.core.exception import FactorEmptyError
from rdagent.core.proposal import HypothesisFeedback
from rdagent.utils.workflow.loop import LoopBase
import loop_guard
work, mode = Path(sys.argv[3]), sys.argv[4]
calls, run = work / "calls.jsonl", work / "run"
run.mkdir()
def fail(code):
    if code:
        row = {"run_id": "r", "endpoint": "/v1/chat/completions", "error_code": code,
               "provider_errors": [code], "attempts": 2, "latency_ms": 360000}
        calls.open("a").write(json.dumps(row) + "\n")
    raise RuntimeError("Failed to create chat completion after 2 retries.")
loop = FactorRDLoop.__new__(FactorRDLoop)
LoopBase.__init__(loop)
loop.session_folder, loop.dump = work / "session", lambda path: None
loop.plan = {"features": [], "feature_codes": {}}
hist, proposed = [], []
loop.trace = SimpleNamespace(sync_dag_parent_and_hist=lambda pair, li: hist.append(li))
def gen(trace, plan):
    proposed.append(loop.loop_idx)
    if loop.loop_idx == 0:
        if mode == "interrupt":
            raise KeyboardInterrupt()
        if mode == "bug":
            raise ValueError("programming error")
        fail({"unattested": None, "budget": "budget_exhausted"}.get(mode, mode))
    return SimpleNamespace(hypothesis="h")
task = SimpleNamespace(factor_name="f1")
exp = SimpleNamespace(based_experiments=[], sub_tasks=[task], sub_workspace_list=[None])
loop.hypothesis_gen = SimpleNamespace(gen=gen)
loop.hypothesis2experiment = SimpleNamespace(convert=lambda h, trace: exp)
loop.coder = SimpleNamespace(develop=lambda e: e)
loop.runner = SimpleNamespace(develop=lambda e: e)
fb = HypothesisFeedback(observations="o", hypothesis_evaluation="e", new_hypothesis="n",
                        reason="ran", decision=False)
loop.summarizer = SimpleNamespace(generate_feedback=lambda e, trace, exception=None: fb)
loop.feedback = loop_guard.RoundFeedback(loop.feedback)
for name, step in (("coder", "coding"), ("runner", "running"), ("summarizer", "feedback")):
    guard = loop_guard.ProviderGuard(getattr(loop, name), loop, step, run, calls, "r",
                                     FactorEmptyError, HypothesisFeedback)
    setattr(loop, name, guard)
try:
    asyncio.run(loop.run(loop_n=2))
    outcome = "completed"
except BaseException as error:
    outcome = type(error).__name__
path = run / "rounds.jsonl"
rows = [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []
print(json.dumps({"outcome": outcome, "proposed": proposed, "trace": hist,
                  "steps": {str(k): v for k, v in loop.step_idx.items()}, "rows": rows}))
"""


def run_factor_script(script: str, *args: str) -> dict[str, Any]:
    import subprocess

    result = subprocess.run(
        [
            os.environ["ALPHA_FACTOR_PYTHON"],
            "-I",
            "-B",
            "-c",
            script,
            os.environ["ALPHA_RDAGENT_SOURCE"],
            str(WORKER),
            *args,
        ],
        check=True,
        capture_output=True,
        text=True,
        timeout=180,
        env={"PATH": os.environ.get("PATH", ""), "OPENAI_API_BASE": "http://127.0.0.1:9"},
    )
    return cast(dict[str, Any], json.loads(result.stdout.strip().splitlines()[-1]))


@RUNTIME
@pytest.mark.parametrize("code", ["provider_timeout", "provider_error"])
def test_real_factor_loop_ends_round_on_proposal_failure(tmp_path: Path, code: str) -> None:
    out = run_factor_script(REAL_LOOP, str(tmp_path), code)
    assert out["outcome"] == "completed" and out["proposed"] == [0, 1]
    assert out["steps"] == {"0": 5, "1": 5}
    assert out["trace"] == [1]  # the failed proposal adds no empty experiment to history
    (row,) = out["rows"]
    assert row["status"] == f"proposal_failed_{code}" and row["iteration"] == 0
    assert row["trial_created"] is False


@RUNTIME
@pytest.mark.parametrize(
    "mode,raised",
    [
        ("budget", "SystemExit"),
        ("interrupt", "KeyboardInterrupt"),
        ("bug", "ValueError"),
        ("unattested", "RuntimeError"),
    ],
)
def test_real_factor_loop_still_stops_on_other_proposal_errors(
    tmp_path: Path, mode: str, raised: str
) -> None:
    out = run_factor_script(REAL_LOOP, str(tmp_path), mode)
    assert out["outcome"] == raised and out["proposed"] == [0]
    assert out["rows"] == [] and out["trace"] == []


REAL_CRITIC = r"""
import json, os, sys
from pathlib import Path
from types import SimpleNamespace
sys.path[:0] = [sys.argv[1], sys.argv[2]]
work = Path(sys.argv[3])
calls, run = work / "calls.jsonl", work / "run"
run.mkdir()
os.environ.update(ALPHA_GATEWAY_CALLS=str(calls), ALPHA_GATEWAY_RUN_ID="r")
from rdagent.components.coder.CoSTEER.evaluators import CoSTEERMultiEvaluator
from rdagent.components.coder.factor_coder.evaluators import FactorEvaluatorForCoder
import alpha_factor_coder
critics, finals = [], []
def receipt(code):
    row = {"run_id": "r", "endpoint": "/v1/chat/completions", "error_code": code,
           "provider_errors": [code] if code else [], "attempts": 2, "latency_ms": 360000}
    calls.open("a").write(json.dumps(row) + "\n")
def coder_round(index, names, fail_on, broken=()):
    calls.open("a").close()
    steps = run / "steps.jsonl"
    steps.open("a").write(json.dumps({"event": "start", "step": "coding", "loop": index}) + "\n")
    single = object.__new__(FactorEvaluatorForCoder)
    single.scen = None
    def critic(**kw):
        name = kw["target_task"].factor_name
        critics.append(name)
        if name == fail_on:
            receipt("provider_timeout")
            receipt("provider_timeout")
            raise RuntimeError("Failed to create chat completion after 2 retries.")
        receipt(None)
        return "critic: fine", None
    def final(**kw):
        finals.append(kw["target_task"].factor_name)
        return True, "final: fine"
    single.code_evaluator = SimpleNamespace(evaluate=critic)
    single.value_evaluator = SimpleNamespace(evaluate=lambda **kw: ("value checks ran", None))
    single.final_decision_evaluator = SimpleNamespace(evaluate=final)
    multi = CoSTEERMultiEvaluator(single, scen=None)
    def workspace(name):
        ran = name not in broken
        return SimpleNamespace(execute=lambda: (name + (" ran" if ran else " crashed"),
                                                [1] if ran else None))
    tasks = [SimpleNamespace(factor_name=n, version=1, get_task_information=lambda n=n: n)
             for n in names]
    evo = SimpleNamespace(sub_tasks=tasks, sub_workspace_list=[workspace(n) for n in names],
                          sub_gt_implementations=None)
    with alpha_factor_coder.tolerant_critic(multi, run):
        steps_iter = multi.evaluate_iter()
        next(steps_iter)
        steps_iter.send(evo)
        try:
            steps_iter.send(None)
        except StopIteration as stop:
            merged = stop.value
    assert multi.single_evaluator is single
    return [[n, bool(fb), fb.execution_feedback, fb.code_feedback]
            for n, fb in zip(names, merged)]
out = {"rounds": [
    coder_round(0, ["a1", "a2", "a3", "a4"], "a2"),
    coder_round(1, ["b1", "b2", "b3"], "b1"),
    coder_round(2, ["c1", "c2"], "c1", broken=("c2",)),
]}
out["critics"], out["finals"] = critics, finals
out["rows"] = [json.loads(line) for line in (run / "rounds.jsonl").read_text().splitlines()]
print(json.dumps(out))
"""


@RUNTIME
def test_real_coder_evaluator_replays_run_four_critic_timeouts(tmp_path: Path) -> None:
    # Run 4: the critic timed out on the 2nd factor of round 0 and the 1st of round 1.
    out = run_factor_script(REAL_CRITIC, str(tmp_path))
    note = "code critic unavailable (provider timeout); judged on execution only"
    round0, round1, round2 = out["rounds"]
    assert round0[0] == ["a1", True, "a1 ran", "critic: fine"]
    assert [r[:2] for r in round0[1:]] == [["a2", True], ["a3", True], ["a4", True]]
    assert all(r[2] == r[0] + " ran" and r[3] == note for r in round0[1:])
    assert all(r[1] is True and r[3] == note for r in round1)
    # Execution-only feedback never accepts code that did not produce values.
    assert round2[1] == ["c2", False, "c2 crashed", note]
    assert out["critics"] == ["a1", "a2", "b1", "c1"] and out["finals"] == ["a1"]
    statuses = [(r["iteration"], r["critic_unavailable_factor_names"]) for r in out["rows"]]
    assert statuses == [(0, ["a2"]), (1, ["b1"]), (2, ["c1"])]
    assert [r["critic_skipped_factor_names"] for r in out["rows"]] == [
        ["a3", "a4"],
        ["b2", "b3"],
        ["c2"],
    ]
    assert all((r["attempts"], r["provider_wait_seconds"]) == (4, 720) for r in out["rows"])
