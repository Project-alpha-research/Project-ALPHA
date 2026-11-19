"""One command from an owner's idea to recorded, visible multi-asset rule trials."""

from __future__ import annotations

import sys
from contextlib import redirect_stdout
from pathlib import Path

import typer

from alpha_cli._cli_json import emit
from alpha_cli.spine.data_health import health_sentence
from alpha_cli.spine.errors import SpineError, fail, test_error
from alpha_cli.spine.run import run_idea
from alpha_cli.spine.spec import load_spec
from alpha_cli.spine.stores import _stores
from alpha_core import DataError
from alpha_core.config import AlphaSettings


def test_rule(
    spec: Path | None = typer.Argument(None, help="Idea spec (.toml or .json)."),  # noqa: B008
    rule: str | None = typer.Option(None, help="ma_cross | breakout | tsmom"),
    param: list[str] | None = typer.Option(None, help="Rule parameter name=value (repeatable)."),  # noqa: B008
    asset: list[str] | None = typer.Option(None, help="Symbol or symbol@store (repeatable)."),  # noqa: B008
    name: str | None = None,
    idea: str | None = None,
    idea_card: str | None = typer.Option(None, help="Id of the idea card for this test."),
    fee_bps: float | None = None,
    slippage_bps: float | None = None,
    quick: bool = typer.Option(
        False, help="Small gauntlet (20/4/4 paths, 50 resamples); labelled quick."
    ),
    no_diagnose: bool = typer.Option(
        False, "--no-diagnose", help="Skip automatic diagnostics; labelled no-diagnostics."
    ),
    check_data: bool = typer.Option(
        False, "--check-data", help="Compute missing or out-of-date daily health reports."
    ),
    accept_bad_data: str | None = typer.Option(
        None,
        "--accept-bad-data",
        help="Proceed after a failed health check for this run. Give a reason.",
    ),
    json_out: bool = typer.Option(False, "--json", help="Emit one JSON result object."),
) -> None:
    """Test a long/flat trading rule on several assets and record every trial."""
    settings = AlphaSettings()
    try:
        parsed = load_spec(
            spec,
            rule=rule,
            param=param,
            asset=asset,
            name=name,
            idea=idea,
            idea_card=idea_card,
            fee_bps=fee_bps,
            slippage_bps=slippage_bps,
        )
        with redirect_stdout(sys.stderr if json_out else sys.stdout):
            output = run_idea(
                parsed,
                home=settings.data_dir,
                seed=settings.random_seed,
                quick=quick,
                check_data=check_data,
                accept_bad_data=accept_bad_data,
                no_diagnose=no_diagnose,
            )
        if all(result["error"] is not None for result in output["results"]):
            fail(
                test_error(
                    "; ".join(result["error"] for result in output["results"]),
                    list(_stores(settings.data_dir)),
                ),
                json_out,
            )
    except SpineError as exc:
        fail(exc, json_out)
    except (ValueError, OSError, DataError) as exc:
        fail(test_error(str(exc)), json_out)
    lines = [
        f"Test {output['test_id']} — {output['name']} (trials total: {output['trials_total']})",
        "ASSET\tRUN\tVERDICT\tOOS SHARPE\tLABELS / ERROR",
    ]
    for result in output["results"]:
        sharpe = result["oos_sharpe"]
        lines.append(
            "\t".join(
                (
                    result["asset"],
                    result["run_id"] or "—",
                    result["verdict"] or "—",
                    f"{sharpe:.3f}" if sharpe is not None else "—",
                    result["error"] or ", ".join(result["labels"]),
                )
            )
        )
        if result.get("data_health"):
            lines.append(health_sentence(result["data_health"]))
    emit(output, json_out=json_out, fallback="\n".join(lines))
