"""`alpha follow`: follow a tested idea forward on paper. F1: the frozen record and the journal.

No signal is computed and no trade is simulated here. No network, no model. Writes only under
`<data_dir>/forward/`, never a trial-ledger row.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, Any

import typer

from alpha_cli import follow_source
from alpha_cli import follow_store as store
from alpha_cli._cli_json import emit
from alpha_cli.follow_journal import JournalRefusal
from alpha_cli.spine.errors import SpineError, fail
from alpha_core.config import AlphaSettings

follow_app = typer.Typer(
    help="Follow a tested idea forward on paper. Never an order, never advice."
)
JSON = Annotated[bool, typer.Option("--json", help="Print the same facts as JSON.")]


def utc_now() -> datetime:
    return datetime.now(tz=UTC)


CLOCK = utc_now  # tests replace this; the journal never reads the wall clock itself


def _clock() -> datetime:
    return CLOCK()


def _row(f: dict[str, Any]) -> str:
    if f["state"] == "broken":
        return f"  {f['follow_id']}  broken: run `alpha follow verify {f['follow_id']}`"
    state = store.WAITING if f["state"] == "waiting" else f["state"]
    return (
        f"  {f['follow_id']}  {store.KINDS[f['kind']]}  {', '.join(f['assets'])}  "
        f"version {f['version']}  {state}"
    )


def _show_text(facts: dict[str, Any]) -> str:
    r = facts["record"]
    counts = ", ".join(f"{n} {k}" for k, n in sorted(facts["entries"].items()))
    lines = [
        f"Follow {r['follow_id']} (paper), version {r['version']}",
        f"  What: {store.KINDS[r['kind']]} {r['source_id']}",
        f"  Assets: {', '.join(r['assets'])}",
        f"  Spec hash: {r['spec_sha256']}",
        f"  Idea card: {r['card_id'] or 'none linked'}",
        f"  Paper size: {r['paper_account_percent']:g}% of a paper account",
        f"  Started: {r['started_at']}",
    ]
    if r["supersedes"]:
        lines.append(f"  Replaces follow {r['supersedes']}")
    lines += [f"  Entries: {counts}", f"  Chain head: {facts['head']}"]
    if facts["state"] == "stopped":
        lines.append(f"State: stopped. Reason: {facts['stop_reason'] or 'none given'}.")
    elif facts["waiting_for_first_bar"]:
        lines.append(f"State: {store.WAITING}.")
    else:
        lines.append("State: active.")
    lines.append(store.PAPER)
    return "\n".join(lines)


@follow_app.command("start")
def start(
    test: Annotated[str, typer.Option("--test", help="Run id of a rule test.")] = "",
    find: Annotated[str, typer.Option("--find", help="Find id of a setup find.")] = "",
    factor: Annotated[str, typer.Option("--factor", help="Not built yet.")] = "",
    card: Annotated[
        str, typer.Option("--card", help="Idea card id (default: the test's own).")
    ] = "",
    size_pct: Annotated[
        float, typer.Option("--size-pct", help="Paper size, percent of a paper account.")
    ] = store.DEFAULT_SIZE_PCT,
    json_out: JSON = False,
) -> None:
    """Follow a tested rule or setup forward on paper. A changed spec starts a new version."""
    home = AlphaSettings().data_dir
    try:
        if sum(bool(x) for x in (test, find, factor)) != 1:
            raise SpineError(
                "FOLLOW_SOURCE_NEEDED",
                "Name exactly one thing to follow: --test, --find or --factor.",
                "Example: alpha follow start --test <run id>",
            )
        if factor:
            raise SpineError(
                "FOLLOW_FACTOR_NOT_BUILT",
                "Following a factor is not built yet.",
                "Follow a rule test (--test) or a setup find (--find).",
            )
        if not 0 < size_pct <= 100:
            raise SpineError(
                "FOLLOW_SIZE",
                "Paper size must be above 0 and at most 100 percent.",
                "Use --size-pct.",
            )
        source = (
            follow_source.rule_test_source(home, test)
            if test
            else follow_source.setup_find_source(home, find)
        )
        facts = store.start_follow(home, source, card=card, size_pct=size_pct, clock=_clock)
    except (SpineError, JournalRefusal) as exc:
        fail(exc, json_out)
    lines = [
        f"{'Following' if facts['created'] else 'Already following'} "
        f"{store.KINDS[facts['kind']]} {facts['source_id']} on paper. "
        f"Follow id {facts['follow_id']}.",
        f"Paper size: {facts['paper_account_percent']:g}% of a paper account.",
    ]
    if facts["replaced"]:
        lines.append(
            f"This is version {facts['version']}. It replaces follow {facts['replaced']}, now "
            "stopped and kept. The forward clock restarts."
        )
    lines += [f"State: {store.WAITING}.", f"See it: alpha follow show {facts['follow_id']}"]
    emit(facts, json_out=json_out, fallback="\n".join(lines))


@follow_app.command("list")
def list_follows(json_out: JSON = False) -> None:
    """One row per follow, with its state. Paper only."""
    rows = store.list_facts(AlphaSettings().data_dir)
    head = f"{len(rows)} idea(s) followed on paper." if rows else "No follows yet (paper)."
    tail = [] if rows else ["Start one: alpha follow start --test <run id>"]
    emit({"follows": rows}, json_out=json_out, fallback="\n".join([head, *map(_row, rows), *tail]))


@follow_app.command("show")
def show(
    follow_id: Annotated[str, typer.Argument(help="Follow id or prefix.")], json_out: JSON = False
) -> None:
    """The frozen record, the entries by kind and the chain head."""
    home = AlphaSettings().data_dir
    try:
        facts = store.show_facts(home, store.resolve(home, follow_id))
    except (SpineError, JournalRefusal) as exc:
        fail(exc, json_out)
    emit(facts, json_out=json_out, fallback=_show_text(facts))


@follow_app.command("verify")
def verify(
    follow_id: Annotated[str, typer.Argument(help="Follow id or prefix.")], json_out: JSON = False
) -> None:
    """Recompute the hash chain. Exit 1 at the first break."""
    home = AlphaSettings().data_dir
    try:
        identity = store.resolve(home, follow_id)
        report = store.journal_report(home, identity)
    except (SpineError, JournalRefusal) as exc:
        fail(exc, json_out)
    broken = report.first_break
    facts = {
        "follow_id": identity,
        "ok": broken is None,
        "entries": report.entries,
        "head": report.head,
        "first_break": None if broken is None else broken._asdict(),
    }
    text = (
        f"Journal of follow {identity} (paper) is intact: {report.entries} entries, "
        f"head {report.head}."
        if broken is None
        else f"Journal of follow {identity} is broken at entry {broken.seq}: {broken.reason}"
    )
    emit(facts, json_out=json_out, fallback=text)
    if broken is not None:
        raise typer.Exit(1)


@follow_app.command("stop")
def stop(
    follow_id: Annotated[str, typer.Argument(help="Follow id or prefix.")],
    reason: Annotated[str, typer.Option("--reason", help="Why it stops.")] = "",
    json_out: JSON = False,
) -> None:
    """Stop a follow. The record and journal stay. Nothing can be written after a stop."""
    home = AlphaSettings().data_dir
    try:
        identity = store.resolve(home, follow_id)
        entry = store.stop_follow(home, identity, reason=reason, clock=_clock)
    except (SpineError, JournalRefusal) as exc:
        fail(exc, json_out)
    emit(
        {"follow_id": identity, "stopped": True, "seq": entry.seq},
        json_out=json_out,
        fallback=f"Follow {identity} stopped (paper). Its record and journal are kept.",
    )
