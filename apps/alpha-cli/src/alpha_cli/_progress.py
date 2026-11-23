"""A progress line for a command that runs for a long time. It changes no number and no file."""

from __future__ import annotations

import functools
import threading
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import Any

import typer

EVERY_SECONDS = 10.0


@contextmanager
def heartbeat(
    label: str | Callable[[], str],
    every: float = EVERY_SECONDS,
    expected: float | None = None,
    detail: Callable[[float], str] | None = None,
) -> Iterator[None]:
    """Print `label: still running, N seconds so far` to stderr every `every` seconds.

    ``label`` may be a function, so the line can name the stage the command has reached.
    With ``expected`` (a rough estimate in seconds) the line also says how long the run should
    take; once the run passes it, the line says "taking longer than expected; still running".
    ``detail`` maps the seconds so far to a short phrase added to each line (such as "fold 3 of 8").
    A run shorter than `every` prints nothing. stderr keeps `--json` output on stdout clean.
    """
    of = f" of about {round(expected)} expected" if expected is not None else ""
    stop = threading.Event()
    started = time.monotonic()

    def beat() -> None:
        while not stop.wait(every):
            elapsed = time.monotonic() - started
            seconds = round(elapsed)
            late = expected is not None and elapsed > expected
            state = "taking longer than expected; still running" if late else "still running"
            extra = f", {detail(elapsed)}" if detail is not None else ""
            name = label() if callable(label) else label
            typer.echo(
                f"{name}: {state}, {seconds} seconds so far{'' if late else of}{extra}.", err=True
            )

    thread = threading.Thread(target=beat, daemon=True)
    thread.start()
    try:
        yield
    finally:
        stop.set()
        thread.join()


def with_heartbeat(label: str) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Run the command inside `heartbeat(label)`; the command keeps its own signature."""

    def wrap(command: Callable[..., Any]) -> Callable[..., Any]:
        @functools.wraps(command)
        def run(*args: Any, **kwargs: Any) -> Any:
            with heartbeat(label):
                return command(*args, **kwargs)

        return run

    return wrap
