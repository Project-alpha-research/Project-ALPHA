"""Causal changes to a rule's signals for engine re-runs: later entries, later exits, skips.

Each change wraps the built strategy's own ``_signal``: the rule still decides on the close of
each bar from its own history, and the change reads only signals up to that bar. The engine then
fills at the next open as always. Each is a frozen value, so it pickles to a spawn worker.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class EntryDelay:
    """Enter ``bars`` bars after the rule says; leave when it says. A trade shorter than the
    delay is never entered. Uses only the rule's signals up to the decision bar."""

    bars: int

    def attach(self, strategy: Any) -> None:
        original, raw = strategy._signal, []

        def delayed() -> int:
            raw.append(int(original()))
            recent = raw[-(self.bars + 1) :]
            held = len(recent) == self.bars + 1 and all(value > 0 for value in recent)
            return 1 if held else min(raw[-1], 0)

        object.__setattr__(strategy, "_signal", delayed)


@dataclass(frozen=True)
class ExitDelay:
    """Leave ``bars`` bars after the rule says; enter when it says."""

    bars: int

    def attach(self, strategy: Any) -> None:
        original, raw = strategy._signal, []

        def delayed() -> int:
            raw.append(int(original()))
            held = any(value > 0 for value in raw[-(self.bars + 1) :])
            return 1 if held else min(raw[-1], 0)

        object.__setattr__(strategy, "_signal", delayed)


@dataclass(frozen=True)
class SkipEntries:
    """Skip each entry the rule makes with chance ``share``, drawn from ``seed`` in order."""

    share: float
    seed: int

    def attach(self, strategy: Any) -> None:
        from numpy.random import default_rng

        original, rng = strategy._signal, default_rng(self.seed)
        state = {"long": False, "kept": True}

        def skipped() -> int:
            value = int(original())
            if value > 0 and not state["long"]:
                state["kept"] = bool(rng.random() >= self.share)
            state["long"] = value > 0
            return value if value <= 0 or state["kept"] else 0

        object.__setattr__(strategy, "_signal", skipped)


SignalChange = EntryDelay | ExitDelay | SkipEntries
