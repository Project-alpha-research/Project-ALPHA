"""One line on stderr for an old command that still works but has a new home."""

from __future__ import annotations

import functools
from collections.abc import Callable
from typing import Any

import typer

_WRAPPED: set[tuple[int, str]] = set()


def announce(group: typer.Typer, old: str, new: str) -> None:
    """Wrap the old command once. Its output and exit code are unchanged."""
    for info in group.registered_commands:
        callback = info.callback
        name = info.name or (callback.__name__ if callback is not None else "")
        if callback is None or name != old or (id(group), old) in _WRAPPED:
            continue
        info.callback = _wrapped(callback, new)
        _WRAPPED.add((id(group), old))


def _wrapped(callback: Callable[..., Any], new: str) -> Callable[..., Any]:
    @functools.wraps(callback)
    def run(*args: Any, **kwargs: Any) -> Any:
        typer.echo(f"This command moved. Use `{new}` (no project needed).", err=True)
        return callback(*args, **kwargs)

    return run
