"""Isolated entry into the pinned upstream factor loop, using external class settings."""

from __future__ import annotations

import asyncio
import json
import os
import sys
from datetime import UTC, datetime
from functools import wraps
from pathlib import Path
from typing import TYPE_CHECKING, Any

# -I removes the script directory: add only ALPHA's worker scripts, never the source root.
WORKER = Path(__file__).resolve().parent
if str(WORKER) not in sys.path:
    sys.path.insert(0, str(WORKER))

if TYPE_CHECKING:
    from .research_memory import ProposalHistory, limit_restored_history, open_factor_loop
    from .source_pin import verify_source
    from .stock_fixture_entry import SourceFinder
else:
    from research_memory import ProposalHistory, limit_restored_history, open_factor_loop
    from source_pin import verify_source
    from stock_fixture_entry import SourceFinder


def install_source(source: Path) -> str:
    identity = verify_source(source)
    sys.meta_path.insert(0, SourceFinder(source))
    return identity


def _step_exception(loop: Any, li: int) -> Any:
    try:
        return loop.loop_prev_out[li].get(loop.EXCEPTION_KEY)
    except (AttributeError, KeyError, TypeError):
        return None


def record_steps(loop_class: Any) -> None:
    """Wrap the step runner with start/end lines (status ok, skipped or error).

    The start line is written before RD-Agent takes the step's semaphore, so with more than one
    loop in parallel a queued loop's start can precede the running one's end; ALPHA runs one loop
    at a time (RD-Agent's default parallelism of 1), where the intervals are exact.
    """
    run_dir = os.environ.get("ALPHA_FACTOR_RUN_DIR")
    if not run_dir:
        return
    path = Path(run_dir) / "steps.jsonl"
    original = loop_class._run_step

    def append(row: dict[str, Any]) -> None:
        with path.open("a") as stream:
            stream.write(
                json.dumps({**row, "ts": datetime.now(UTC).isoformat()}, sort_keys=True) + "\n"
            )

    @wraps(original)
    async def wrapped(self: Any, li: int, *args: Any, **kwargs: Any) -> Any:
        si = self.step_idx[li]
        row = {"schema": "AlphaRdagentStepV1", "loop": li, "step_index": si, "step": self.steps[si]}
        append({**row, "event": "start"})
        error_type, status = None, "ok"
        before = _step_exception(self, li)
        try:
            return await original(self, li, *args, **kwargs)
        except BaseException as error:
            error_type, status = type(error).__name__, "error"
            raise
        finally:
            # RD-Agent swallows its skip-loop errors (CoderError, FactorEmptyError) and stores
            # them under EXCEPTION_KEY, then jumps to feedback: record those steps as skipped.
            after = _step_exception(self, li)
            if status == "ok" and after is not None and after is not before:
                error_type, status = type(after).__name__, "skipped"
            append({**row, "event": "end", "status": status, "error_type": error_type})

    loop_class._run_step = wrapped


def main() -> None:
    if len(sys.argv) != 3 or sys.argv[2] not in {"1", "2", "3"}:
        raise ValueError("usage: factor_loop_entry.py <source> <loop_n: 1..3>")
    install_source(Path(sys.argv[1]))
    from rdagent.app.qlib_rd_loop.conf import FACTOR_PROP_SETTING
    from rdagent.app.qlib_rd_loop.factor import FactorRDLoop
    from rdagent.utils.workflow.loop import LoopBase

    record_steps(LoopBase)
    loop, total = open_factor_loop(FactorRDLoop, FACTOR_PROP_SETTING, int(sys.argv[2]), os.environ)
    if not isinstance(loop.hypothesis2experiment.prepare_context, ProposalHistory):
        limit_restored_history(loop, os.environ)
    loop._init_base_features(None)
    asyncio.run(loop.run(loop_n=total))


if __name__ == "__main__":
    main()
