"""RD-Agent's own factor coder, with one upstream counter restarted per experiment.

Selected through RD-Agent's setting ``QLIB_FACTOR_CODER``; RD-Agent's files stay unmodified.

Upstream defect (pinned 484776c, ``rdagent/components/coder/CoSTEER/knowledge_management.py``,
``CoSTEERRAGStrategyV2``): ``current_generated_trace_count`` remembers how many evolve steps were
already turned into knowledge, but every ``CoSTEER.develop`` call starts a new, empty evolving
trace while the counter keeps the previous experiment's length. ``generate_knowledge`` then skips
the first steps of every later experiment, so in one run usually only the first experiment's
coding attempts reach the persistent knowledge base (seen 2026-11-15: two rounds, seven factors
coded, four recorded). Restarting the counter before each experiment records every attempt.
Proposed upstream patch: reset the counter in ``CoSTEER.develop`` (or key it by trace identity).
"""

from __future__ import annotations

import os
import tempfile
from collections.abc import Mapping, Sequence
from contextlib import nullcontext
from pathlib import Path
from typing import Any

from filelock import FileLock
from rdagent.components.coder.factor_coder import FactorCoSTEER
from rdagent.core.serialization import dump, load


def demote(knowledge: Any, task_informations: Sequence[str]) -> list[str]:
    """Retain rejected code and its history, removing both successful retrieval paths."""
    demoted = []
    for information in dict.fromkeys(task_informations):
        changed = information in knowledge.success_task_to_knowledge_dict
        knowledge.success_task_to_knowledge_dict.pop(information, None)
        for node_id, unit in knowledge.node_to_implementation_knowledge_dict.items():
            if unit.target_task.get_task_information() != information:
                continue
            node = knowledge.graph.nodes[node_id]
            if node.label == "task_success_implement":
                node.label = "alpha_rejected_implement"
                changed = True
        if changed:
            demoted.append(information)
    return demoted


def demote_in_file(
    environ: Mapping[str, str], task_informations: Sequence[str]
) -> tuple[list[str], str | None]:
    """A memory failure is advisory; report it without stopping the research run."""
    try:
        name = environ.get("FACTOR_CoSTEER_new_knowledge_base_path")
        if not name or not Path(name).exists():
            return [], "no persistent coding memory"
        path = Path(name)
        lock = (
            FileLock(environ["FACTOR_CoSTEER_filelock_path"])
            if environ.get("FACTOR_CoSTEER_enable_filelock", "False").lower() == "true"
            else nullcontext()
        )
        with lock:
            with path.open("rb") as stream:
                knowledge = load(stream)
            demoted = demote(knowledge, task_informations)
            descriptor, temporary = tempfile.mkstemp(prefix=".coder-verdict-", dir=path.parent)
            try:
                with os.fdopen(descriptor, "wb") as stream:
                    dump(knowledge, stream)
                    stream.flush()
                    os.fsync(stream.fileno())
                os.replace(temporary, path)
            finally:
                Path(temporary).unlink(missing_ok=True)
        return demoted, None
    except Exception as error:  # Memory demotion must never abort the runner.
        return [], f"{type(error).__name__}: {error}"


class AlphaFactorCoSTEER(FactorCoSTEER):
    def develop(self, exp: Any) -> Any:
        if self.rag.dump_knowledge_base_path is not None:
            lock = (
                FileLock(self.settings.filelock_path)
                if self.settings.enable_filelock
                else nullcontext()
            )
            with lock:
                self.rag.load_dumped_knowledge_base()
        self.rag.current_generated_trace_count = 0
        return super().develop(exp)
