"""Isolated entry into the pinned upstream factor loop, using external class settings."""

from __future__ import annotations

import asyncio
import json
import os
import sys
from datetime import UTC, datetime
from functools import wraps
from pathlib import Path
from typing import Any

# -I removes the script directory: add only ALPHA's worker scripts, never the source root.
WORKER = Path(__file__).resolve().parent
if str(WORKER) not in sys.path:
    sys.path.insert(0, str(WORKER))

from research_memory import open_factor_loop  # noqa: E402
from source_pin import verify_source  # noqa: E402
from stock_fixture_entry import SourceFinder  # noqa: E402


def install_source(source: Path) -> str:
    identity = verify_source(source)
    sys.meta_path.insert(0, SourceFinder(source))
    return identity


def record_steps(loop_class: Any) -> None:
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
        error_type = None
        try:
            return await original(self, li, *args, **kwargs)
        except BaseException as error:
            error_type = type(error).__name__
            raise
        finally:
            append(
                {
                    **row,
                    "event": "end",
                    "status": "error" if error_type else "ok",
                    "error_type": error_type,
                }
            )

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
    loop._init_base_features(None)
    asyncio.run(loop.run(loop_n=total))


if __name__ == "__main__":
    main()
