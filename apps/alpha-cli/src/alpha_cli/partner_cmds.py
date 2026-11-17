"""An offline scorecard for the research partner's answer checker."""

from typing import Any

import typer

from alpha_cli._cli_json import emit
from alpha_cli.spine.honesty import run_selftest

partner_app = typer.Typer(
    help="Self-checks of the AI research partner's honesty tools.", no_args_is_help=True
)


def _scorecard(result: dict[str, Any]) -> str:
    lines = [
        f"Honesty self-test: {result['passed']} of {result['total']} "
        "planted answers were judged as expected."
    ]
    for scenario in result["scenarios"]:
        title = scenario["title"]
        got = ", ".join(scenario["got"]) or "none"
        expected = ", ".join(scenario["expected"])
        if scenario["ok"]:
            lines.append(
                f"PASS  honest answer accepted: {title}"
                if scenario["honest"]
                else f"PASS  caught: {title} ({got})"
            )
        else:
            lines.append(
                f"FAIL  honest answer rejected: {title} (got {got})"
                if scenario["honest"]
                else f"FAIL  missed: {title} (expected {expected}, got {got})"
            )
    lines.append(result["note"])
    return "\n".join(lines)


@partner_app.command("selftest")
def selftest(json_out: bool = typer.Option(False, "--json")) -> None:
    """Check planted honest and dishonest answers against temporary stored runs."""
    result = run_selftest()
    emit(result, json_out=json_out, fallback=_scorecard(result))
    if not result["ok"]:
        raise typer.Exit(1)
