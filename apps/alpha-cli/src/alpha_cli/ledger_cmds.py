"""Read-only ledger reports over the three historical trial schemas."""

from __future__ import annotations

import hashlib
import json
import os
from collections import Counter
from collections.abc import Callable
from dataclasses import asdict
from enum import StrEnum
from pathlib import Path
from typing import Annotated, Any

import typer

from alpha_cli._cli_json import emit
from alpha_cli.rdagent_discussion import NOTE_HELP
from alpha_cli.spine.errors import SpineError, fail
from alpha_cli.spine.stores import typed_symbol
from alpha_cli.spine.trial_query import ASSET_NOTE, asset_group
from alpha_cli.spine.trial_reader import (
    LedgerSnapshot,
    family_counts,
    ledger_sources,
    read_ledgers,
    trials_for_deflation,
)
from alpha_cli.spine.trial_record import TrialRecord
from alpha_cli.spine.tries import sentence, tries
from alpha_core.config import AlphaSettings

ledger_app = typer.Typer(help="Read all recorded trials through one unchanged-ledger view.")
RD = Annotated[Path | None, typer.Option("--rdagent-ledger", help="RD-Agent ledger path.")]
JSON = Annotated[bool, typer.Option("--json")]
OUTCOME = Annotated[
    str | None,
    typer.Option(
        help="An evidence word (e.g. 'some evidence') or an old word (supported, rejected, "
        "inconclusive, error, 'not supported'); both match, so old scripts keep working."
    ),
]
# The group callback keeps a flag given before the subcommand; the command runs in one process.
_BEFORE_SUBCOMMAND: dict[str, Path | None] = {}
NOTICE = "Read-only view; the ledgers themselves are unchanged."
# Where the RD-Agent factor loop's shared ledger lives beside the data directory (the
# `--trial-ledger` path every real run has used): read when `ledger/sources.toml` is absent.
DEFAULT_RDAGENT_LEDGER = Path("runs/rdagent-trial-ledger/rdagent-factor-trials.jsonl")


def _default_rdagent_ledger(home: Path) -> Path:
    """The Workstation's rule: `ALPHA_RDAGENT_RUNS_DIR`, else `runs/` beside the data home."""
    runs = os.environ.get("ALPHA_RDAGENT_RUNS_DIR")
    if runs:
        return Path(runs) / DEFAULT_RDAGENT_LEDGER.relative_to("runs")
    return home.resolve().parent / DEFAULT_RDAGENT_LEDGER


def _rdagent_ledger(home: Path, rdagent: Path | None) -> Path | None:
    if rdagent is None and not (home / "ledger/sources.toml").exists():
        return _default_rdagent_ledger(home)
    return rdagent


def figures(row: dict[str, Any]) -> str:
    values = row.get("measures", {})
    ic, q = values.get("mean_ic"), values.get("q")
    text = (
        f"{row['measure_clock']}: IC "
        + (f"{ic:.4g}" if ic is not None else "not recorded")
        + ", q "
        + (f"{q:.4g}" if q is not None else "not recorded")
    )

    if values.get("screen_cutoff") is not None:
        text += (
            f" (BH diagnostic); screen cutoff {values['screen_cutoff']:.4g} "
            f"over {values['screen_m']:g} looks, {values['screen_confirmed']:g} confirmed"
        )
    if values.get("dsr") is not None:
        text += f"; stored deflated Sharpe {values['dsr']:.4g}"
        if values.get("deflation_n") is None:
            text += "; old rule (fewer looks counted)"
        else:
            text += (
                f" over {values['deflation_n']:g} looks; "
                f"variance {values['deflation_variance']:.4g}"
            )
    return text


def _render(output: dict[str, Any]) -> str:
    rows = output.get(
        "records", output.get("families", output.get("rows", output.get("sources", [])))
    )
    if "record" in output:
        rows = [output["record"]]
    rows = [{**row, "figures": figures(row)} if row.get("measure_clock") else row for row in rows]
    # A rule test's stored status is its old letter grade: it stays in the JSON, never in the text.
    rows = [{**row, "raw_status": None} if row.get("kind") == "rule_test" else row for row in rows]
    # Beside the headline count of tries, no other count is printed: they stay in the JSON.
    hidden = {"rows", "mapped", "unknown", "reader_trials"} if "tries" in output else set()
    keys = [
        key
        for key in (
            "trial_id",
            "source",
            "state",
            "family_id",
            "kind",
            "outcome",
            "raw_status",
            "reason",
            "figures",
            "month",
            "asset",
            "tries",
            "rows",
            "mapped",
            "unknown",
            "reader_trials",
            "measure_value",
        )
        if key not in hidden and any(key in row for row in rows)
    ]
    lines = ["\t".join(keys)] if keys else []
    lines.extend(
        "\t".join("" if row.get(key) is None else str(row[key]) for key in keys) for row in rows
    )
    counted = output.get("tries")
    if isinstance(counted, dict):
        # One headline number; the row counts stay in the JSON for machines.
        lines.append(sentence(counted))
        if output.get("rdagent_kinds"):
            kinds = ", ".join(f"{name} {n}" for name, n in output["rdagent_kinds"].items())
            total = sum(output["rdagent_kinds"].values())
            lines.append(f"The RD-Agent ledger adds {total} trials ({kinds}).")
        if output.get("breakdown"):
            lines.append(f"By kind: {json.dumps(counted['by_kind'], sort_keys=True)}")
            lines.append(f"By family: {json.dumps(counted['by_family'], sort_keys=True)}")
        lines.append(counted["definition"])
        if output.get("unknown_rows"):
            lines.append(
                f"{output['unknown_rows']} ledger rows ALPHA could not interpret; the deflated "
                "Sharpe counts them anyway."
            )
    for key in (
        *(() if isinstance(counted, dict) else ("by_kind", "by_outcome", "family_count")),
        "newest_created_at",
        "evidence_found",
        "evidence_sha256_now",
        "evidence_matches",
    ):
        if key in output:
            lines.append(f"{key}: {json.dumps(output[key], sort_keys=True)}")
    if "trials_text" in output and not isinstance(counted, dict):
        lines.append(output["trials_text"])
    if "note" in output:
        lines.append(output["note"])
    for source in output.get("sources", []):
        if source["state"] == "missing":
            if source.get("optional", False):
                continue
            lines.append(f"{source['source']}: ledger file not found ({source['file']})")
        else:
            lines.append(f"{source['source']}: read {source['file']}")
        for reason, count in source["unknown_by_reason"].items():
            lines.append(
                f"{source['source']}: {count} row(s) not understood yet, counted as trials "
                f"anyway: {reason}"
            )
    return "\n".join([*lines, NOTICE])


def _run(
    rdagent: Path | None,
    json_out: bool,
    action: Callable[[LedgerSnapshot, Path], dict[str, Any]],
    text: Callable[[dict[str, Any]], str] = _render,
) -> None:
    rdagent = rdagent or _BEFORE_SUBCOMMAND.get("rdagent_ledger")
    try:
        home = AlphaSettings().data_dir
        snapshot = read_ledgers(
            ledger_sources(
                home,
                _rdagent_ledger(home, rdagent),
                rdagent_optional=rdagent is None and not (home / "ledger/sources.toml").exists(),
            )
        )
        output = action(snapshot, home)
        output["sources"] = [asdict(s) for s in snapshot.sources]
        output["unknown"] = [asdict(row) for row in snapshot.unknown]
        emit(output, json_out=json_out, fallback=text(output))
    except (ValueError, OSError) as exc:
        fail(
            exc
            if isinstance(exc, SpineError)
            else SpineError(
                "LEDGER_READ_FAILED",
                str(exc),
                "Correct the reported ledger or evidence read error.",
            ),
            json_out,
        )


def _totals(snapshot: LedgerSnapshot) -> dict[str, Any]:
    result = trials_for_deflation(snapshot, "")
    total, unknown = result["all_trials"], result["unknown_rows"]
    text = f"{total} trials"
    if unknown:
        text += f", including {unknown} rows ALPHA could not interpret (counted anyway)"
    return {"all_trials": total, "unknown_rows": unknown, "trials_text": text}


def _summary(snapshot: LedgerSnapshot, home: Path) -> dict[str, Any]:
    return {
        "tries": tries(snapshot),
        "breakdown": True,
        "by_kind": dict(Counter(r.kind for r in snapshot.records)),
        "by_outcome": dict(Counter(r.outcome for r in snapshot.records)),
        "rdagent_kinds": dict(
            sorted(Counter(r.kind for r in snapshot.records if r.source == "rdagent").items())
        ),
        "family_count": len(family_counts(snapshot)),
        **_totals(snapshot),
        "newest_created_at": max(
            (r.created_at for r in snapshot.records if r.created_at), default=None
        ),
    }


@ledger_app.command()
def summary(rdagent_ledger: RD = None, json_out: JSON = False) -> None:
    """Summarise mapped trials, unknown rows and missing sources."""
    _run(rdagent_ledger, json_out, _summary)


def _share_per_kind(records: list[TrialRecord], limit: int) -> list[TrialRecord]:
    """Newest rows, with every kind of try given an equal share so none is pushed out of view.

    Never more than `limit` rows: with more kinds than slots, the newest rows of all kinds win.
    """
    kinds = sorted({r.kind for r in records})
    if not kinds:
        return []
    share = max(1, limit // len(kinds))
    taken = {id(r) for kind in kinds for r in [x for x in records if x.kind == kind][:share]}
    chosen = [r for r in records if id(r) in taken]
    spare = [r for r in records if id(r) not in taken][: max(0, limit - len(chosen))]
    return sorted(
        [*chosen, *spare],
        key=lambda r: (r.created_at is not None, r.created_at or "", r.source, r.source_line),
        reverse=True,
    )[:limit]


@ledger_app.callback(invoke_without_command=True)
def default_view(ctx: typer.Context, rdagent_ledger: RD = None, json_out: JSON = False) -> None:
    """With no subcommand, list the newest trials of every kind (same as `ledger list`)."""
    _BEFORE_SUBCOMMAND["rdagent_ledger"] = rdagent_ledger
    if ctx.invoked_subcommand is None:
        list_trials(rdagent_ledger=rdagent_ledger, json_out=json_out)


@ledger_app.command("list")
def list_trials(
    kind: str | None = None,
    family: str | None = None,
    asset: str | None = None,
    outcome: OUTCOME = None,
    source: str | None = None,
    limit: int = 50,
    rdagent_ledger: RD = None,
    json_out: JSON = False,
) -> None:
    """List matching trials newest first, retaining source provenance."""

    def select(snapshot: LedgerSnapshot, home: Path) -> dict[str, Any]:
        if not 1 <= limit <= 200:
            raise SpineError("BAD_PARAMETER", "Limit must be from 1 to 200.", "Use --limit 1..200.")
        name, said = typed_symbol(asset, data_dir=home) if asset else (None, None)
        records = [
            r
            for r in snapshot.records
            if all(
                value is None or getattr(r, key) == value
                for key, value in dict(kind=kind, family_id=family, source=source).items()
            )
            # The filter still takes the old machine words, so existing callers keep working.
            and (outcome is None or outcome in {r.outcome, r.machine_outcome})
            and (name is None or asset_group(name) in {asset_group(a) for a in r.assets})
        ]
        records.sort(
            key=lambda r: (r.created_at is not None, r.created_at or "", r.source, r.source_line),
            reverse=True,
        )
        shown = records[:limit] if kind else _share_per_kind(records, limit)
        return {
            "records": [asdict(r) for r in shown],
            "note": " ".join(
                filter(
                    None,
                    [
                        said,
                        f"Showing {len(shown)} of {len(records)} rows "
                        "(newest first within each kind).",
                    ],
                )
            ),
        }

    _run(rdagent_ledger, json_out, select)


def _recorded_run_id(run: Path) -> str | None:
    """A run folder's recorded id; another run's unreadable identity file only fails to match."""
    identity = run / "run-identity.json"
    if not identity.is_file():
        return None
    try:
        recorded = json.loads(identity.read_bytes())
    except ValueError:
        return None
    value = recorded.get("run_id") if isinstance(recorded, dict) else None
    return value if isinstance(value, str) else None


def _evidence(record: TrialRecord, home: Path) -> dict[str, Any]:
    root = home if record.source == "spine" else Path(record.source_file).parent.parent
    candidates: list[Path] = []
    if record.evidence_path:
        if record.source == "spine":
            candidates = [root / record.evidence_path]
        elif record.run_id:
            roots = list(root.iterdir()) if record.kind == "rule_family" else [root]
            runs: set[Path] = set()
            for folder in roots:
                if not folder.is_dir():
                    continue
                direct = folder / record.run_id
                # Validate references even when the run or its evidence does not exist.
                runs.add(direct)
                runs.update(
                    run
                    for run in folder.iterdir()
                    if run.is_dir() and _recorded_run_id(run) == record.run_id
                )
            candidates = [r / record.evidence_path for r in runs]
    # Evidence references never permit traversal out of the declared evidence root.
    if any(not path.resolve().is_relative_to(root.resolve()) for path in candidates):
        raise SpineError(
            "LEDGER_EVIDENCE_INVALID",
            "Evidence path escapes its root.",
            "Inspect the raw ledger evidence reference.",
        )
    found = [p for p in candidates if p.is_file()]
    if len(found) > 1:
        raise SpineError(
            "LEDGER_EVIDENCE_INVALID",
            "Evidence path is not unique.",
            "Inspect the matching run directories.",
        )
    digest = hashlib.sha256(found[0].read_bytes()).hexdigest() if found else None
    return {
        "evidence_found": bool(found),
        "evidence_sha256_now": digest,
        "evidence_matches": digest == record.evidence_sha256 if record.evidence_sha256 else None,
    }


@ledger_app.command()
def show(trial_id: str, rdagent_ledger: RD = None, json_out: JSON = False) -> None:
    """Show a record, its raw row and a fresh evidence hash check."""

    def select(snapshot: LedgerSnapshot, home: Path) -> dict[str, Any]:
        record = next((r for r in snapshot.records if r.trial_id == trial_id), None)
        if record is None:
            raise SpineError(
                "UNKNOWN_TRIAL", f"Unknown trial {trial_id!r}.", "Run alpha ledger list."
            )
        return {
            "record": asdict(record),
            "raw_row": snapshot.raw_rows[(record.source_file, record.source_line)],
            **_evidence(record, home),
        }

    _run(rdagent_ledger, json_out, select)


@ledger_app.command()
def families(rdagent_ledger: RD = None, json_out: JSON = False) -> None:
    """Show family counts and the conservative all-trials total."""

    def select(snapshot: LedgerSnapshot, home: Path) -> dict[str, Any]:
        return {
            "families": family_counts(snapshot),
            **_totals(snapshot),
            "tries": tries(snapshot),
        }

    _run(rdagent_ledger, json_out, select)


@ledger_app.command("tries")
def tries_cmd(
    asset: str = typer.Argument(..., help="The asset symbol, e.g. SPY."),
    rdagent_ledger: RD = None,
    json_out: JSON = False,
) -> None:
    """How many tries on one asset, in one sentence (the count the deflated Sharpe uses)."""

    def select(snapshot: LedgerSnapshot, home: Path) -> dict[str, Any]:
        name, note = typed_symbol(asset, data_dir=home)
        return {"tries": tries(snapshot, name), "resolved_note": note}

    def text(output: dict[str, Any]) -> str:
        line = sentence(output["tries"])
        return f"{output['resolved_note']} {line}" if output["resolved_note"] else line

    _run(rdagent_ledger, json_out, select, text)


@ledger_app.command("query")
def query_trials(
    question: str,
    asset: str | None = None,
    family: str | None = None,
    measure: str | None = None,
    limit: int = 50,
    rdagent_ledger: RD = None,
    json_out: JSON = False,
) -> None:
    """Run a named question with bound parameters; arbitrary SQL is unavailable."""
    from alpha_cli.spine.trial_query import query

    def select(snapshot: LedgerSnapshot, home: Path) -> dict[str, Any]:
        name, said = typed_symbol(asset, data_dir=home) if asset else (None, None)
        note = " ".join(filter(None, [said, ASSET_NOTE if "asset" in question else None]))
        return {
            "question": question,
            **({"note": note} if note else {}),
            "rows": query(
                snapshot, question, asset=name, family=family, measure=measure, limit=limit
            ),
        }

    _run(rdagent_ledger, json_out, select)


class Theme(StrEnum):
    light = "light"
    dark = "dark"


@ledger_app.command("journey")
def journey(
    run_dir: Annotated[
        Path, typer.Option(exists=True, file_okay=False, help="Recorded run folder.")
    ],
    factor: Annotated[
        str | None, typer.Option(help="Select all iterations of this factor name.")
    ] = None,
    out: Annotated[
        Path | None, typer.Option(file_okay=False, help="Parent for the journey folder.")
    ] = None,
    theme: Annotated[Theme, typer.Option(help="Figure background.")] = Theme.light,
) -> None:
    """Write seven-step journeys, annotated pictures and their plotted data."""
    from alpha_cli.rdagent_journey import build

    typer.echo(build(run_dir, out, factor, theme == Theme.dark))


class ReplyAuthor(StrEnum):
    owner = "owner"
    stand_in = "stand-in"


RunFolder = Annotated[Path, typer.Option(exists=True, file_okay=False, help="RD-Agent run folder.")]


@ledger_app.command("proposal")
def proposal(
    run_dir: RunFolder,
    details: Annotated[
        bool, typer.Option(help="Show the full open and closed idea types.")
    ] = False,
    last_decision: Annotated[
        bool, typer.Option("--last-decision", help="Show only the latest decision.")
    ] = False,
) -> None:
    """Show the ideas RD-Agent proposes and waits on before it builds anything."""
    from alpha_cli.rdagent_discussion import proposal_text

    try:
        typer.echo(proposal_text(run_dir, details=details, last_decision=last_decision))
    except ValueError as error:
        typer.echo(str(error), err=True)
        raise typer.Exit(1) from error


@ledger_app.command("reply")
def discussion_reply(
    run_dir: RunFolder,
    author: Annotated[
        ReplyAuthor, typer.Option("--as", help="Who answers: owner, or stand-in (not the owner).")
    ],
    accept: Annotated[list[str] | None, typer.Option(help="Build by name or list number.")] = None,
    drop: Annotated[
        list[str] | None,
        typer.Option(help="Skip by name or list number, with an optional =reason."),
    ] = None,
    revise: Annotated[
        list[str] | None,
        typer.Option(help="Ask for a change by name or list number, followed by =note."),
    ] = None,
    idea: Annotated[list[str] | None, typer.Option(help="Add your own idea (two at most).")] = None,
    note: Annotated[str | None, typer.Option(help=NOTE_HELP)] = None,
) -> None:
    """Answer RD-Agent's proposal. Ideas you do not name are built as proposed."""
    from alpha_cli.rdagent_discussion import submit

    try:
        typer.echo(
            submit(run_dir, author.value, accept or [], drop or [], revise or [], idea or [], note)
        )
    except ValueError as error:
        typer.echo(str(error), err=True)
        raise typer.Exit(1) from error
