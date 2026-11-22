"""`alpha confirm`: the one-shot test of one idea on the reserved period (the final check).

`plan`, `list` and `show` only read. `run` prints the plan, then spends one slot and scores the
frozen test once; it also resumes a confirmation whose slot is already spent. The owner asks for
it in chat; there is no confirmation step. MCP, web routes and the web launcher cannot reach it.
"""

from __future__ import annotations

import sys
from contextlib import redirect_stdout
from typing import Any

import typer

from alpha_cli import reserved_slots
from alpha_cli._cli_json import emit
from alpha_cli.spine.confirm import plan
from alpha_cli.spine.errors import SpineError, fail
from alpha_core import DataError
from alpha_core.config import AlphaSettings
from alpha_core.reserve import RESERVED_START

confirm_app = typer.Typer(
    help=f"Confirm one tested idea on the reserved period ({RESERVED_START} on): "
    "once, 10 slots in all."
)
RESERVED_WORDS = (
    f"The reserved period is the data from {RESERVED_START} on. It is held back from every test, "
    "so it can serve once as a final check on data no test has seen."
)


def _rule_words(rule: dict[str, Any]) -> str:
    params = ", ".join(f"{k}={v}" for k, v in rule["params"].items())
    costs = rule["costs"]
    return (
        f"{rule['kind']} ({params}); costs {costs['fee_bps']} bps fee and "
        f"{costs['slippage_bps']} bps slippage per trade"
    )


def _rate_lines(rate: dict[str, Any]) -> list[str]:
    """How often the rule traded before; read from the earlier period only."""
    if rate["per_year"] is None:
        return [f"  Trades per year (earlier period): not known; {rate['reason']}."]
    lines = [
        f"  Trades per year (earlier period): {rate['per_year']:.1f} "
        f"({rate['trades']} trades in {rate['years']:.1f} years)."
    ]
    return [*lines, f"  {rate['warning']}"] if rate["warning"] else lines


def _plan_lines(found: dict[str, Any]) -> list[str]:
    frozen, slots, earlier = found["frozen"], found["slots"], found["earlier_reading"]
    engine = "the small (quick) gauntlet" if frozen["quick"] else "the full gauntlet"
    from alpha_cli.spine.reading import plain  # lazy: reading pulls in scipy

    sentence = plain(earlier.get("sentence") or "no reading was stored")
    return [
        RESERVED_WORDS,
        "",
        "What would be tested. It is frozen: nothing can change.",
        f"  Run: {frozen['run_id']} ({found['rule']['name']})",
        f"  Rule: {_rule_words(found['rule'])}",
        f"  Asset: {frozen['symbol']} (store {frozen['store']})",
        f"  Test key: {frozen['test_key_sha256'][:16]} "
        "(spec, asset, store, dates and data content)",
        f"  Engine: {engine}, seed {frozen['seed']}"
        + (", no diagnostics" if frozen["no_diagnose"] else ""),
        f"  Earlier period (already seen): {sentence}",
        f"  Reserved period (not seen): {frozen['reserved_first'][:10]} to "
        f"{frozen['reserved_end'][:10]}, {frozen['reserved_bars']} bars",
        *_rate_lines(found["trade_rate"]),
        "  Code: "
        + (
            "CHANGED since the stored test. The earlier period must still compute the same."
            if found["code_changed"]
            else "the same as for the stored test."
        ),
        f"Slots: {slots['used']} of {slots['total']} used, {slots['left']} left.",
        "Already confirmed (check for a near-duplicate: the same idea on a similar asset, or "
        "in another rule shape):",
        *(
            f"  Slot {e['slot']}: {e['rule']} on {e['symbol']}, run {e['run_id']}, {e['date']}"
            for e in found["earlier_confirmations"]
        ),
        *([] if found["earlier_confirmations"] else ["  none"]),
        "What confirming means:",
        *(f"  - {line}" for line in found["consequences"]),
        "The earlier period is computed again first. If it does not match the stored run, "
        "nothing is spent.",
    ]


def _settings() -> AlphaSettings:
    return AlphaSettings()


@confirm_app.command("plan")
def plan_cmd(
    run_id: str = typer.Argument(..., help="The stored `alpha test` run to confirm."),
    json_out: bool = typer.Option(False, "--json", help="Emit one JSON object."),
) -> None:
    """Show exactly what would be tested and what it costs. Writes nothing."""
    try:
        found = plan(_settings().data_dir, run_id)
    except SpineError as exc:
        fail(exc, json_out)
    except (DataError, OSError, ValueError) as exc:
        fail(SpineError("CONFIRM_REFUSED", str(exc), "Run alpha confirm list."), json_out)
    lines = [*_plan_lines(found), "Nothing was written."]
    lines.append(f"To spend the slot: alpha confirm run {run_id}. It cannot be undone.")
    emit(found, json_out=json_out, fallback="\n".join(lines))


@confirm_app.command("run")
def run_cmd(
    run_id: str = typer.Argument(..., help="The stored `alpha test` run to confirm."),
    json_out: bool = typer.Option(False, "--json", help="Emit one JSON object."),
) -> None:
    """Print the plan, then spend 1 slot and test once on the reserved period (or resume)."""
    from alpha_cli.spine import confirm_run

    home = _settings().data_dir
    found = None
    shown = sys.stdout
    words = ""
    try:
        if confirm_run.receipt_for(home, run_id) is None:
            found = plan(home, run_id)
            words = f"Spending 1 slot now. After this, {found['slots']['left'] - 1} slots are left."
            if not json_out:
                typer.echo("\n".join(_plan_lines(found)))

        def spent() -> None:
            # Printed when the receipt is written, not before: a refusal spends nothing.
            if words and not json_out:
                typer.echo(words, file=shown)

        with redirect_stdout(sys.stderr):
            output = confirm_run.confirm_run(home, run_id, on_spent=spent)
    except SpineError as exc:
        fail(exc, json_out)
    except (DataError, OSError, ValueError) as exc:
        fail(SpineError("CONFIRM_REFUSED", str(exc), f"Run alpha confirm plan {run_id}."), json_out)
    emit({**output, "plan": found}, json_out=json_out, fallback="\n".join(result_lines(output)))


def result_lines(output: dict[str, Any]) -> list[str]:
    """Both periods side by side, as readings: numbers in context, no pass or fail."""
    from alpha_cli.spine.reading import plain  # lazy: reading pulls in scipy

    def one(name: str, part: dict[str, Any]) -> list[str]:
        sharpe = part.get("oos_sharpe")
        return [
            f"{name}: scored {str(part.get('scored_from'))[:10]} to "
            f"{str(part.get('scored_to'))[:10]} (run {part.get('run_id')})",
            "  Sharpe (return per unit of risk, per year): "
            + (f"{sharpe:.3f}" if isinstance(sharpe, float) else "not computed"),
            f"  Reading: {part.get('reading')}. {plain(part.get('sentence') or '')}".rstrip(),
        ]

    return [
        f"Slot {output['slot']} of {reserved_slots.SLOTS} (receipt {output['receipt_id']}); "
        f"{output['slots_left']} left.",
        *one("Earlier period (seen before)", output["earlier"]),
        *one("Reserved period (seen now, once)", output["reserved"]),
        "This is a reading, not a verdict. It is no advice and no promise of profit.",
        "It is recorded as it is; it cannot be discarded or run again.",
    ]


@confirm_app.command("list")
def list_cmd(json_out: bool = typer.Option(False, "--json", help="Emit one JSON object.")) -> None:
    """Slots used and left, and each receipt in plain words. Writes nothing."""
    try:
        found = reserved_slots.receipts(_settings().data_dir)
    except (DataError, OSError, ValueError) as exc:
        fail(SpineError("CONFIRM_REFUSED", str(exc), "Run alpha info."), json_out)
    lines = [f"Reserved-period slots: {len(found)} of {reserved_slots.SLOTS} used."]
    for item in found:
        frozen = item["frozen"]
        state = "finished" if item["result"] else "slot spent, run not finished (resume with run)"
        lines.append(
            f"  Slot {item['slot']}: {frozen['rule']} on {frozen['symbol']}, run {item['run_id']}, "
            f"{str(item['created_at'])[:10]}; {state}."
        )
    output = {"used": len(found), "left": reserved_slots.SLOTS - len(found), "receipts": found}
    emit(output, json_out=json_out, fallback="\n".join(lines))


@confirm_app.command("show")
def show_cmd(
    which: str = typer.Argument(..., help="A receipt id or the confirmed run id."),
    json_out: bool = typer.Option(False, "--json", help="Emit one JSON object."),
) -> None:
    """One receipt and its result, as stored. Reads no reserved bar."""
    from alpha_cli.spine.confirm_run import shown

    try:
        found = next(
            r
            for r in reserved_slots.receipts(_settings().data_dir)
            if which in (r["receipt_id"], r["run_id"])
        )
        if found["result"] is None:
            raise DataError(
                f"slot {found['slot']} is spent but its run is not finished; "
                f"run alpha confirm run {found['run_id']}"
            )
        output = shown(_settings().data_dir, found["run_id"])
    except StopIteration:
        fail(
            SpineError("NO_RECEIPT", f"No receipt for {which}.", "Run alpha confirm list."),
            json_out,
        )
    except (DataError, OSError, ValueError) as exc:
        fail(SpineError("CONFIRM_REFUSED", str(exc), "Run alpha confirm list."), json_out)
    emit(output, json_out=json_out, fallback="\n".join(result_lines(output)))


__all__ = ["confirm_app", "result_lines"]
