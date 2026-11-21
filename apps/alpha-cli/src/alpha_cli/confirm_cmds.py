"""`alpha confirm`: the owner's one-shot test of one idea on the reserved period (2024-01-01 on).

`plan` and `list`/`show` only read. `request` issues the Touch ID challenge and prints the local
link; the owner's touch on that page is the only yes. `run` spends the slot only with that yes, or
resumes a confirmation whose slot is already spent. Nothing here is reachable from MCP or from a
web route without the owner's assertion.
"""

from __future__ import annotations

import base64
import json
import sys
from contextlib import redirect_stdout
from typing import Any
from urllib.parse import urlencode

import typer

from alpha_cli import reserved_slots
from alpha_cli._cli_json import emit
from alpha_cli.spine.confirm import plan
from alpha_cli.spine.errors import SpineError, fail
from alpha_core import DataError
from alpha_core.config import AlphaSettings

confirm_app = typer.Typer(
    help="Confirm one tested idea on the reserved period (2024-01-01 on): once, 10 slots in all."
)
RESERVED_WORDS = (
    "The reserved period is the data from 2024-01-01 on. It is held back from every test, so it "
    "can serve once as a final check on data no test has seen."
)


def _b64(value: object) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _spec_words(spec: dict[str, Any]) -> str:
    params = ", ".join(f"{k}={v}" for k, v in spec["rule"]["params"].items())
    costs = spec["costs"]
    return (
        f"{spec['rule']['kind']} ({params}); costs {costs['fee_bps']} bps fee and "
        f"{costs['slippage_bps']} bps slippage per trade"
    )


def _plan_lines(found: dict[str, Any]) -> list[str]:
    frozen, slots, earlier = found["frozen"], found["slots"], found["earlier_reading"]
    engine = "the small (quick) gauntlet" if frozen["quick"] else "the full gauntlet"
    sentence = earlier.get("sentence") or "no reading was stored"
    return [
        RESERVED_WORDS,
        "",
        "What would be tested. It is frozen: nothing can change.",
        f"  Run: {frozen['run_id']} ({found['spec']['name']})",
        f"  Rule: {_spec_words(found['spec'])}",
        f"  Asset: {frozen['symbol']} (store {frozen['store']})",
        f"  Test key: {frozen['test_key_sha256'][:16]} "
        "(spec, asset, store, dates and data content)",
        f"  Engine: {engine}, seed {frozen['seed']}"
        + (", no diagnostics" if frozen["no_diagnose"] else ""),
        f"  Earlier period (already seen): {sentence}",
        f"  Reserved period (not seen): {frozen['reserved_first'][:10]} to "
        f"{frozen['reserved_end'][:10]}, {frozen['reserved_bars']} bars",
        f"Slots: {slots['used']} of {slots['total']} used, {slots['left']} left.",
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
    lines.append(f'To go ahead: alpha confirm request {run_id} --reason "<why this idea>".')
    emit(found, json_out=json_out, fallback="\n".join(lines))


@confirm_app.command("request")
def request_cmd(
    run_id: str = typer.Argument(..., help="The stored `alpha test` run to confirm."),
    reason: str = typer.Option(..., help="Why this idea, in your words (kept with the receipt)."),
    json_out: bool = typer.Option(False, "--json", help="Emit one JSON object."),
) -> None:
    """Ask for the owner's Touch ID yes: prints a local link that works for 60 seconds."""
    from alpha_cli.owner_auth import OWNER_ORIGIN, reserved_confirmation_options

    home = _settings().data_dir
    try:
        found = plan(home, run_id)
        frozen = found["frozen"]
        payload = {"run_id": run_id, "reserved_end": frozen["reserved_end"]}
        summary = (
            f"Test run {run_id} ({frozen['rule']} on {frozen['symbol']}) once on the reserved "
            f"period, {frozen['reserved_bars']} bars. " + " ".join(found["consequences"])
        )
        options = reserved_confirmation_options(
            data_dir=home,
            payload=payload,
            artifact_hash=frozen["artifact_hash"],
            consequence_summary=summary,
            reason=reason,
        )
    except SpineError as exc:
        fail(exc, json_out)
    except (DataError, OSError, ValueError) as exc:
        fail(SpineError("CONFIRM_REFUSED", str(exc), "Run alpha confirm plan first."), json_out)
    fragment = urlencode(
        {
            "challenge": options["challenge_id"],
            "options": _b64(options["public_key"]),
            "payload": _b64(payload),
            "summary": summary,
        }
    )
    url = f"{OWNER_ORIGIN}/owner-auth/confirm#{fragment}"
    lines = [
        *_plan_lines(found),
        "Open this local link in the Workstation browser and touch Touch ID to say yes.",
        "It works for 60 seconds. If it expires, run this command again; nothing is spent.",
        url,
    ]
    emit(
        {**found, "url": url, "expires_at": options["expires_at"]},
        json_out=json_out,
        fallback="\n".join(lines),
    )


@confirm_app.command("run")
def run_cmd(
    run_id: str = typer.Argument(..., help="The stored `alpha test` run the owner confirmed."),
    authorization: str | None = typer.Option(
        None, help="The owner's Touch ID yes (the Workstation passes it). Not needed to resume."
    ),
    json_out: bool = typer.Option(False, "--json", help="Emit one JSON object."),
) -> None:
    """Run the confirmed test on the reserved period once, or resume it. Shows the reading."""
    from alpha_cli.spine.confirm_run import confirm_run

    try:
        with redirect_stdout(sys.stderr):
            output = confirm_run(_settings().data_dir, run_id, authorization_id=authorization)
    except SpineError as exc:
        fail(exc, json_out)
    except (DataError, OSError, ValueError) as exc:
        fail(SpineError("CONFIRM_REFUSED", str(exc), f"Run alpha confirm plan {run_id}."), json_out)
    emit(output, json_out=json_out, fallback="\n".join(result_lines(output)))


def result_lines(output: dict[str, Any]) -> list[str]:
    """Both periods side by side, as readings: numbers in context, no pass or fail."""

    def one(name: str, part: dict[str, Any]) -> list[str]:
        sharpe = part.get("oos_sharpe")
        return [
            f"{name}: scored {str(part.get('scored_from'))[:10]} to "
            f"{str(part.get('scored_to'))[:10]} (run {part.get('run_id')})",
            "  Sharpe (return per unit of risk, per year): "
            + (f"{sharpe:.3f}" if isinstance(sharpe, float) else "not computed"),
            f"  Reading: {part.get('reading')}. {part.get('sentence') or ''}".rstrip(),
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
