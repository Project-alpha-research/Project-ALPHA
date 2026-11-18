"""The RD-Agent trial ledger: reading it, validating its rows, importing historical items.

Split out of `rdagent_factor_eval` unchanged; that module re-exports these names."""

from __future__ import annotations

import fcntl
import json
import os
import re
import sys
from collections.abc import Iterator
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from alpha_cli._rdagent_clocks import (
    CLOCKS as CLOCKS,
)
from alpha_cli._rdagent_clocks import (
    trial_family,
    validate_clock_row,
)
from alpha_cli._rdagent_judge import (
    AUTHORITY,
    LABEL,
    LEDGER_SCHEMAS,
    LOOP_UNIVERSE,
    STATUSES,
    SURVIVORSHIP,
    TRIAL_SCHEMA,
    WINDOWS,
    canonical,
    outside_git,
    sha,
)
from alpha_cli._rdagent_stability import plain_name
from alpha_cli.toolbox.reserve import RESERVED_START
from alpha_core import DataError


class LedgerRows(list[dict[str, Any]]):
    """Physical ledger rows; iteration exposes supported schemas only.

    Length and indices retain physical line numbering for existing appenders. Unknown
    contents are available separately for conservative counting, never normal row logic.
    """

    def __iter__(self) -> Iterator[dict[str, Any]]:
        return (row for row in super().__iter__() if row["schema"] in LEDGER_SCHEMAS)

    @property
    def unknown_rows(self) -> list[dict[str, Any]]:
        return [row for row in super().__iter__() if row["schema"] not in LEDGER_SCHEMAS]


def _read_ledger(path: Path) -> LedgerRows:
    if not path.exists():
        return LedgerRows()
    raw = path.read_bytes()
    if raw and not raw.endswith(b"\n"):
        # Writers append under the ledger lock, so a partial last line is a crashed writer;
        # appending after it would corrupt the next row. Fail loud (research-integrity rule).
        raise DataError("incomplete trial ledger line")
    records = LedgerRows()
    for index, line in enumerate(raw.splitlines(), 1):
        try:
            row = json.loads(line)
            if not isinstance(row, dict) or not isinstance(row.get("schema"), str):
                raise ValueError("invalid schema or trial identity")
            if row["trial_index"] != index:
                raise ValueError("invalid schema or trial identity")
            if row["schema"] not in LEDGER_SCHEMAS:
                records.append(row)
                continue
            if not re.fullmatch("[0-9a-f]{64}", row["code_sha256"]):
                raise ValueError("invalid schema or trial identity")
            for key in (
                "name",
                "run_id",
                "iteration",
                "panel_sha256",
                "windows",
                "stage",
                "status",
                "p",
                "q",
                "family_size",
                "screen",
                "replay",
                "label",
                "survivorship",
                "authority",
                "total_trials",
            ):
                if key not in row:
                    raise ValueError(f"missing {key}")
            if not 0 <= row["p"] <= 1 or not 0 <= row["q"] <= 1 or row["authority"] != AUTHORITY:
                raise ValueError("invalid trial metrics or authority")
            statuses = (
                {"SUPPORT", "CONTRADICTION", "INSUFFICIENT", "INVALID"}
                if row["schema"] == "AlphaRuleTrialV1"
                else STATUSES
            )
            if row["status"] not in statuses or row["stage"] not in {"none", "screen", "replay"}:
                raise ValueError("invalid trial status or stage")
            if row["schema"] in {
                "AlphaRdagentFactorTrialV2",
                TRIAL_SCHEMA,
                "AlphaRuleTrialV1",
            } and (
                not isinstance(row["instruments"], list)
                or not row["instruments"]
                or any(not isinstance(s, str) or not s.strip() for s in row["instruments"])
                or not isinstance(row["exposure"], dict)
                or not {"previously_exposed", "worst_status", "matches"} <= row["exposure"].keys()
            ):
                raise ValueError("invalid V2 instruments or exposure")
            if row["schema"] == "AlphaRuleTrialV1":
                _validate_rule_row(row)
            if row["schema"] == TRIAL_SCHEMA:
                validate_clock_row(row)
                if "screen_rule" in row:
                    validate_honesty_row(row)
            if row["status"] == "IMPORTED":
                _validate_imported(row["imported"])
                if (
                    row["schema"] not in {"AlphaRdagentFactorTrialV2", TRIAL_SCHEMA}
                    or row["stage"] != "none"
                    or row["p"] != 1.0
                ):
                    raise ValueError("invalid imported trial")
        except (ValueError, TypeError, KeyError) as error:
            raise DataError(f"invalid trial ledger line {index}: {error}") from error
        records.append(row)
    unknown = records.unknown_rows
    if unknown:
        schemas = sorted({row["schema"] for row in unknown})
        print(
            f"rdagent-factor-eval: warning: {len(unknown)} ledger rows of other kinds "
            f"were skipped ({', '.join(schemas)}); counted with p = 1.0",
            file=sys.stderr,
        )
    return records


def _ledger_family(rows: list[dict[str, Any]]) -> dict[tuple[str, str], dict[str, Any]]:
    """Unknown rows contribute only a conservative trial, never a factor identity."""
    family = trial_family(
        [
            row
            for row in rows
            if row["schema"] in LEDGER_SCHEMAS and row["schema"] != "AlphaRuleTrialV1"
        ]
    )
    for row in rows:
        if row["schema"] not in LEDGER_SCHEMAS:
            family[(str(row["trial_index"]), "unknown")] = {"p": 1.0, "replay": {}}
    return family


def _validate_rule_row(row: dict[str, Any]) -> None:
    for key in ("family_id", "plain_name", "evidence", "warnings"):
        if key not in row:
            raise ValueError(f"missing {key}")
    if (
        not isinstance(row["family_id"], str)
        or not row["family_id"]
        or not isinstance(row["plain_name"], str)
        or not row["plain_name"]
        or not isinstance(row["warnings"], list)
        or any(not isinstance(w, str) for w in row["warnings"])
        or row["stage"] != "replay"
        or not isinstance(row["family_size"], int)
        or row["family_size"] < 1
        or row["total_trials"] < row["trial_index"]
        or row["windows"]["reserved_start"] != RESERVED_START
        or not {"history_start", "scored_start", "scored_end", "exploration_end"}
        <= row["windows"].keys()
        or not isinstance(row["evidence"]["trial"], str)
        or not re.fullmatch("[0-9a-f]{64}", row["evidence"]["sha256"])
    ):
        raise ValueError("invalid rule family metadata")


def _validate_imported(value: Any) -> None:
    if (
        not isinstance(value, dict)
        or set(value) != {"evaluated_by", "result_summary", "source", "code_path"}
        or any(not isinstance(v, str) or not v.strip() for v in value.values())
        or not Path(value["code_path"]).is_absolute()
    ):
        raise ValueError("invalid imported provenance")


def _historical_item(item: Any) -> dict[str, Any]:
    if not isinstance(item, dict) or set(item) != {
        "name",
        "code_path",
        "run_id",
        "iteration",
        "windows",
        "evaluated_by",
        "result_summary",
        "source",
    }:
        raise ValueError("invalid historical item fields")
    provenance = {k: item[k] for k in ("evaluated_by", "result_summary", "source", "code_path")}
    _validate_imported(provenance)
    if (
        any(not isinstance(item[k], str) or not item[k].strip() for k in ("name", "run_id"))
        or type(item["iteration"]) is not int
        or item["iteration"] < 0
        or not isinstance(item["windows"], dict)
        or set(item["windows"]) != set(WINDOWS)
    ):
        raise ValueError("invalid historical trial metadata")
    windows = item["windows"]
    for key in ("history", "exploration"):
        bounds = windows[key]
        if not isinstance(bounds, list) or len(bounds) != 2:
            raise ValueError("invalid historical window bounds")
        if any(
            not isinstance(d, str) or not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", d)
            for d in bounds
        ):
            raise ValueError("invalid historical window date")
        if date.fromisoformat(bounds[0]) > date.fromisoformat(bounds[1]):
            raise ValueError("reversed historical window")
    for key in ("panel_end", "reserved_start"):
        if not isinstance(windows[key], str) or not re.fullmatch(
            r"[0-9]{4}-[0-9]{2}-[0-9]{2}", windows[key]
        ):
            raise ValueError("invalid historical window date")
        date.fromisoformat(windows[key])
    if windows["reserved_start"] != RESERVED_START:
        # The exposure label is computed from this date; it must be the ledger's protected start.
        raise ValueError(f"historical reserved_start must be {RESERVED_START}")
    return provenance


def import_historical(ledger: Path, source: Path) -> list[dict[str, Any]]:
    from alpha_cli.rdagent_exposure import label_for, read_entries

    outside_git(ledger)
    try:
        items = json.loads(source.read_bytes())
    except (ValueError, UnicodeError) as error:
        raise DataError(f"invalid historical input: {error}") from error
    if not isinstance(items, list):
        raise DataError("historical input must be a list")
    with Path(str(ledger) + ".lock").open("a+b") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        history = _read_ledger(ledger)
        identities = {r["code_sha256"] for r in history if r["schema"] in LEDGER_SCHEMAS}
        entries = read_entries(ledger)
        rows: list[dict[str, Any]] = []
        for item in items:
            try:
                provenance = _historical_item(item)
                digest = sha(Path(item["code_path"]).read_bytes())
                if digest in identities:
                    raise ValueError("historical code hash already in trial ledger or batch")
            except (ValueError, TypeError, KeyError, OSError) as error:
                raise DataError(f"invalid historical item {len(rows) + 1}: {error}") from error
            row = {
                "schema": "AlphaRdagentFactorTrialV2",
                "trial_index": len(history) + len(rows) + 1,
                "name": item["name"],
                "plain_name": plain_name(item["name"]),
                "code_sha256": digest,
                "run_id": item["run_id"],
                "recorded_at": datetime.now(UTC).isoformat(),
                "iteration": item["iteration"],
                "windows": item["windows"],
                "status": "IMPORTED",
                "reason": "historical result imported without re-evaluation",
                "stage": "none",
                "p": 1.0,
                "q": 1.0,
                "screen": {},
                "replay": {},
                "panel_sha256": "0" * 64,
                "instruments": list(LOOP_UNIVERSE),
                "imported": provenance,
                "label": LABEL,
                "survivorship": SURVIVORSHIP,
                "authority": AUTHORITY,
            }
            row["exposure"] = label_for(row, entries)
            rows.append(row)
            identities.add(digest)
        for row in rows:
            row.update(
                family_size=len(_ledger_family([*history, *history.unknown_rows, *rows])),
                distinct_factors=len(
                    {
                        r["code_sha256"]
                        for r in [*history, *rows]
                        if r["schema"] != "AlphaRuleTrialV1"
                    }
                ),
                total_trials=len(history) + len(rows),
            )
        with ledger.open("ab", buffering=0) as stream:
            for row in rows:
                line = canonical(row)
                if stream.write(line) != len(line):
                    raise DataError("short trial ledger write")
                os.fsync(stream.fileno())
    return rows


def new_factor_row(
    factor: dict[str, Any],
    inputs: dict[str, str],
    index: int,
    run_id: str,
    iteration: int,
    symbols: list[str],
    survivorship: str,
    recorded_at: str,
) -> dict[str, Any]:
    from alpha_cli._rdagent_stats import FACTOR_DEFLATION_RULE, SCREEN_RULE

    return {
        **factor,
        "schema": TRIAL_SCHEMA,
        "plain_name": plain_name(factor["name"]),
        "trial_index": index,
        "run_id": run_id,
        "recorded_at": recorded_at,
        "iteration": iteration,
        "panel_sha256": inputs["panel_sha256"],
        "windows": WINDOWS,
        "instruments": symbols,
        "stage": "none",
        "p": 1.0,
        "q": 1.0,
        "screen": {},
        "replay": {},
        "lead_clock": factor["primary_clock"],
        "screen_rule": SCREEN_RULE,
        "deflation_rule": FACTOR_DEFLATION_RULE,
        "diagnostics": {},
        "factor_values": {
            "path": inputs["factor_values_path"],
            "sha256": inputs["factors_sha256"],
        },
        "label": LABEL,
        "survivorship": survivorship,
        "authority": AUTHORITY,
        "clocks": {
            c: {"status": "ERROR", "p": 1.0, "q": 1.0, "screen": {}, "replay": {}} for c in CLOCKS
        },
    }


def validate_honesty_row(row: dict[str, Any]) -> None:
    from alpha_cli._rdagent_stats import FACTOR_DEFLATION_RULE, SCREEN_RULE, screen_cutoff

    if (
        row["screen_rule"] != SCREEN_RULE
        or row["deflation_rule"] != FACTOR_DEFLATION_RULE
        or type(row["declared_direction"]) is not int
        or row["declared_direction"] not in (-1, 1)
        or row["primary_clock"] not in ("weekly", "monthly")
        or not isinstance(row["direction_reason"], str)
        or not row["direction_reason"].strip()
    ):
        raise ValueError("invalid declared factor rules")
    if row["screen_cutoff"] != screen_cutoff(row["screen_m"], row["screen_confirmed"]):
        raise ValueError("screen cutoff differs from recorded counts")
    if row["status"] != "REPEAT" and any(
        t["replay"] for c, t in row["clocks"].items() if c != row["primary_clock"]
    ):
        raise ValueError("diagnostic clock cannot create replay evidence")
