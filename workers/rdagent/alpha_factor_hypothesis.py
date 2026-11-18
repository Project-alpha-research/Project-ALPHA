"""Carry per-factor proposal text through the pinned experiment converter."""

from __future__ import annotations

import json
import os
from collections.abc import Callable
from typing import Any


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
