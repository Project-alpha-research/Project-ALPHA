"""`alpha research compare`: what the command reads and says about the held-back boundary."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from alpha_cli import _runner
from alpha_cli.spine import reserve

# kronos needs a precomputed forecast cache (built by backtest/validate/optim, not this
# lightweight comparison spec) and rules needs an owner-saved rule set (--rules), so
# exclude both from the default all-strategies sweep.
SWEEP_EXCLUDED = {"kronos", "rules"}


def held_bars(symbol: str, data_dir: Path) -> tuple[list[Any], reserve.Hold]:
    """The symbol's bars up to the held-back boundary, and what was held back."""
    held = reserve.hold(symbol, data_dir=data_dir)
    bars, _ = _runner.load_bars(symbol, data_dir=data_dir, as_of=held.as_of)
    return bars, held


def held_fields(held: reserve.Hold) -> dict[str, Any]:
    """The payload keys: the cut-off, record and plain sentence; none unless bars were held back."""
    return {**held.identity(), "reserve_sentence": held.say()} if held.held_back else {}
