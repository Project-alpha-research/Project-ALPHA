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

from typing import Any

from rdagent.components.coder.factor_coder import FactorCoSTEER


class AlphaFactorCoSTEER(FactorCoSTEER):
    def develop(self, exp: Any) -> Any:
        self.rag.current_generated_trace_count = 0
        return super().develop(exp)
