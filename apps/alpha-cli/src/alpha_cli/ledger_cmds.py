"""Read-only ledger reports over the three historical trial schemas."""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from collections.abc import Callable
from dataclasses import asdict
from pathlib import Path
from typing import Annotated, Any

import typer

from alpha_cli._cli_json import emit
from alpha_cli.spine.errors import SpineError, fail
from alpha_cli.spine.trial_query import ASSET_NOTE, asset_group
from alpha_cli.spine.trial_reader import (
    LedgerSnapshot,
    family_counts,
    ledger_sources,
    read_ledgers,
    trials_for_deflation,
)
from alpha_cli.spine.trial_record import TrialRecord
from alpha_core.config import AlphaSettings

ledger_app = typer.Typer(help="Read all recorded trials through one unchanged-ledger view.")
RD = Annotated[Path | None, typer.Option("--rdagent-ledger", help="RD-Agent ledger path.")]
JSON = Annotated[bool, typer.Option("--json")]
NOTICE = "Read-only view; the ledgers themselves are unchanged."
# Where the RD-Agent factor loop's shared ledger lives beside the data directory (the
# `--trial-ledger` path every real run has used): read when `ledger/sources.toml` is absent.
DEFAULT_RDAGENT_LEDGER = Path("runs/rdagent-trial-ledger/rdagent-factor-trials.jsonl")


def _rdagent_ledger(home: Path, rdagent: Path | None) -> Path | None:
    if rdagent is None and not (home / "ledger/sources.toml").exists():
        return home.resolve().parent / DEFAULT_RDAGENT_LEDGER
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
            "rows",
            "mapped",
            "unknown",
            "reader_trials",
            "measure_value",
        )
        if any(key in row for row in rows)
    ]
    lines = ["\t".join(keys)] if keys else []
    lines.extend(
        "\t".join("" if row.get(key) is None else str(row[key]) for key in keys) for row in rows
    )
    for key in (
        "by_kind",
        "by_outcome",
        "family_count",
        "newest_created_at",
        "evidence_found",
        "evidence_sha256_now",
        "evidence_matches",
    ):
        if key in output:
            lines.append(f"{key}: {json.dumps(output[key], sort_keys=True)}")
    if "trials_text" in output:
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
    rdagent: Path | None, json_out: bool, action: Callable[[LedgerSnapshot, Path], dict[str, Any]]
) -> None:
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
        emit(output, json_out=json_out, fallback=_render(output))
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
        "by_kind": dict(Counter(r.kind for r in snapshot.records)),
        "by_outcome": dict(Counter(r.outcome for r in snapshot.records)),
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


@ledger_app.command("list")
def list_trials(
    kind: str | None = None,
    family: str | None = None,
    asset: str | None = None,
    outcome: str | None = None,
    source: str | None = None,
    limit: int = 50,
    rdagent_ledger: RD = None,
    json_out: JSON = False,
) -> None:
    """List matching trials newest first, retaining source provenance."""

    def select(snapshot: LedgerSnapshot, home: Path) -> dict[str, Any]:
        if not 1 <= limit <= 200:
            raise SpineError("BAD_PARAMETER", "Limit must be from 1 to 200.", "Use --limit 1..200.")
        records = [
            r
            for r in snapshot.records
            if all(
                value is None or getattr(r, key) == value
                for key, value in dict(
                    kind=kind, family_id=family, outcome=outcome, source=source
                ).items()
            )
            and (asset is None or asset_group(asset) in {asset_group(a) for a in r.assets})
        ]
        records.sort(
            key=lambda r: (r.created_at is not None, r.created_at or "", r.source, r.source_line),
            reverse=True,
        )
        return {"records": [asdict(r) for r in records[:limit]]}

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
        }

    _run(rdagent_ledger, json_out, select)


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

    _run(
        rdagent_ledger,
        json_out,
        lambda snapshot, home: {
            "question": question,
            **({"note": ASSET_NOTE} if "asset" in question else {}),
            "rows": query(
                snapshot, question, asset=asset, family=family, measure=measure, limit=limit
            ),
        },
    )
