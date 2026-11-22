"""Lossless provenance and common vocabulary for historical trial rows."""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, fields
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from alpha_cli._rdagent_stability import plain_name, recorded_status, status_reason
from alpha_cli.spine.reading import (
    LEGACY_SETUP_OUTCOMES,
    OLD_SETUP_OUTCOMES,
    SETUP_WORDS,
    WORDS,
    old_grade_text,
)

OUTCOMES = ("supported", "rejected", "inconclusive", "invalid", "error", "recorded")
FACTOR_OUTCOMES = {
    "CANDIDATE": "supported",
    "DEFLATION_FAIL": "rejected",
    "SCREEN_FAIL": "rejected",
    "SPREAD_FAIL": "rejected",
    "REPLAY_FAIL": "rejected",
    "FAST_ONLY": "rejected",
    "DEGENERATE": "invalid",
    "LOOKAHEAD": "invalid",
    "UNSTABLE": "invalid",
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
    reason: str | None = None
    measure_clock: str | None = None
    # Owner words never branch code: ``outcome`` is what is printed; ``machine_outcome`` is the
    # old four-way word (and the old letter stays in ``raw_status``). Counting reads neither.
    machine_outcome: str | None = None
    evidence: str | None = None
    aim_relation: str | None = None


# What was tested, independent of the code version that tested it: spec hash, assets, data window
# start and end as used, bar size, the data store, and the content of the data (``idea_id``: the
# spec hash with the fingerprint of the exact bars and dividends used). Two stores, or one store
# after a price revision or a change of adjustment basis, are different tests. The one definition:
# ledger repeat labelling, the family count (deflation) and the same-asset count all build it here.
TestKey = tuple[str, tuple[str, ...], str | None, str | None, str | None, str | None, str | None]


def make_test_key(
    spec_hash: str | None,
    assets: tuple[str, ...],
    data_start: str | None,
    data_end: str | None,
    bar_size: str | None,
    *,
    store: str | None,
    data_id: str | None,
) -> TestKey | None:
    """The test key, or None when the spec hash or the asset is missing (an unmatchable test).

    A missing store or data id (rows written before they were recorded) stays None in the key, so
    such a row never matches a row that records them.
    """
    if not spec_hash or not assets:
        return None
    return (spec_hash, assets, data_start, data_end, bar_size, store, data_id)


def _row_bar_size(row: dict[str, Any]) -> str | None:
    if isinstance(row.get("bar_size"), str) and row["bar_size"]:
        return str(row["bar_size"])
    return "1D" if row.get("periods_per_year") in (252, 365) else None


def row_test_key(row: dict[str, Any]) -> TestKey | None:
    """The test key of a raw spine rule-test ledger row; None for any other row or a thin one."""
    if row.get("kind", "rule_test") not in {"rule_test", "screen_trial"}:
        return None
    spec, symbol = row.get("spec_sha256"), row.get("symbol")
    start, end = row.get("first_ts"), row.get("last_ts")
    store, data_id = row.get("store"), row.get("idea_id")
    if not isinstance(spec, str) or not isinstance(symbol, str):
        return None
    if not all(v is None or isinstance(v, str) for v in (start, end, store, data_id)):
        return None
    return make_test_key(
        spec, (symbol,), start, end, _row_bar_size(row), store=store, data_id=data_id
    )


def _strings(value: Any) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)) or any(not isinstance(v, str) for v in value):
        raise ValueError("expected a list of strings")
    return tuple(value)


def _rule_words(row: dict[str, Any], status: Any, machine: str) -> tuple[str, str | None]:
    """Owner outcome and evidence of a rule-test row; a row with only a letter says so."""
    found = row.get("evidence")
    if found is not None and found != "fault" and found not in WORDS:
        raise ValueError(f"unknown evidence: {found}")
    if machine in {"error", "recorded"}:
        return machine, found
    return (found if found is not None else old_grade_text(status)), found


def _setup_words(row: dict[str, Any]) -> tuple[str, str, str | None]:
    """Machine word, owner word and a note for a setup row; old and new words both read."""
    raw = row["outcome"]
    found = row.get("evidence")
    if found is not None and found not in SETUP_WORDS:
        raise ValueError(f"unknown evidence: {found}")
    if raw in OLD_SETUP_OUTCOMES:
        return (
            raw,
            found or OLD_SETUP_OUTCOMES[raw],
            None if found else "recorded under the old wording",
        )
    if raw not in SETUP_WORDS:
        raise ValueError(f"unknown study outcome: {raw}")
    return LEGACY_SETUP_OUTCOMES[raw], found or raw, None


def _spine(row: dict[str, Any]) -> dict[str, Any]:
    raw_kind = row.get("kind", "rule_test")
    if not isinstance(raw_kind, str):
        raise ValueError("invalid kind")
    kind, subkind = raw_kind, None
    if raw_kind.startswith("tool:"):
        kind, subkind = "tool", raw_kind[5:]
        if not subkind:
            raise ValueError("missing tool name")
    elif raw_kind not in {
        "rule_test",
        "setup_find",
        "setup_study",
        "setup_trade",
        "reserved_confirmation",
    }:
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
        machine = "error" if "error" in labels else outcomes[status]
        outcome, evidence_word = _rule_words(row, status, machine)
    family = "spine-other"
    machine_outcome, evidence_word, note = None, row.get("evidence"), None
    if kind == "rule_test":
        machine_outcome = machine
        if not isinstance(row["rule"], str) or not row["rule"]:
            raise ValueError("missing rule name")
        family = f"spine:{row['rule']}"
    elif kind == "tool":
        from alpha_cli.toolbox.registry import ALIASES

        subkind = ALIASES.get(str(subkind), subkind)
        legacy = next((name for name, tool in ALIASES.items() if tool == subkind), subkind)
        family = f"spine-tool:{legacy}"
        outcome = row.get("outcome", "recorded")
    elif kind == "other" and subkind == "screen_trial":
        family = "spine-screen"
    elif kind == "setup_find":
        family = f"spine-setup:{row['name']}"
    elif kind == "reserved_confirmation":
        # The owner's one look at the reserved period: its own family, never a counted trial, so
        # it changes no family count used to deflate another test.
        family = f"spine-confirmation:{row['rule']}"
    elif kind in {"setup_study", "setup_trade"}:
        family = "setup:" + " ".join(row["idea"].casefold().split())
        machine_outcome, outcome, note = _setup_words(row)
        evidence_word = outcome
    evidence = f"runs/{row['run_id']}/manifest.json" if row.get("run_id") else None
    if kind == "tool":
        evidence = row.get("tool_output")
    elif kind == "setup_find":
        evidence = f"setups/{row['find_id']}/manifest.json" if row.get("find_id") else None
    elif kind in {"setup_study", "setup_trade"}:
        evidence = (
            f"setup-trades/{row['trade_id']}/manifest.json"
            if kind == "setup_trade"
            else f"setup-studies/{row['study_id']}/manifest.json"
        )
    return dict(
        kind=kind,
        subkind=subkind,
        family_id=family,
        family_size_recorded=None,
        counts_for_deflation=kind == "rule_test"
        or (kind in {"setup_study", "setup_trade"} and "repeat" not in labels),
        name=row.get("name"),
        spec_hash=row.get("spec_sha256"),
        assets=_strings(row["assets"])
        if kind in {"setup_study", "setup_trade"}
        else (row["symbol"],)
        if row.get("symbol")
        else (),
        bar_size=_row_bar_size(row),
        windows={"data_start": row.get("first_ts"), "data_end": row.get("last_ts")},
        outcome=outcome,
        raw_status=status,
        measures={
            k: row.get(k)
            for k in (
                ("occurrences", "mean_net_return", "excess_over_drift", "random_date_p")
                if kind in {"setup_study", "setup_trade"}
                else ("oos_sharpe", "benchmark_sharpe", "dsr")
            )
        },
        evidence_path=evidence,
        evidence_sha256=None,
        labels=labels,
        created_at=row["recorded_at"],
        created_at_basis="recorded",
        reason=note,
        machine_outcome=machine_outcome,
        evidence=evidence_word if kind in {"rule_test", "setup_study", "setup_trade"} else None,
        aim_relation=row.get("aim_relation") if kind == "rule_test" else None,
    )


def _run_date(run_id: str | None) -> tuple[str | None, str]:
    prefix = run_id[:10] if isinstance(run_id, str) else ""
    try:
        parsed = date.fromisoformat(prefix)
    except ValueError:
        return None, "not recorded"
    return (prefix, "run-id date") if parsed.isoformat() == prefix else (None, "not recorded")


def universe_label(row: dict[str, Any]) -> str:
    if "universe_includes_delisted" in row:
        flag = row["universe_includes_delisted"]
        if type(flag) is not bool:
            raise ValueError("universe_includes_delisted must be a boolean")
        return "includes-delisted" if flag else "survivor-universe"
    value = row.get("survivorship", "")
    text = (value if isinstance(value, str) else " ".join(_strings(value))).lower()
    counts = re.findall(r"\b(\d+)\s+(?:(?:instruments?|coins?|names?)\s+)?later\s+delisted\b", text)
    if any(int(count) > 0 for count in counts):
        return "includes-delisted"
    if re.search(
        r"^survivors?$|survivors?[ -]only|only\s+survivors?|"
        r"(?:today.s|current)\s+survivors|from.*survivors|are\s+survivors|survivors\s+chosen",
        text,
    ):
        return "survivor-universe"
    return "universe-not-recorded"


def _rdagent(row: dict[str, Any]) -> dict[str, Any]:
    rule = row["schema"] == "AlphaRuleTrialV1"
    status = row["status"] if rule else recorded_status(row)
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
    measure_clock = None if rule else "daily"
    measures = {k: row[k] for k in ("p", "q")}
    if rule:
        measures["annualised_excess"] = row["replay"].get("annualised_excess")
    else:
        screen = row["screen"]
        if row["schema"] == "AlphaRdagentFactorTrialV3":
            for clock in ("daily", "weekly", "monthly"):
                if not isinstance(row["clocks"][clock], dict):
                    raise ValueError("invalid clock")
            lead = row["clocks"][row["lead_clock"]]
            if all(k in lead for k in ("p", "q")):
                measures.update({k: lead[k] for k in ("p", "q")})
                screen = lead["screen"]
                measure_clock = row["lead_clock"]
            else:
                screen = row["clocks"].get("daily", {}).get("screen", row["screen"])
        measures["mean_ic"] = screen.get("mean_ic")
        result = (
            row.get("clocks", {})
            .get(row.get("lead_clock", "daily"), row)
            .get("replay", {})
            .get("deflated_sharpe", {})
        )
        measures.update(
            {k: result[k] for k in ("dsr", "deflation_n", "deflation_variance") if k in result}
        )
        measures.update(
            {
                k: row.get(k)
                for k in (
                    "screen_cutoff",
                    "screen_m",
                    "screen_confirmed",
                    "bh_q_diagnostic",
                    "expected_chance_passes",
                )
                if k in row
            }
        )
    labels = tuple(
        label
        for label, present in (
            ("exploratory", row["label"].startswith("exploratory")),
            ("not-admitted", row["authority"].get("admitted") is False),
            ("previously-exposed", row.get("exposure", {}).get("previously_exposed") is True),
            (universe_label(row), True),
            ("repeat", status == "REPEAT"),
            ("imported", status == "IMPORTED"),
        )
        if present
    )
    if "universe_includes_delisted" in row and type(row["universe_includes_delisted"]) is not bool:
        raise ValueError("universe_includes_delisted must be a boolean")
    created, basis = _run_date(row["run_id"])
    if "recorded_at" in row:
        stamp = datetime.fromisoformat(row["recorded_at"])
        if stamp.tzinfo is None:
            raise ValueError("recorded_at must have a timezone")
        created, basis = stamp.astimezone(UTC).isoformat(), "recorded"
    evidence = row["evidence"] if rule else row.get("evidence", {})
    return dict(
        kind="rule_family" if rule else "factor",
        subkind=None,
        family_id=f"rule:{row['family_id']}" if rule else "rdagent-factors",
        family_size_recorded=row["family_size"],
        counts_for_deflation=rule or status != "REPEAT",
        name=(row.get("plain_name") or row.get("name")) if rule else plain_name(row["name"]),
        spec_hash=row["code_sha256"],
        assets=_strings(row["instruments"] if rule else row.get("instruments", [])),
        bar_size="1D",
        windows=windows,
        outcome=outcomes[status],
        raw_status=status,
        reason=status_reason(row),
        measure_clock=measure_clock,
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
    values["machine_outcome"] = values.get("machine_outcome") or values["outcome"]
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
