"""Carry per-factor proposal text through the pinned experiment converter."""

from __future__ import annotations

import json
import os
from collections.abc import Callable
from copy import copy
from typing import Any


def built_hypothesis(hypothesis: Any, tasks: list[Any]) -> Any:
    """Project individual task hypotheses when the original could describe unbuilt ideas."""
    view = copy(hypothesis)
    view.hypothesis = "\n".join(f"{task.factor_name}: {task.description}" for task in tasks)
    for field in (
        "reason",
        "concise_reason",
        "concise_observation",
        "concise_justification",
        "concise_knowledge",
    ):
        setattr(view, field, "")
    return view


def discussion_excluded_ideas(decision: dict[str, Any]) -> bool:
    reply = decision.get("reply")
    return bool(decision.get("refused")) or (
        isinstance(reply, dict)
        and any(choice["action"] == "drop" for choice in reply["ideas"].values())
    )


def discussion_history(trace: Any) -> Any:
    """Render a copy of past discussion rounds without quoting their mixed hypotheses."""
    history = getattr(trace, "hist", None)
    if not history:
        return trace
    pairs = []
    for exp, feedback in history:
        if discussion_excluded_ideas(getattr(exp, "discussion", {})):
            exp = copy(exp)
            exp.hypothesis = built_hypothesis(exp.hypothesis, exp.sub_tasks)
            # Feedback from a saved run may also quote or suggest variants of the old idea.
            if feedback is not None:
                feedback = copy(feedback)
                for field in ("observations", "hypothesis_evaluation", "new_hypothesis", "reason"):
                    setattr(feedback, field, "")
        pairs.append((exp, feedback))
    view = copy(trace)
    view.hist = pairs
    return view


class ProposalResponse:
    def __init__(self, original: Callable[..., Any]) -> None:
        self.original = original

    def __call__(self, response: str, hypothesis: Any, trace: Any) -> Any:
        experiment = self.original(response, hypothesis, trace)
        ideas = json.loads(response)
        for task in experiment.sub_tasks:
            idea = ideas[task.factor_name]
            # A nested object fits the pinned converter's dict[str, str | dict] value
            # schema even if the model supplied a non-text summary.
            metadata = idea.get("proposal_metadata")
            fields = metadata if isinstance(metadata, dict) else idea
            task.plain_summary = fields.get("plain_summary")
            if os.environ.get("ALPHA_FACTOR_DISCUSS") == "1":
                task.planned_columns = fields.get("input_columns")
        return experiment
