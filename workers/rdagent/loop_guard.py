"""ALPHA round boundary for exhausted gateway chat failures; upstream stays unchanged."""

from __future__ import annotations

import json
from copy import copy, deepcopy
from pathlib import Path
from typing import Any

# The round outcomes this guard records; the Workstation reader has a sentence for each.
ROUND_STATUSES = {
    "provider_timeout": "coding_failed_provider_timeout",
    "provider_error": "coding_failed_provider_error",
    "internal_error": "coding_failed_internal_error",
}


def _as_tuple(value: Any) -> tuple[type[BaseException], ...]:
    return tuple(value) if isinstance(value, (tuple, list)) else (value,)


def raised_by_alpha(error: BaseException) -> bool:
    """Decide by the deepest frame that is ALPHA worker code or RD-Agent code.

    Library frames (pandas, scipy, json, ...) are skipped, so an ALPHA defect raised inside a
    library call still counts as ALPHA's, and an upstream search that fails inside numpy still
    counts as upstream's. Frames of neither kind decide nothing.
    """
    worker = Path(__file__).resolve().parent
    frames = []
    traceback = error.__traceback__
    while traceback is not None:
        frames.append(Path(traceback.tb_frame.f_code.co_filename))
        traceback = traceback.tb_next
    # The first frame is ProviderGuard.develop itself, which only re-raises.
    for filename in reversed(frames[1:]):
        try:
            resolved = filename.resolve()
        except OSError:
            continue
        if resolved.parent == worker:
            return True
        if "rdagent" in resolved.parts:
            return False
    return False


class ProviderGuard:
    def __init__(
        self,
        component: Any,
        loop: Any,
        step: str,
        run: Path,
        calls: Path,
        run_id: str,
        skip_error: type[Exception],
        feedback_factory: Any,
    ) -> None:
        self.component, self.loop, self.step = component, loop, step
        self.run, self.calls, self.run_id = run, calls, run_id
        self.skip_error, self.feedback_factory = skip_error, feedback_factory
        if step == "coding" and hasattr(loop, "_propose"):
            # Installed at the existing guard wiring seam; no upstream loop override.
            proposal = ProviderGuard(
                loop._propose, loop, "proposal", run, calls, run_id, skip_error, feedback_factory
            )
            loop._propose = proposal.propose
            if hasattr(loop, "record"):
                loop.record = RoundRecord(loop.record, run)
            if hasattr(loop, "_exp_gen"):
                experiment = ProviderGuard(
                    loop._exp_gen,
                    loop,
                    "proposal",
                    run,
                    calls,
                    run_id,
                    skip_error,
                    feedback_factory,
                )
                loop._exp_gen = experiment.propose

    def __getattr__(self, name: str) -> Any:
        return getattr(object.__getattribute__(self, "component"), name)

    def _offset(self) -> int:
        return self.calls.stat().st_size if self.calls.exists() else 0

    def _failure(self, error: Exception, offset: int) -> dict[str, Any] | None:
        # Upstream discards the transport cause. Only new, matching chat receipts can attest
        # a provider failure; a stale receipt or an arbitrary coding exception cannot.
        if not self.calls.exists():
            return None
        with self.calls.open("rb") as stream:
            stream.seek(offset)
            raw = stream.read()
        calls = [json.loads(line) for line in raw[: raw.rfind(b"\n") + 1].splitlines()]
        chat = [
            r
            for r in calls
            if r.get("run_id") == self.run_id and r.get("endpoint") == "/v1/chat/completions"
        ]
        if not chat:
            return None
        last = chat[-1]
        code = last.get("error_code")
        if code == "budget_exhausted":
            raise SystemExit("budget exhausted; loop ended cleanly") from error
        if not (
            isinstance(error, RuntimeError) and "Failed to create chat completion" in str(error)
        ):
            return None
        if code not in last.get("provider_errors", []) and code not in {
            "provider_timeout",
            "codex_timeout",
            "provider_unavailable",
            "provider_error",
            "invalid_provider_response",
            "invalid_json_from_model",
        }:
            return None
        kind = (
            "provider_timeout"
            if code in {"provider_timeout", "codex_timeout"}
            else "provider_error"
        )
        # Upstream retries a failed call once (MAX_RETRY=2): the call's failed receipts are the
        # trailing run of failed chat receipts, and every one of their attempts was waited for.
        failed: list[dict[str, Any]] = []
        for receipt in reversed(chat):
            if not receipt.get("error_code"):
                break
            failed.append(receipt)
        return {
            "schema": "AlphaRdagentRoundV1",
            "iteration": self.round_index(),
            "status": "proposal_failed_" + kind
            if self.step == "proposal"
            else ROUND_STATUSES[kind],
            "reason": f"{self.step}: {code}",
            "step": self.step,
            "attempts": sum(int(r.get("attempts", 0)) for r in failed),
            "provider_wait_seconds": sum(float(r.get("latency_ms", 0)) for r in failed) / 1000,
            "trial_created": False,
        }

    def round_index(self) -> int:
        path = self.run / "steps.jsonl"
        if path.exists():
            for line in reversed(path.read_text().splitlines()):
                row = json.loads(line)
                step = "direct_exp_gen" if self.step == "proposal" else self.step
                if row.get("event") == "start" and row.get("step") == step:
                    return int(row["loop"])
        return int(self.loop.loop_idx)

    def _record(self, row: dict[str, Any], exp: Any) -> str:
        row["factor_names"] = [task.factor_name for task in getattr(exp, "sub_tasks", [])]
        row["trial_created"] = bool(getattr(exp, "alpha_evaluation", {}).get("factors"))
        with (self.run / "rounds.jsonl").open("a") as stream:
            stream.write(json.dumps(row, sort_keys=True) + "\n")
        return (
            f"{row['status']}: {self.step}; {row['attempts']} attempts, "
            f"{row['provider_wait_seconds']:g} seconds waited"
        )

    def propose(self, *args: Any, **kwargs: Any) -> Any:
        offset = self._offset()
        try:
            return self.component(*args, **kwargs)
        except Exception as error:
            row = self._failure(error, offset)
            if row is None:
                raise
            raise self.skip_error(self._record(row, None)) from error

    def develop(self, exp: Any) -> Any:
        offset = self._offset()
        try:
            return self.component.develop(exp)
        except Exception as error:
            row = self._failure(error, offset)
            if row is None:
                if self.step != "coding" or exp is None or self._loop_handles(error):
                    raise
                if raised_by_alpha(error):
                    raise  # A defect in ALPHA's own worker code is not a recoverable coder error.
                return self._recover_coding(exp, error)
            raise self.skip_error(self._record(row, exp)) from error

    def _loop_handles(self, error: Exception) -> bool:
        # Upstream's own round endings (CoderError "all tasks failed", FactorEmptyError) and
        # ALPHA's skip error keep the loop's existing skip/withdraw path and are never judged.
        handled = (
            self.skip_error,
            *_as_tuple(getattr(self.loop, "skip_loop_error", ())),
            *_as_tuple(getattr(self.loop, "withdraw_loop_error", ())),
        )
        return isinstance(error, handled)

    def _recover_coding(self, exp: Any, error: Exception) -> Any:
        completed = getattr(exp, "alpha_completed_coding", {})
        feedback = getattr(exp, "prop_dev_feedback", None)
        if feedback is not None:
            for task, workspace, result in zip(
                exp.sub_tasks, exp.sub_workspace_list, feedback, strict=True
            ):
                if workspace is not None and getattr(result, "value_generated_flag", False):
                    completed.setdefault(task.factor_name, (workspace, result))
        row = {
            "schema": "AlphaRdagentRoundV1",
            "iteration": self.round_index(),
            "status": ROUND_STATUSES["internal_error"],
            "step": "coding",
            "exception_type": type(error).__name__,
            "message": " ".join(str(error).split()),
            "factor_names": [t.factor_name for t in exp.sub_tasks],
            "factors": [
                {
                    "name": t.factor_name,
                    "trial_created": False,
                    "status": "coded" if t.factor_name in completed else "not_coded",
                }
                for t in exp.sub_tasks
            ],
        }
        exp.alpha_internal_coding = row
        if not completed:
            raise self.skip_error(
                f"{row['status']}: {row['exception_type']}: {row['message']}"
            ) from error
        recovered = copy(exp)
        recovered.sub_tasks = [t for t in exp.sub_tasks if t.factor_name in completed]
        recovered.sub_workspace_list = [completed[t.factor_name][0] for t in recovered.sub_tasks]
        recovered.prop_dev_feedback = [completed[t.factor_name][1] for t in recovered.sub_tasks]
        return recovered

    def generate_feedback(self, exp: Any, trace: Any, exception: Exception | None = None) -> Any:
        offset = self._offset()
        try:
            return self.component.generate_feedback(exp, trace, exception)
        except Exception as error:
            row = self._failure(error, offset)
            if row is None:
                raise
            # Feedback cannot skip backwards to itself. Close this round with a negative
            # feedback record and let upstream record/advance normally.
            return self.feedback_factory(
                observations="",
                reason=self._record(row, exp),
                decision=False,
                hypothesis_evaluation="provider failed",
                new_hypothesis="try a new round",
            )


class RoundFeedback:
    """Retain pre-coding refusals even when upstream bypasses the summarizer on a skip."""

    def __init__(self, original: Any) -> None:
        self.original = original

    def __call__(self, previous: dict[str, Any]) -> Any:
        feedback = self.original(previous)
        exp = (
            previous.get("running")
            or previous.get("coding")
            or (previous.get("direct_exp_gen") or {}).get("exp_gen")
        )
        if getattr(exp, "alpha_family_refusal", None):
            feedback.observations = ""
            feedback.reason += "\n" + "\n".join(getattr(exp, "alpha_refused_before_coding", []))
        failure = getattr(exp, "alpha_internal_coding", None)
        if failure:
            feedback.reason += (
                f"\n{failure['status']}: {failure['exception_type']}: {failure['message']}"
            )
        return feedback


class RoundRecord:
    """A failed proposal has a round row, but no experiment to add to the research trace."""

    def __init__(self, original: Any, run: Path) -> None:
        self.original, self.run = original, run
        self.internal_failures = 0

    def __call__(self, previous: dict[str, Any]) -> Any:
        proposal = previous.get("direct_exp_gen") or {}
        exp = previous.get("running") or previous.get("coding") or proposal.get("exp_gen")
        if exp is None:
            self.internal_failures = 0
            return None
        exp.alpha_run_dir = str(self.run)
        panel = self.run / "panel/panel-receipt.json"
        if panel.exists():
            exp.alpha_panel_sha256 = json.loads(panel.read_text())["panel_sha256"]
        result = self.original({**previous, "direct_exp_gen": proposal})
        row = getattr(exp, "alpha_internal_coding", None)
        self.internal_failures = self.internal_failures + 1 if row else 0
        if row:
            judged = {
                f["name"] for f in (getattr(exp, "alpha_evaluation", None) or {}).get("factors", [])
            }
            for factor in row["factors"]:
                factor["trial_created"] = factor["name"] in judged
            row["trial_created"] = bool(judged)
            with (self.run / "rounds.jsonl").open("a") as stream:
                stream.write(json.dumps(row, sort_keys=True) + "\n")
        if self.internal_failures >= 2:
            message = "Two consecutive rounds ended with an internal coding error; run stopped"
            (self.run / "loop-stop.json").write_text(json.dumps({"loop_reason": message}) + "\n")
            raise SystemExit(message)
        return result


class ExecutedFeedback:
    """Execution survived an internal error before the coder could return its feedback.

    A plain class, not a dataclass: tests load this file without registering it as a module.
    """

    def __init__(self, execution_feedback: str, final_decision: bool) -> None:
        self.execution_feedback, self.final_decision = execution_feedback, final_decision
        self.value_generated_flag = True

    def __bool__(self) -> bool:
        return self.final_decision


class CriticEvaluator:
    """Keep upstream execution/value feedback when its per-factor code opinion is unavailable.

    FactorEvaluatorForCoder calls code_evaluator.evaluate after executing and checking values.
    Only that call is recoverable here. The final opinion uses those existing value checks when
    the critic was unavailable. All wrappers are removed before upstream serialises knowledge.
    One instance lives for one coding round (including all its evolve attempts).
    """

    def __init__(self, evaluator: Any, guard: ProviderGuard, exp: Any = None) -> None:
        self.evaluator, self.guard = evaluator, guard
        self.exp = exp
        self.failure: dict[str, Any] | None = None
        self.unavailable: list[str] = []
        self.skipped: list[str] = []

    def evaluate(self, target_task: Any, implementation: Any, *args: Any, **kwargs: Any) -> Any:
        evaluator = self.evaluator
        code = evaluator.code_evaluator.evaluate
        value = evaluator.value_evaluator.evaluate
        final = evaluator.final_decision_evaluator.evaluate
        generated, value_decision, unavailable = False, None, False
        execute = implementation.execute if implementation is not None else None
        executed, execution_text = False, ""

        def execution(*eargs: Any, **ekwargs: Any) -> Any:
            nonlocal executed, execution_text
            if execute is None:
                raise RuntimeError("execution capture requires a workspace")
            result = execute(*eargs, **ekwargs)
            execution_text, values = result
            executed = values is not None
            return result

        def check_values(*vargs: Any, **vkwargs: Any) -> Any:
            nonlocal generated, value_decision
            result = value(*vargs, **vkwargs)
            generated, value_decision = True, result[1]
            return result

        def critic(*cargs: Any, **ckwargs: Any) -> Any:
            nonlocal unavailable
            name = target_task.factor_name
            if self.failure is None:
                offset = self.guard._offset()
                try:
                    return code(*cargs, **ckwargs)
                except Exception as error:
                    failure = self.guard._failure(error, offset)
                    if failure is None:
                        raise
                    self.failure = failure
                    self.unavailable.append(name)
            else:
                self.skipped.append(name)
            unavailable = True
            return self.note(), None

        def decide(*fargs: Any, **fkwargs: Any) -> Any:
            if unavailable:
                return generated and value_decision is not False, self.note()
            return final(*fargs, **fkwargs)

        evaluator.code_evaluator.evaluate = critic
        evaluator.value_evaluator.evaluate = check_values
        evaluator.final_decision_evaluator.evaluate = decide
        if implementation is not None and self.exp is not None:
            implementation.execute = execution
        try:
            try:
                result = evaluator.evaluate(target_task, implementation, *args, **kwargs)
            finally:
                evaluator.code_evaluator.evaluate = code
                evaluator.value_evaluator.evaluate = value
                evaluator.final_decision_evaluator.evaluate = final
                if implementation is not None and self.exp is not None:
                    implementation.execute = execute
        except Exception:
            if self.exp is not None and executed:
                self.exp.alpha_completed_coding[target_task.factor_name] = (
                    deepcopy(implementation),
                    ExecutedFeedback(str(execution_text), value_decision is not False),
                )
            raise
        if self.exp is not None and getattr(result, "value_generated_flag", False):
            self.exp.alpha_completed_coding[target_task.factor_name] = (
                deepcopy(implementation),
                deepcopy(result),
            )
        return result

    def note(self) -> str:
        if self.failure is None:
            raise RuntimeError("critic fallback requires an attested provider failure")
        cause = "timeout" if self.failure["status"].endswith("timeout") else "error"
        return f"code critic unavailable (provider {cause}); judged on execution only"

    def record(self) -> None:
        if self.failure is None:
            return
        unavailable, skipped = (
            list(dict.fromkeys(self.unavailable)),
            list(dict.fromkeys(self.skipped)),
        )
        row = {
            **self.failure,
            "status": self.failure["status"].replace("coding_failed_", "critic_unavailable_"),
            "step": "code_critic",
            "reason": self.note(),
            "critic_unavailable": len(unavailable),
            "critic_unavailable_factor_names": unavailable,
            "critic_skipped": len(skipped),
            "critic_skipped_factor_names": skipped,
            "factor_names": list(dict.fromkeys(unavailable + skipped)),
        }
        # Written before the runner: whether this round creates trials is not known here.
        row.pop("trial_created")
        with (self.guard.run / "rounds.jsonl").open("a") as stream:
            stream.write(json.dumps(row, sort_keys=True) + "\n")
