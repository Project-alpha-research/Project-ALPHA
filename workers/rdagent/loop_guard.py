"""ALPHA round boundary for exhausted gateway chat failures; upstream stays unchanged."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

# The round outcomes this guard records; the Workstation reader has a sentence for each.
ROUND_STATUSES = {
    "provider_timeout": "coding_failed_provider_timeout",
    "provider_error": "coding_failed_provider_error",
}


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
                raise
            raise self.skip_error(self._record(row, exp)) from error

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
        return feedback


class RoundRecord:
    """A failed proposal has a round row, but no experiment to add to the research trace."""

    def __init__(self, original: Any, run: Path) -> None:
        self.original, self.run = original, run

    def __call__(self, previous: dict[str, Any]) -> Any:
        proposal = previous.get("direct_exp_gen") or {}
        exp = previous.get("running") or previous.get("coding") or proposal.get("exp_gen")
        if exp is None:
            return None
        panel = self.run / "panel/panel-receipt.json"
        if panel.exists():
            exp.alpha_panel_sha256 = json.loads(panel.read_text())["panel_sha256"]
        return self.original({**previous, "direct_exp_gen": proposal})


class CriticEvaluator:
    """Keep upstream execution/value feedback when its per-factor code opinion is unavailable.

    FactorEvaluatorForCoder calls code_evaluator.evaluate after executing and checking values.
    Only that call is recoverable here. The final opinion uses those existing value checks when
    the critic was unavailable. All wrappers are removed before upstream serialises knowledge.
    One instance lives for one coding round (including all its evolve attempts).
    """

    def __init__(self, evaluator: Any, guard: ProviderGuard) -> None:
        self.evaluator, self.guard = evaluator, guard
        self.failure: dict[str, Any] | None = None
        self.unavailable: list[str] = []
        self.skipped: list[str] = []

    def evaluate(self, target_task: Any, implementation: Any, *args: Any, **kwargs: Any) -> Any:
        evaluator = self.evaluator
        code = evaluator.code_evaluator.evaluate
        value = evaluator.value_evaluator.evaluate
        final = evaluator.final_decision_evaluator.evaluate
        generated, value_decision, unavailable = False, None, False

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
        try:
            return evaluator.evaluate(target_task, implementation, *args, **kwargs)
        finally:
            evaluator.code_evaluator.evaluate = code
            evaluator.value_evaluator.evaluate = value
            evaluator.final_decision_evaluator.evaluate = final

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
