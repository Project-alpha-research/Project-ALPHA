"""Read existing append-only ledgers without creating files or changing writers."""

from __future__ import annotations

import fcntl
import json
import tomllib
from collections import Counter
from contextlib import nullcontext
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

from alpha_cli.spine.errors import SpineError
from alpha_cli.spine.trial_record import FACTOR_SCHEMAS, TrialRecord, map_row

READER_VERSION = 1


@dataclass(frozen=True)
class LedgerSource:
    source: str
    file: str
    state: str = "missing"
    optional: bool = False
    rows: int = 0
    mapped: int = 0
    unknown: int = 0
    unknown_by_reason: dict[str, int] = field(default_factory=dict)


@dataclass(frozen=True)
class UnknownRow:
    source: str
    file: str
    line: int
    schema: str | None
    reason: str


@dataclass(frozen=True)
class LedgerSnapshot:
    records: list[TrialRecord]
    unknown: list[UnknownRow]
    sources: list[LedgerSource]
    raw_rows: dict[tuple[str, int], dict[str, Any]] = field(default_factory=dict)


def ledger_sources(
    home: Path, rdagent: Path | None = None, *, rdagent_optional: bool = False
) -> list[LedgerSource]:
    """Explicit RD-Agent paths take precedence over local source configuration."""
    config = home / "ledger/sources.toml"
    if rdagent is None and config.exists():
        try:
            settings = tomllib.loads(config.read_text(encoding="utf-8"))
            section = settings.get("rdagent", {})
            if not isinstance(section, dict):
                raise ValueError("rdagent must be a table")
            value = section.get("factor_ledger")
            if value is not None:
                if not isinstance(value, str) or not Path(value).is_absolute():
                    raise ValueError("factor_ledger must be an absolute path")
                rdagent = Path(value)
        except (ValueError, OSError) as exc:
            raise SpineError(
                "LEDGER_SOURCE_INVALID",
                f"{config}: {exc}",
                "Correct ledger/sources.toml or use --rdagent-ledger PATH.",
            ) from exc
    paths = [("spine", home / "ledger/trials.jsonl")]
    if rdagent is not None:
        paths.append(("rdagent", rdagent))
    return [
        LedgerSource(source, str(path.resolve()), optional=source == "spine" or rdagent_optional)
        for source, path in paths
    ]


def _read_bytes(path: Path) -> bytes:
    lock = path.with_suffix(path.suffix + ".lock")
    with lock.open("rb") if lock.exists() else nullcontext() as stream:
        if stream is not None:
            fcntl.flock(stream.fileno(), fcntl.LOCK_SH)
        return path.read_bytes()


def read_ledgers(sources: list[LedgerSource]) -> LedgerSnapshot:
    records: list[TrialRecord] = []
    unknown: list[UnknownRow] = []
    reports: list[LedgerSource] = []
    raw_rows: dict[tuple[str, int], dict[str, Any]] = {}
    for source in sources:
        path = Path(source.file)
        if not path.exists():
            reports.append(replace(source, state="missing"))
            continue
        lines = _read_bytes(path).splitlines(keepends=True)
        reasons: Counter[str] = Counter()
        mapped = 0
        for number, line in enumerate(lines, 1):
            schema, row = None, None
            try:
                if number == len(lines) and not line.endswith(b"\n"):
                    raise ValueError("incomplete last line (a writer may be mid-append)")
                row = json.loads(line)
                if not isinstance(row, dict):
                    raise ValueError("not a JSON object")
                schema = row.get("schema") if isinstance(row.get("schema"), str) else None
                record = map_row(source.source, path, number, row)
            except (ValueError, KeyError, TypeError, IndexError, AttributeError) as exc:
                reason = f"missing field: {exc.args[0]}" if isinstance(exc, KeyError) else str(exc)
                unknown.append(UnknownRow(source.source, str(path), number, schema, reason))
                if isinstance(row, dict):
                    raw_rows[(str(path.resolve()), number)] = row
                reasons[reason] += 1
            else:
                records.append(record)
                raw_rows[(record.source_file, number)] = row
                mapped += 1
        reports.append(
            replace(
                source,
                state="present",
                rows=len(lines),
                mapped=mapped,
                unknown=sum(reasons.values()),
                unknown_by_reason=dict(reasons),
            )
        )
    return LedgerSnapshot(records, unknown, reports, raw_rows)


def spine_snapshot(home: Path) -> LedgerSnapshot:
    """The spine ledger alone, as a snapshot; an unreadable file fails with its typed error."""
    path = (home / "ledger/trials.jsonl").resolve()
    try:
        return read_ledgers([LedgerSource("spine", str(path))])
    except OSError as exc:
        raise SpineError(
            "LEDGER_UNREADABLE",
            f"Cannot read the trial ledger {path}: {exc}",
            "Fix the file's permissions; never edit or delete ledger rows.",
        ) from exc


def family_counts(snapshot: LedgerSnapshot) -> list[dict[str, Any]]:
    """Use RD-Agent's existing clock/identity count and preserve unknown attempts."""
    groups: dict[str, list[TrialRecord]] = {}
    for record in snapshot.records:
        groups.setdefault(record.family_id, []).append(record)
    rd_unknown = sum(row.source == "rdagent" for row in snapshot.unknown)
    if rd_unknown:
        groups.setdefault("rdagent-factors", [])
    result = []
    for family, records in sorted(groups.items()):
        count = sum(
            r.counts_for_deflation
            and not (r.kind == "rule_test" and {"repeat", "error"}.intersection(r.labels))
            for r in records
        )
        if family == "rdagent-factors":
            from alpha_cli._rdagent_clocks import trial_family

            raw = [snapshot.raw_rows[(r.source_file, r.source_line)] for r in records]
            # An unmapped row of a factor schema (a status this reader has no mapping for yet)
            # is still a factor attempt: let the writer's own counter see it so the count is
            # never below the family size the writer recorded. Anything else adds one each.
            extra = [
                snapshot.raw_rows[key]
                for row in snapshot.unknown
                if row.source == "rdagent"
                and row.schema in FACTOR_SCHEMAS
                and (key := (str(Path(row.file).resolve()), row.line)) in snapshot.raw_rows
            ]
            try:
                count = len(trial_family(raw + extra)) + rd_unknown - len(extra)
            except (ValueError, KeyError, TypeError, IndexError, AttributeError):
                count = len(trial_family(raw)) + rd_unknown
        latest = records[-1] if records else None
        result.append(
            dict(
                family_id=family,
                kind=latest.kind if latest else "factor",
                source=latest.source if latest else "rdagent",
                rows=len(records),
                reader_trials=count,
                family_size_recorded=latest.family_size_recorded if latest else None,
                outcomes=dict(Counter(r.outcome for r in records)),
            )
        )
    return result


def trials_for_deflation(snapshot: LedgerSnapshot, family_id: str) -> dict[str, Any]:
    counts = family_counts(snapshot)
    # Every RD-Agent unknown row is already inside the factor family count; only unknown rows
    # of other files (the spine) still need adding. A row is counted once, never twice.
    outside = sum(row.source != "rdagent" for row in snapshot.unknown)
    return {
        "family_id": family_id,
        "family_trials": next(
            (r["reader_trials"] for r in counts if r["family_id"] == family_id), 0
        ),
        "all_trials": sum(r["reader_trials"] for r in counts) + outside,
        "unknown_rows": len(snapshot.unknown),
        "basis": "Family counts, which already include unknown RD-Agent rows, plus unknown rows "
        "of other files; every row is counted once, whether or not it can be interpreted.",
    }
