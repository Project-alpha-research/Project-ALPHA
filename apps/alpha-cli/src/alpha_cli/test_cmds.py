"""One command from an owner's idea to recorded, visible multi-asset rule trials."""

from __future__ import annotations

import io
import re
import sys
from collections.abc import Callable
from contextlib import redirect_stdout
from pathlib import Path
from typing import Any

import typer

from alpha_cli._cli_json import emit
from alpha_cli._estimate import UnitTimer, read_rate, say_minutes, write_rate
from alpha_cli._progress import heartbeat
from alpha_cli.spine.data_health import health_sentence
from alpha_cli.spine.errors import SpineError, fail, test_error
from alpha_cli.spine.label_meaning import label_block
from alpha_cli.spine.owner_reading import variant_lines
from alpha_cli.spine.reading import reading_text, reading_word
from alpha_cli.spine.recheck import MISMATCH_EXIT, recheck_idea
from alpha_cli.spine.run import run_idea
from alpha_cli.spine.spec import IdeaSpec, load_spec
from alpha_cli.spine.stores import _stores
from alpha_core import DataError
from alpha_core.config import AlphaSettings


def _echo_notes(text: str) -> None:
    """What the run printed while it worked: warnings first, then the places files were saved."""
    lines = [line for line in text.splitlines() if line.strip()]
    paths = [line for line in lines if "saved to:" in line or line.startswith("Figure")]
    for line in [*(line for line in lines if line not in paths), *paths]:
        typer.echo(line)


def rate_key(quick: bool, kind: str, no_diagnose: bool) -> str:
    """One kept rate per kind of test: an owner rule costs more per asset than a built-in one."""
    return f"test_asset:{kind}{':quick' if quick else ''}{':no-diagnose' if no_diagnose else ''}"


def expected_line(expected: float | None, *, units: int) -> str:
    """The first line: a time from the last run on this computer, or when one will follow."""
    if expected is None:
        when = "after the first asset is tested" if units > 1 else "from the next run on"
        return (
            f"alpha test: no time estimate yet; this computer has not timed a test. "
            f"One follows {when}. Progress lines follow about every 10 seconds."
        )
    return (
        f"alpha test: this takes {say_minutes(expected)} (from the last test on this computer); "
        "a busy machine takes longer. Progress lines follow about every 10 seconds."
    )


class RunClock:
    """Times the assets of one `alpha test` run and re-states the estimate once, when measured."""

    def __init__(self, units: int, prior: float | None, say: Callable[[str], None]) -> None:
        self.timer = UnitTimer(units, prior_per_unit=prior)
        self._say = say

    def stage(self, text: str) -> None:
        """Called as each stage begins; "testing X (n of N)" marks the start of asset n."""
        found = re.fullmatch(r"testing .+ \(\d+ of \d+\)", text)
        if found is None:
            return
        if not self.timer.started:  # the first asset tested; an unreadable one is skipped
            self.timer.start()
            return
        self.timer.finish_unit()
        expected = self.timer.expected()
        if self.timer.done == 1 and expected is not None:
            self._say(f"alpha test: measured on the first asset: {say_minutes(expected)} in all.")

    def finish(self, data_dir: Path, key: str, results: list[dict[str, Any]]) -> None:
        """Keep the rate of this run for the next first guess, when every asset was tested.

        A repeat is read from the stored run and a failed asset stops early: neither is a rate."""
        if not self.timer.started:
            return
        self.timer.finish_unit()
        if all(row.get("executed") is True and row.get("error") is None for row in results):
            write_rate(data_dir, key, self.timer.per_unit() or 0.0)


def _start_progress(
    parsed: IdeaSpec, settings: AlphaSettings, key: str
) -> tuple[RunClock, list[str], Callable[[str], None]]:
    """Print the time estimate; return the clock, the current stage, and the stage reporter.

    A normal test and a recheck both use it, so both tell the owner how long to wait."""
    clock = RunClock(
        len(parsed.assets),
        read_rate(settings.data_dir, key),
        lambda line: typer.echo(line, err=True),
    )
    typer.echo(expected_line(clock.timer.expected(), units=len(parsed.assets)), err=True)
    stage = ["starting"]

    def note_stage(text: str) -> None:
        stage[0] = text
        clock.stage(text)

    return clock, stage, note_stage


def _reading_count(home: Path, result: dict[str, Any]) -> list[str]:
    """The stored deflated-Sharpe count of this reading, tied to the headline count of tries."""
    from alpha_cli import _artifacts
    from alpha_cli.spine.facts import read_json
    from alpha_cli.spine.tries import reading_count_sentence

    if not result.get("run_id"):
        return []
    diagnostics = read_json(_artifacts.run_dir(home, result["run_id"]) / "diagnostics.json")
    family = (diagnostics.get("trials") or {}).get("family")
    said = reading_count_sentence(family, result["symbol"]) if isinstance(family, dict) else None
    return [said] if said else []


def _recheck_lines(output: dict[str, Any]) -> list[str]:
    lines = []
    for result in output["results"]:
        found, asset = result["recheck"], result["asset"]
        if result["error"]:
            lines.append(f"{asset}: {result['error']}")
        elif found["match"] is None:
            lines.append(
                f"{asset}: {found['reason']}. Run `alpha test <spec>` once first; "
                "a recheck never creates the stored result."
            )
        else:
            code = "the code changed since" if found["code_changed"] else "the code is the same as"
            if found["match"]:
                exact = "bit for bit" if found["bit_identical"] else "within the tolerance"
                head = f"the same result, {exact}"
            else:
                head = f"a different result ({found['differences_total']} differences)"
            lines.append(
                f"{asset}: computed again in {found['seconds']:.1f} s and compared with run "
                f"{found['compared_with']}: {head}; {code} the stored run."
            )
            if found.get("identity_note"):
                lines.append(f"  {found['identity_note']}")
            lines.extend(
                f"  {d['field']}: stored {d['stored']}, recomputed {d['recomputed']}"
                for d in found["differences"]
            )
    return lines


def _recheck(
    parsed: IdeaSpec,
    settings: AlphaSettings,
    quick: bool,
    accept_bad_data: str | None,
    check_data: bool,
    json_out: bool,
) -> None:
    """`recheck`: computed again and compared with the stored result. Never writes."""
    if check_data:
        fail(
            SpineError(
                "BAD_OPTION",
                "--recheck cannot be used with --check-data: a health report writes a file, "
                "and a recheck writes nothing.",
                "Run alpha data health first, then alpha test --recheck.",
            ),
            json_out,
        )
    key = rate_key(quick, parsed.rule.kind, False)
    clock, stage, note_stage = _start_progress(parsed, settings, key)
    with (
        heartbeat(lambda: f"alpha test: {stage[0]}", expected=clock.timer.expected),
        redirect_stdout(sys.stderr if json_out else sys.stdout),
    ):
        output = recheck_idea(
            parsed,
            home=settings.data_dir,
            seed=settings.random_seed,
            quick=quick,
            accept_bad_data=accept_bad_data,
            stage=note_stage,
        )
    if all(result["error"] is not None for result in output["results"]):
        fail(
            test_error(
                "; ".join(result["error"] for result in output["results"]),
                list(_stores(settings.data_dir)),
            ),
            json_out,
        )
    emit(output, json_out=json_out, fallback="\n".join(_recheck_lines(output)))
    if any(r["recheck"]["match"] is False for r in output["results"]):
        raise typer.Exit(MISMATCH_EXIT)


def _plan_only(
    parsed: IdeaSpec, plan: bool, recheck: bool, settings: AlphaSettings, json_out: bool
) -> None:
    """`--plan`, and the refusal of a context spec without it. Never runs the engine."""
    from alpha_cli._context_plan import REFUSAL, plan_idea, plan_lines

    if not plan:
        fail(SpineError("GATED_ENGINE_MISSING", REFUSAL, "Run alpha test <spec> --plan."), json_out)
    if parsed.context is None or recheck:
        message = (
            "--plan describes a context gate; this spec has none."
            if parsed.context is None
            else "--plan cannot be used with --recheck."
        )
        fail(SpineError("BAD_OPTION", message, "Run alpha test without --plan."), json_out)
    output = plan_idea(parsed, home=settings.data_dir)
    if all(result["error"] is not None for result in output["results"]):
        errors = "; ".join(result["error"] for result in output["results"])
        fail(test_error(errors, list(_stores(settings.data_dir))), json_out)
    emit(output, json_out=json_out, fallback="\n".join(plan_lines(output)))


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
    recheck: bool = typer.Option(
        False,
        "--recheck",
        help="Compute the test again and compare it with the stored result. Writes nothing. "
        "Exit 4 if the two differ.",
    ),
    plan: bool = typer.Option(
        False,
        "--plan",
        help="For a spec with a context gate: describe the gate per asset. Runs no engine, "
        "writes nothing.",
    ),
    json_out: bool = typer.Option(False, "--json", help="Emit one JSON result object."),
) -> None:
    """Test a long/flat trading rule on several assets and record every trial."""
    settings = AlphaSettings()
    notes = io.StringIO()
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
        if plan or parsed.context is not None:
            _plan_only(parsed, plan, recheck, settings, json_out)
            return
        if recheck:
            _recheck(parsed, settings, quick, accept_bad_data, check_data, json_out)
            return
        key = rate_key(quick, parsed.rule.kind, no_diagnose)
        clock, stage, note_stage = _start_progress(parsed, settings, key)
        with (
            heartbeat(lambda: f"alpha test: {stage[0]}", expected=clock.timer.expected),
            redirect_stdout(sys.stderr if json_out else notes),
        ):
            output = run_idea(
                parsed,
                home=settings.data_dir,
                seed=settings.random_seed,
                quick=quick,
                check_data=check_data,
                accept_bad_data=accept_bad_data,
                no_diagnose=no_diagnose,
                stage=note_stage,
            )
            clock.finish(settings.data_dir, key, output["results"])
        if all(result["error"] is not None for result in output["results"]):
            _echo_notes(notes.getvalue())
            fail(
                test_error(
                    "; ".join(result["error"] for result in output["results"]),
                    list(_stores(settings.data_dir)),
                ),
                json_out,
            )
    except SpineError as exc:
        _echo_notes(notes.getvalue())
        fail(exc, json_out)
    except (ValueError, OSError, DataError) as exc:
        _echo_notes(notes.getvalue())
        fail(test_error(str(exc)), json_out)
    from alpha_cli.spine.trial_reader import spine_snapshot
    from alpha_cli.spine.tries import sentence, tries

    snapshot = spine_snapshot(settings.data_dir)
    lines = [
        f"Test {output['test_id']} — {output['name']}",
        *([f"Linked to idea card {parsed.idea_card}."] if parsed.idea_card else []),
        "ASSET\tRUN\tREADING\tOOS SHARPE\tLABELS / ERROR",
    ]
    for result in output["results"]:
        sharpe = result["oos_sharpe"]
        lines.append(
            "\t".join(
                (
                    result["asset"],
                    result["run_id"] or "—",
                    reading_word(result["reading"]) if result.get("reading") else "—",
                    f"{sharpe:.3f}" if sharpe is not None else "—",
                    result["error"]
                    or (f"{len(result['labels'])} labels, below" if result["labels"] else "—"),
                )
            )
        )
        if result.get("reading"):
            lines.append(reading_text(result["reading"]))
            lines.extend(variant_lines(result["reading"]))
        if result.get("data_health"):
            lines.append(health_sentence(result["data_health"]))
        if not result.get("executed", True) and result["run_id"]:
            lines.append("The engine did not run: the stored run for this test was returned.")
        if result.get("symbol"):
            counted = _reading_count(settings.data_dir, result)
            lines.extend(counted or [sentence(tries(snapshot, result["symbol"]))])
        if result["labels"] and not result["error"]:
            lines.extend(label_block(result["labels"]))
    emit(output, json_out=json_out, fallback="\n".join(lines))
    if not json_out:
        _echo_notes(notes.getvalue())
