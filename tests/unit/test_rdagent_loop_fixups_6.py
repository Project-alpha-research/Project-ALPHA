"""Round recovery and recorded provider outcomes, without model calls or sockets."""

from __future__ import annotations

import ast
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

from tests.unit.test_rdagent_loop_fixups_3 import judge_namespace
from workers.rdagent import factor_loop_launch as launch
from workers.rdagent import research_memory as memory
from workers.rdagent.idea_families import declaration


def upstream_class(path: str, name: str, methods: set[str], namespace: dict[str, Any]) -> Any:
    source = os.environ.get("ALPHA_RDAGENT_SOURCE")
    if not source:
        pytest.skip("read-only pinned RD-Agent source is not configured")
    tree = ast.parse((Path(source) / "rdagent" / path).read_text())
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == name)
    cls.bases, cls.keywords, cls.decorator_list = [], [], []
    cls.body = [
        n
        for n in cls.body
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name in methods
    ]
    future = ast.ImportFrom(module="__future__", names=[ast.alias(name="annotations")], level=0)
    tree = ast.fix_missing_locations(ast.Module(body=[future, cls], type_ignores=[]))
    exec(compile(tree, path, "exec"), namespace)
    return namespace[name]


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
    cls = upstream_class(
        "components/workflow/rd_loop.py",
        "RDLoop",
        {"direct_exp_gen", "coding", "running", "feedback", "record"},
        ns,
    )
    base = upstream_class("utils/workflow/loop.py", "LoopBase", {"_run_step"}, ns)
    loop = cls()
    loop._run_step = base._run_step.__get__(loop)
    loop.steps = ["direct_exp_gen", "coding", "running", "feedback", "record"]
    loop.step_idx, loop.loop_prev_out, loop.loop_trace = (
        {0: 0, 1: 0},
        {0: {}, 1: {}},
        {0: [], 1: []},
    )
    loop.EXCEPTION_KEY, loop.LOOP_IDX_KEY = "exception", "loop"
    loop.skip_loop_error, loop.skip_loop_error_stepname = ValueError, "feedback"
    loop.withdraw_loop_error = ()
    loop.get_semaphore = lambda _: asyncio.Semaphore(1)
    loop.tracker, loop.pbar = (
        SimpleNamespace(log_workflow_state=Mock()),
        SimpleNamespace(set_postfix=Mock()),
    )
    loop.dump, loop._check_exit_conditions_on_step = Mock(), Mock()
    loop.session_folder = tmp_path
    loop.get_unfinished_loop_cnt = lambda _: 0
    loop.plan = {"features": [], "feature_codes": {}}
    loop.trace = SimpleNamespace(sync_dag_parent_and_hist=Mock())
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


def failed_call(calls: Path, code: str = "provider_timeout") -> None:
    with calls.open("a") as stream:
        stream.write(
            json.dumps(
                {
                    "run_id": "test",
                    "endpoint": "/v1/chat/completions",
                    "error_code": code,
                    "attempts": 2,
                    "latency_ms": 360000,
                }
            )
            + "\n"
        )
    raise RuntimeError("Failed to create chat completion after 2 retries.")


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


def test_critic_budget_refusal_still_ends_run(tmp_path: Path) -> None:
    from workers.rdagent.loop_guard import CriticEvaluator, ProviderGuard

    calls = tmp_path / "calls.jsonl"
    evaluator = SimpleNamespace(
        code_evaluator=SimpleNamespace(evaluate=lambda: failed_call(calls, "budget_exhausted")),
        value_evaluator=SimpleNamespace(evaluate=Mock()),
        final_decision_evaluator=SimpleNamespace(evaluate=Mock()),
    )
    evaluator.evaluate = lambda *args: evaluator.code_evaluator.evaluate()
    guard = ProviderGuard(
        None, SimpleNamespace(loop_idx=0), "coding", tmp_path, calls, "test", ValueError, None
    )
    wrapped = CriticEvaluator(evaluator, guard)
    with pytest.raises(SystemExit, match="budget exhausted"):
        wrapped.evaluate(SimpleNamespace(factor_name="factor"), None)
    wrapped.record()
    assert not (tmp_path / "rounds.jsonl").exists()


def test_new_round_outcomes_have_plain_sentences() -> None:
    from alpha_web._rdagent_runs import STATUS_SENTENCES

    for step in ("proposal_failed", "critic_unavailable"):
        for failure in ("provider_timeout", "provider_error"):
            assert STATUS_SENTENCES[f"{step}_{failure}"]


def test_restored_proposal_text_keeps_four_same_panel_rounds(tmp_path: Path) -> None:
    history = []
    for i in range(21):
        exp = SimpleNamespace(
            alpha_panel_sha256="other" if i in (18, 20) else "current",
            sub_tasks=[
                SimpleNamespace(factor_name=f"price_delay_{i}", description="", variables={})
            ],
            alpha_evaluation={"factors": [{"name": f"price_delay_{i}", "status": "SCREEN_FAIL"}]},
        )
        history.append((exp, SimpleNamespace(observations=f"FULL ROUND {i}")))
    trace = SimpleNamespace(hist=history)
    closed = "Closed families: volatility and beta; past return (momentum or reversal)"

    def prepare(current: Any) -> tuple[dict[str, Any], bool]:
        return {
            "hypothesis_and_feedback": "\n".join(f.observations for _, f in current.hist)
            + "\n"
            + closed,
            "last_hypothesis_and_feedback": current.hist[-1][1].observations
            if current.hist
            else "",
            "RAG": len(current.hist),
        }, True

    wrapper = memory.ProposalHistory(prepare, 21, "current")
    context, flag = wrapper(trace)
    text = context["hypothesis_and_feedback"]
    assert flag and text.count("FULL ROUND") == 4
    assert text.count("Restored round:") == 17
    assert text.count("different coin panel") == 2
    assert all(f"FULL ROUND {i}" in text for i in (15, 16, 17, 19))
    assert "FULL ROUND 20" not in context["last_hypothesis_and_feedback"]
    assert context["RAG"] == 21
    assert text.count(closed) == 1
    assert len(trace.hist) == 21 and trace.hist is history
    assert wrapper.counts(trace) == {"history_rounds_full": 4, "history_rounds_summarised": 17}


def test_restore_installs_history_view_on_both_proposal_prompts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    session = tmp_path / "old/work/log/__session__/0"
    session.mkdir(parents=True)
    (session / "4_record").touch()
    run = tmp_path / "new"
    (run / "panel").mkdir(parents=True)
    (run / "panel/panel-receipt.json").write_text(json.dumps({"panel_sha256": "same"}))
    trace = SimpleNamespace(hist=[(SimpleNamespace(alpha_panel_sha256="same"), None)] * 21)
    cls = Mock()
    cls.load.return_value = SimpleNamespace(trace=trace)
    loop = SimpleNamespace(
        hypothesis_gen=SimpleNamespace(prepare_context=Mock()),
        hypothesis2experiment=SimpleNamespace(prepare_context=Mock()),
    )
    monkeypatch.setattr(memory, "_new_factor_loop", lambda *args: loop)
    restored, rounds = memory.open_factor_loop(
        cls,
        None,
        2,
        {
            "ALPHA_RDAGENT_MEMORY_DIR": str(tmp_path),
            "FACTOR_CoSTEER_knowledge_base_path": str(tmp_path / "absent"),
            "ALPHA_RDAGENT_CONTINUE_SESSION": str(session.parent),
            "ALPHA_RDAGENT_MEMORY_EVENTS": str(run / "memory-events.jsonl"),
            "ALPHA_FACTOR_RUN_DIR": str(run),
            "LOG_TRACE_PATH": str(run / "log"),
        },
    )
    assert restored is loop and rounds == 2 and loop.trace is trace
    assert isinstance(loop.hypothesis_gen.prepare_context, memory.ProposalHistory)
    assert isinstance(loop.hypothesis2experiment.prepare_context, memory.ProposalHistory)
    assert json.loads((run / "history-context.json").read_text()) == {
        "history_rounds_full": 4,
        "history_rounds_summarised": 17,
    }


def test_history_summary_retains_provider_failure_status() -> None:
    exp = SimpleNamespace(sub_tasks=[SimpleNamespace(factor_name="price_delay")])
    trace = SimpleNamespace(
        hist=[
            (
                exp,
                SimpleNamespace(
                    reason="coding_failed_provider_timeout: coding; 4 attempts, 720 seconds waited"
                ),
            )
        ]
    )
    wrapper = memory.ProposalHistory(
        lambda trace: ({"hypothesis_and_feedback": ""}, True), 1, "panel"
    )
    context, _ = wrapper(trace)
    assert (
        "price_delay; other: price_delay; coding_failed_provider_timeout"
        in context["hypothesis_and_feedback"]
    )


def test_empty_restored_trace_after_proposal_failure_remains_usable() -> None:
    original = {
        "hypothesis_and_feedback": "no previous rounds",
        "last_hypothesis_and_feedback": "no previous rounds",
    }
    wrapper = memory.ProposalHistory(lambda trace: (dict(original), True), 0, "panel")
    context, flag = wrapper(SimpleNamespace(hist=[]))
    assert flag and context == original


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


def test_declaration_prompt_has_no_filled_choice() -> None:
    template = judge_namespace()["DECLARATION_TEMPLATE"]
    assert "declared_direction: <+1 or -1>" in template
    assert "primary_clock: <weekly or monthly>" in template
    assert "direction_reason: <one sentence of economic reasoning>" in template
    assert "follow from the idea" in template
    with pytest.raises(ValueError):
        declaration(template)


@pytest.mark.parametrize("direction,clock", [("+1 or -1", "weekly"), ("+1", "weekly or monthly")])
def test_ambiguous_declarations_still_refused(direction: str, clock: str) -> None:
    with pytest.raises(ValueError):
        declaration(
            f"declared_direction: {direction}; primary_clock: {clock}; "
            "direction_reason: Demand persists."
        )


def test_receipt_separates_failed_wait_from_retried_calls(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from tests.unit.test_rdagent_factor_launch import args

    job = launch.Launch(
        args(tmp_path),
        {"ALPHA_RDAGENT_SOURCE": tmp_path, "ALPHA_FACTOR_PYTHON": tmp_path / "a/b/c/python"},
    )
    job.run.mkdir()
    (job.run / "history-context.json").write_text(
        json.dumps({"history_rounds_full": 4, "history_rounds_summarised": 17})
    )
    (job.run / "rounds.jsonl").write_text(
        json.dumps(
            {
                "iteration": 0,
                "status": "coding_failed_provider_timeout",
                "provider_wait_seconds": 360.5,
            }
        )
        + "\n"
    )
    job.receipt["call_split"] = launch.call_split(
        [
            {
                "endpoint": "/v1/chat/completions",
                "provider_errors": ["provider_timeout"],
                "error_code": error,
                "latency_ms": milliseconds,
                "attempts": 2,
            }
            for error, milliseconds in [("provider_timeout", 360500), (None, 181000)]
        ]
    )
    monkeypatch.setattr(job, "gateway_status", lambda: {})
    monkeypatch.setattr(job, "write_call_labels", lambda: {})
    job.finish(0, "completed")
    receipt = json.loads((job.run / "receipt.json").read_text())
    assert receipt["provider_failed_wait_seconds"] == 360.5
    assert receipt["provider_call_seconds_with_retries"] == 541.5
    assert "provider_wait_seconds" not in receipt
    assert receipt["history_rounds_full"] == 4
    assert receipt["history_rounds_summarised"] == 17


# --- Review additions: recorded shapes from real runs and the real upstream loop classes. ---

WORKER = Path(__file__).resolve().parents[2] / "workers/rdagent"
RUNTIME = pytest.mark.skipif(
    not (os.environ.get("ALPHA_FACTOR_PYTHON") and os.environ.get("ALPHA_RDAGENT_SOURCE")),
    reason="requires ALPHA_FACTOR_PYTHON and ALPHA_RDAGENT_SOURCE",
)


def test_restored_panel_comes_from_the_recorded_evaluation_inputs() -> None:
    # Real evaluation records carry the panel hash under "inputs" and on each factor row.
    def evaluated(name: str, panel: str) -> tuple[Any, Any]:
        exp = SimpleNamespace(
            sub_tasks=[SimpleNamespace(factor_name=name, description="", variables={})],
            alpha_evaluation={
                "inputs": {"panel_sha256": panel},
                "factors": [{"name": name, "status": "SCREEN_FAIL", "panel_sha256": panel}],
            },
        )
        return exp, SimpleNamespace(observations=f"FULL {name}")

    unevaluated = (
        SimpleNamespace(sub_tasks=[SimpleNamespace(factor_name="lost")], alpha_evaluation=None),
        SimpleNamespace(reason="coding_failed_provider_timeout: coding", observations="FULL lost"),
    )
    trace = SimpleNamespace(
        hist=[evaluated("old", "other"), unevaluated, evaluated("same", "current")]
    )

    def prepare(current: Any) -> tuple[dict[str, Any], bool]:
        return {"hypothesis_and_feedback": "\n".join(f.observations for _, f in current.hist)}, True

    wrapper = memory.ProposalHistory(prepare, 3, "current")
    text = wrapper(trace)[0]["hypothesis_and_feedback"]
    assert "FULL same" in text and "FULL old" not in text
    assert "Restored round: old; other: old; SCREEN_FAIL; different coin panel" in text
    assert "lost; other: lost; coding_failed_provider_timeout; coin panel not recorded" in text
    assert wrapper.counts(trace) == {"history_rounds_full": 1, "history_rounds_summarised": 2}


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
