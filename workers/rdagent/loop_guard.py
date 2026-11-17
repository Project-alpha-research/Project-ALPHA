"""ALPHA round boundary for exhausted gateway chat failures; upstream stays unchanged."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


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
        return {
            "schema": "AlphaRdagentRoundV1",
            "iteration": self.round_index(),
            "status": f"coding_failed_{kind}",
            "reason": f"{self.step}: {code}",
            "step": self.step,
            "attempts": int(last.get("attempts", 0)),
            "provider_wait_seconds": float(last.get("latency_ms", 0)) / 1000,
            "trial_created": False,
        }

    def round_index(self) -> int:
        path = self.run / "steps.jsonl"
        if path.exists():
            for line in reversed(path.read_text().splitlines()):
                row = json.loads(line)
                if row.get("event") == "start" and row.get("step") == self.step:
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
            or previous.get("direct_exp_gen", {}).get("exp_gen")
        )
        if getattr(exp, "alpha_family_refusal", None):
            feedback.observations = ""
            feedback.reason += "\n" + "\n".join(getattr(exp, "alpha_refused_before_coding", []))
        return feedback
