"""Lossless provenance and common vocabulary for historical trial rows."""

from __future__ import annotations

import math
from dataclasses import dataclass, fields
from datetime import date
from pathlib import Path
from typing import Any

OUTCOMES = ("supported", "rejected", "inconclusive", "invalid", "error", "recorded")
FACTOR_OUTCOMES = {
    "CANDIDATE": "supported",
    "SCREEN_FAIL": "rejected",
    "REPLAY_FAIL": "rejected",
    "FAST_ONLY": "rejected",
    "DEGENERATE": "invalid",
    "LOOKAHEAD": "invalid",
    "FAILED": "error",
    "ERROR": "error",
    "IMPORTED": "recorded",
    "REPEAT": "recorded",
}
RULE_OUTCOMES = {
    "SUPPORT": "supported",
    "CONTRADICTION": "rejected",
    "INSUFFICIENT": "inconclusive",
    "INVALID": "invalid",
}
FACTOR_SCHEMAS = frozenset(f"AlphaRdagentFactorTrialV{v}" for v in (1, 2, 3))


@dataclass(frozen=True)
class TrialRecord:
    trial_id: str
    source: str
    schema: str
    kind: str
    subkind: str | None
    family_id: str
    family_size_recorded: int | None
    counts_for_deflation: bool
    name: str | None
    spec_hash: str | None
    assets: tuple[str, ...]
    bar_size: str | None
    windows: dict[str, str | None]
    outcome: str
    raw_status: str | None
    measures: dict[str, float | None]
    evidence_path: str | None
    evidence_sha256: str | None
    labels: tuple[str, ...]
    created_at: str | None
    created_at_basis: str
    run_id: str | None
    source_file: str
    source_line: int


def _strings(value: Any) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)) or any(not isinstance(v, str) for v in value):
        raise ValueError("expected a list of strings")
    return tuple(value)


def _spine(row: dict[str, Any]) -> dict[str, Any]:
    raw_kind = row.get("kind", "rule_test")
    if not isinstance(raw_kind, str):
        raise ValueError("invalid kind")
    kind, subkind = raw_kind, None
    if raw_kind.startswith("tool:"):
        kind, subkind = "tool", raw_kind[5:]
        if not subkind:
            raise ValueError("missing tool name")
    elif raw_kind not in {"rule_test", "setup_find"}:
        kind, subkind = "other", raw_kind
    labels = _strings(row["labels"])
    outcome, status = "recorded", row.get("verdict")
    if kind == "rule_test":
        status = row["verdict"]
        outcomes = {
            "A": "supported",
            "B": "supported",
            "C": "inconclusive",
            "D": "rejected",
            "F": "rejected",
            None: "recorded",
        }
        if status not in outcomes:
            raise ValueError(f"unknown verdict: {status}")
        outcome = "error" if "error" in labels else outcomes[status]
    family = "spine-other"
    if kind == "rule_test":
        if not isinstance(row["rule"], str) or not row["rule"]:
            raise ValueError("missing rule name")
        family = f"spine:{row['rule']}"
    elif kind == "tool":
        family = f"spine-tool:{subkind}"
    elif kind == "setup_find":
        family = f"spine-setup:{row['name']}"
    evidence = f"runs/{row['run_id']}/manifest.json" if row.get("run_id") else None
    if kind == "tool":
        evidence = row.get("tool_output")
    elif kind == "setup_find":
        evidence = f"setups/{row['find_id']}/manifest.json" if row.get("find_id") else None
    return dict(
        kind=kind,
        subkind=subkind,
        family_id=family,
        family_size_recorded=None,
        counts_for_deflation=kind == "rule_test",
        name=row.get("name"),
        spec_hash=row.get("spec_sha256"),
        assets=(row["symbol"],) if row.get("symbol") else (),
        bar_size=row["bar_size"]
        if isinstance(row.get("bar_size"), str) and row["bar_size"]
        else "1D"
        if row.get("periods_per_year") in (252, 365)
        else None,
        windows={"data_start": row.get("first_ts"), "data_end": row.get("last_ts")},
        outcome=outcome,
        raw_status=status,
        measures={k: row.get(k) for k in ("oos_sharpe", "benchmark_sharpe", "dsr")},
        evidence_path=evidence,
        evidence_sha256=None,
        labels=labels,
        created_at=row["recorded_at"],
        created_at_basis="recorded",
    )


def _run_date(run_id: str | None) -> tuple[str | None, str]:
    prefix = run_id[:10] if isinstance(run_id, str) else ""
    try:
        parsed = date.fromisoformat(prefix)
    except ValueError:
        return None, "not recorded"
    return (prefix, "run-id date") if parsed.isoformat() == prefix else (None, "not recorded")


def _rdagent(row: dict[str, Any]) -> dict[str, Any]:
    rule = row["schema"] == "AlphaRuleTrialV1"
    status = row["status"]
    outcomes = RULE_OUTCOMES if rule else FACTOR_OUTCOMES
    if status not in outcomes:
        raise ValueError(f"unknown status: {status}")
    window = row["windows"]
    if rule and (not isinstance(row["family_id"], str) or not row["family_id"]):
        raise ValueError("invalid family_id")
    if not rule:
        _strings(window["history"])
        _strings(window["exploration"])
    windows = {
        "data_start": window["history_start"] if rule else window["history"][0],
        "data_end": window["exploration_end"] if rule else window["panel_end"],
        "scored_start": window["scored_start"] if rule else window["exploration"][0],
        "scored_end": window["scored_end"] if rule else window["exploration"][1],
        "reserved_start": window["reserved_start"],
    }
    measures = {k: row[k] for k in ("p", "q")}
    if rule:
        measures["annualised_excess"] = row["replay"].get("annualised_excess")
    else:
        screen = row["screen"]
        if row["schema"] == "AlphaRdagentFactorTrialV3":
            for clock in ("daily", "weekly", "monthly"):
                if not isinstance(row["clocks"][clock], dict):
                    raise ValueError("invalid clock")
            screen = row["clocks"][row["lead_clock"]]["screen"]
        measures["mean_ic"] = screen.get("mean_ic")
    labels = tuple(
        label
        for label, present in (
            ("exploratory", row["label"].startswith("exploratory")),
            ("not-admitted", row["authority"].get("admitted") is False),
            ("previously-exposed", row.get("exposure", {}).get("previously_exposed") is True),
            ("survivor-universe", bool(row["survivorship"])),
            ("repeat", status == "REPEAT"),
            ("imported", status == "IMPORTED"),
        )
        if present
    )
    created, basis = _run_date(row["run_id"])
    evidence = row["evidence"] if rule else row.get("evidence", {})
    return dict(
        kind="rule_family" if rule else "factor",
        subkind=None,
        family_id=f"rule:{row['family_id']}" if rule else "rdagent-factors",
        family_size_recorded=row["family_size"],
        counts_for_deflation=rule or status != "REPEAT",
        name=row.get("plain_name") or row.get("name"),
        spec_hash=row["code_sha256"],
        assets=_strings(row["instruments"] if rule else row.get("instruments", [])),
        bar_size="1D",
        windows=windows,
        outcome=outcomes[status],
        raw_status=status,
        measures=measures,
        evidence_path=evidence.get("trial" if rule else "series_manifest"),
        evidence_sha256=evidence.get("sha256"),
        labels=labels,
        created_at=created,
        created_at_basis=basis,
    )


def _validate(record: TrialRecord) -> None:
    for field in fields(record):
        value = getattr(record, field.name)
        text_expected = field.type == "str" or field.type == "str | None" and value is not None
        if text_expected and not isinstance(value, str):
            raise ValueError(f"invalid {field.name}: expected text")
    _strings(record.assets)
    if record.family_size_recorded is not None and (
        type(record.family_size_recorded) is not int or record.family_size_recorded < 0
    ):
        raise ValueError("invalid family_size")
    if any(v is not None and not isinstance(v, str) for v in record.windows.values()):
        raise ValueError("invalid window")
    for key, value in record.measures.items():
        if value is not None:
            if type(value) not in (int, float) or not math.isfinite(value):
                raise ValueError(f"invalid measure: {key}")
            record.measures[key] = float(value)


def map_row(source: str, path: Path, line_no: int, row: dict[str, Any]) -> TrialRecord:
    """Map known shapes; mapping failures are reported by the snapshot reader."""
    schema, index = row["schema"], row["trial_index"]
    if type(index) is not int or index < 1:
        raise ValueError("invalid trial_index")
    if schema == "AlphaTrialV1" and source == "spine":
        values = _spine(row)
    elif schema in FACTOR_SCHEMAS | {"AlphaRuleTrialV1"} and source == "rdagent":
        values = _rdagent(row)
    else:
        raise ValueError(f"unknown schema: {schema}")
    record = TrialRecord(
        trial_id=f"{source}:{index}",
        source=source,
        schema=schema,
        run_id=row.get("run_id"),
        source_file=str(path.resolve()),
        source_line=line_no,
        **values,
    )
    _validate(record)
    return record
