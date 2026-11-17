"""Investigation tools on a recorded rule test: market attribution, regimes and change points."""

from __future__ import annotations

import sys
from collections.abc import Callable
from contextlib import redirect_stdout
from pathlib import Path
from typing import Any

import typer

from alpha_cli._cli_json import emit
from alpha_cli.spine.errors import fail, tool_error
from alpha_cli.spine.facts import METRICS
from alpha_cli.spine.stores import _stores
from alpha_core import DataError
from alpha_core.config import AlphaSettings

tool_app = typer.Typer(
    help="Investigate a recorded rule test: market exposure, market regimes and change points.",
    no_args_is_help=True,
)
_JSON = typer.Option(False, "--json", help="Emit one JSON result object.")


def _text(output: dict[str, Any]) -> str:
    """Plain-English summary: each stored fact with its meaning, then where it was saved."""
    lines = [f"{output['tool']} of run {output['run_id']} [{', '.join(output['labels'])}]"]
    for fact in output["facts"]:
        value = "unavailable" if fact["value"] is None else f"{fact['value']:.4g}"
        lines.append(f"  {fact['metric']} = {value}: {METRICS[fact['metric']]}")
        if fact["reason"]:
            lines.append(f"    reason: {fact['reason']}")
    result = output["result"]
    join = result.get("join")
    if join and (join["run_bars_dropped"] or join["other_bars_dropped"]):
        lines.append(
            f"  Matching dates dropped {join['run_bars_dropped']} of {join['run_bars']} run bars "
            f"and {join['other_bars_dropped']} bars of the other asset."
        )
    lines.extend(f"  Note: {flag['detail']}" for flag in result.get("flags", []))
    lines.extend(f"  Change on {item['date'][:10]}" for item in result.get("breaks", []))
    lines.append(f"  Basis: {output['basis']}")
    lines.append(f"  Saved: {output['file']} (ledger rows: {output['trials_total']})")
    return "\n".join(lines)


def _run(call: Callable[[Path], dict[str, Any]], json_out: bool) -> None:
    """Run one tool; progress goes to stderr, one result or error envelope to stdout."""
    home = AlphaSettings().data_dir
    try:
        with redirect_stdout(sys.stderr if json_out else sys.stdout):
            output = call(home)
    except (ValueError, OSError, DataError) as exc:
        fail(tool_error(exc, list(_stores(home))), json_out)
    # Per-bar series stay in the saved file; the printed result is the summary.
    printed = {**output, "result": {k: v for k, v in output["result"].items() if k != "series"}}
    emit(printed, json_out=json_out, fallback=_text(output))


@tool_app.command("attribution")
def attribution_command(
    run_id: str,
    benchmark: str | None = typer.Option(
        None, help="Benchmark SYMBOL or SYMBOL@store (default: the run's own asset)."
    ),
    json_out: bool = _JSON,
) -> None:
    """How much of the run's return is benchmark exposure (beta) and what is left (alpha)."""
    from alpha_cli.spine import tools

    _run(lambda home: tools.attribution(home, run_id, benchmark), json_out)


@tool_app.command("regimes")
def regimes_command(
    run_id: str,
    market: str | None = typer.Option(
        None, help="Market SYMBOL or SYMBOL@store (default: the run's own asset)."
    ),
    k: int = typer.Option(2, min=2, max=4, help="Number of market regimes."),
    json_out: bool = _JSON,
) -> None:
    """Whether the run earns its return in calm or in turbulent markets."""
    from alpha_cli.spine import tools

    _run(lambda home: tools.regimes(home, run_id, market, k), json_out)


@tool_app.command("changepoints")
def changepoints_command(
    run_id: str,
    on: str = typer.Option("returns", help="Series to search: returns | equity."),
    json_out: bool = _JSON,
) -> None:
    """Dates at which the run's behaviour shifted; a hindsight description, never a signal."""
    from alpha_cli.spine import tools

    _run(lambda home: tools.changepoints(home, run_id, on), json_out)
