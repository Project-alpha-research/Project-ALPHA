"""Read a closed projection of factor receipts and the default ledger, without execution.

No request string is a path. No artifact reference in a receipt is followed. Counts that the
writer did not record remain unknown: in particular, candidate is not a deflation verdict.
"""

from __future__ import annotations

import json
import math
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from alpha_web.api.errors import safe_message
from alpha_web.api.rdagent_models import (
    RdAgentCap,
    RdAgentClock,
    RdAgentDetail,
    RdAgentFactor,
    RdAgentRun,
    RdAgentRunList,
    RecordedFact,
)

MISSING = "not recorded by this run"
RECEIPT_SCHEMA = "AlphaRdagentFactorRunReceiptV1"
FACTOR_SCHEMAS = {f"AlphaRdagentFactorTrialV{version}" for version in (1, 2, 3)}
MAX_FILE_BYTES = 32 * 1024 * 1024
STATUS_SENTENCES = {
    "NOT_RUN": "This check was not run.",
    "OK": "This stage produced usable values.",
    "PASS": "This recorded stage passed; confirmation is still required.",
    "FAIL": "This recorded stage failed.",
    "FAILED": "The factor produced no usable values; the specific reason was not recorded.",
    "critic_rejected": "The code ran, but RD-Agent's critic did not accept it.",
    "cap_reached": "The call cap stopped the coder before it produced usable values.",
    "exception": "The code raised an exception and produced no usable values.",
    "bad_output": "The code was missing or did not produce the required numeric factor column.",
    "LOOKAHEAD": "The factor changed when future data was removed, so it cannot be trusted.",
    "UNSTABLE": "The factor changed on identical inputs, so its result is not reproducible.",
    "DEGENERATE": "There were too few usable observations or too little variation to judge it.",
    "ERROR": "Evaluation failed; this factor needs investigation.",
    "SCREEN_FAIL": "The factor did not pass the ranking test.",
    "SPREAD_FAIL": "The top third did not beat the bottom third before costs.",
    "REPLAY_FAIL": "The factor did not retain positive excess returns after costs.",
    "CANDIDATE": (
        "A weekly or monthly clock passed screening and replay; confirmation is still required."
    ),
    "FAST_ONLY": "Only the daily clock passed; this is not a swing candidate.",
    "REPEAT": "This code was already evaluated and supplies no new evidence.",
    "IMPORTED": "This is a recorded historical trial, not a new evaluation by this run.",
    "refused_closed_family": (
        "The idea family was already closed, so the proposal was refused before coding."
    ),
    "no_admissible_idea": "Repeated closed-family proposals ended this round before coding.",
    "abandoned_at_cap": "The cap stopped an unfinished round; no trial was created for it.",
}
REFUSED_STATUSES = frozenset({"refused_closed_family", "no_admissible_idea"})
SCREENED = frozenset({"SPREAD_FAIL", "REPLAY_FAIL", "PASS"})
SPREAD_CHECKED = frozenset({"REPLAY_FAIL", "PASS"})
FUNNEL = (
    "proposed",
    "refused_closed_family",
    "code_ran",
    "passed_rank_screen",
    "passed_spread_check",
    "passed_deflation",
)
SCREEN = (
    "status",
    "mean_ic",
    "n",
    "effective_n",
    "z",
    "p",
    "direction",
    "warnings",
    "mean_ci_95.lower",
    "mean_ci_95.upper",
)
SPREAD = (
    "status",
    "reason",
    "top_third_mean_return",
    "bottom_third_mean_return",
    "mean_spread",
    "annualized_spread",
    "t",
    "decision_days",
    "top_share_changed_per_rebalance",
    "estimated_annual_cost",
    "mean_ci_95.lower",
    "mean_ci_95.upper",
)
REPLAY = (
    "status",
    "counted_only",
    "net_annual_excess",
    "gross_annual_excess",
    "net_sharpe",
    "net.annualized_return",
    "net.compounded_return",
    "net.sharpe",
    "net.max_drawdown",
    "gross.annualized_return",
    "gross.compounded_return",
    "gross.sharpe",
    "gross.max_drawdown",
    "gap_policy.delisting_haircut",
    "gap_policy.assumption",
    "mean_turnover",
    "annual_cost",
    "turnover_per_rebalance",
    "rebalances",
    "haircuts_applied",
    "writeoff_instruments",
    "written_off_at_panel_end",
)
DEFLATION = ("sharpe", "psr", "dsr", "expected_max_sharpe", "n_trials", "threshold", "passed")
UNIVERSE = (
    "instruments",
    "universe_text",
    "universe_includes_delisted",
    "instruments_ended_early",
    "missing_instrument_days",
    "longest_gap",
    "gap_policy.delisting_haircut",
    "gap_policy.assumption",
    "identity_jump_policy.min_gap_days",
    "identity_jump_policy.ratio",
)
CACHE = (
    "cache_hit_rate",
    "prompt_tokens",
    "cached_tokens",
    "reasoning_tokens",
    "completion_tokens",
    "distinct_providers",
    "unknown_provider_calls",
    "usage_unknown_attempts",
    "router_session_sent",
)


def status_sentence(status: str, failure_reason: str | None) -> str:
    key = failure_reason if status == "FAILED" and failure_reason else status
    if key not in STATUS_SENTENCES:
        raise ValueError("Unrecognised RD-Agent factor status or failure reason.")
    return STATUS_SENTENCES[key]


TEXT_CHUNK = 400


def _clean(piece: str) -> str:
    """Slashes joining words (admitted/approved) are prose; paths start a word and are redacted."""
    tokens = [
        token if token.startswith(("/", "~")) or ":" in token else token.replace("/", "\u2215")
        for token in f"x {piece}".split(" ")
    ]
    protected = " ".join(tokens)
    return safe_message(protected, fallback="x ")[2:].replace("\u2215", "/")


def _text(value: str) -> str:
    """Redact secrets and paths without cutting long recorded text or refusing a leading bracket.

    safe_message keeps 500 characters and rejects text that starts with a bracket, so the text is
    prefixed and passed in whole-word pieces; secrets contain no spaces, so no piece splits one.
    """
    words, pieces, current = value.split(), [], ""
    for word in words:
        if current and len(current) + len(word) >= TEXT_CHUNK:
            pieces.append(current)
            current = ""
        current = f"{current} {word}".strip()
    if current:
        pieces.append(current)
    cleaned = [_clean(piece) for piece in pieces]
    return " ".join(cleaned) if cleaned else safe_message("", fallback="Recorded text unavailable.")


def _get(row: dict[str, Any], path: str) -> Any:
    current: Any = row
    for part in path.split("."):
        if not isinstance(current, dict):
            if current is None:
                return None
            raise ValueError("Recorded RD-Agent object has an invalid shape.")
        current = current.get(part)
    return current


def counted(value: int, basis: str) -> RecordedFact:
    """A figure obtained by counting recorded rows or subtracting two recorded times."""
    return RecordedFact(value=value, basis=basis)


def fact(value: Any) -> RecordedFact:
    if value is None:
        return RecordedFact(value=None, reason=MISSING)
    if isinstance(value, str):
        return RecordedFact(value=_text(value))
    if isinstance(value, (bool, int, float)):
        if isinstance(value, float) and not math.isfinite(value):
            raise ValueError("Non-finite RD-Agent figure.")
        return RecordedFact(value=value)
    if isinstance(value, list) and all(isinstance(item, str) for item in value):
        return RecordedFact(value=[_text(item) for item in value])
    raise ValueError("Recorded RD-Agent fact has an invalid shape.")


def project(row: dict[str, Any], fields: tuple[str, ...]) -> dict[str, RecordedFact]:
    return {field: fact(_get(row, field)) for field in fields}


def _object(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError("Recorded RD-Agent file must contain JSON objects.")
    return value


def _read(root: Path, relative: str) -> bytes | None:
    """Only constant relative names reach here; refuse links at every path component."""
    path = root
    for part in Path(relative).parts:
        path = path / part
        if path.is_symlink():
            raise ValueError("RD-Agent recorded files must not be symbolic links.")
    if not path.exists():
        return None
    if not path.is_file() or path.stat().st_size > MAX_FILE_BYTES:
        raise ValueError("RD-Agent recorded file is not a bounded regular file.")
    with path.open("rb") as stream:
        content = stream.read(MAX_FILE_BYTES + 1)
    if len(content) > MAX_FILE_BYTES:
        raise ValueError("RD-Agent recorded file exceeds the read limit.")
    return content


def _json(root: Path, relative: str) -> dict[str, Any]:
    content = _read(root, relative)
    return {} if content is None else _object(json.loads(content))


def _lines(root: Path, relative: str) -> tuple[list[dict[str, Any]], str | None]:
    content = _read(root, relative)
    if content is None:
        return [], MISSING
    lines = content.splitlines(keepends=True)
    incomplete = bool(lines and not lines[-1].endswith(b"\n"))
    if incomplete:
        lines = lines[:-1]
    rows = [_object(json.loads(line)) for line in lines]
    return (
        rows,
        "The last record is still being written; refresh to read it." if incomplete else None,
    )


def _runs(root: Path) -> list[tuple[Path, dict[str, Any]]]:
    if not root.exists():
        return []
    if root.is_symlink() or not root.is_dir():
        raise ValueError("The RD-Agent runs directory is not a regular directory.")
    result: list[tuple[Path, dict[str, Any]]] = []
    seen: set[str] = set()
    for folder in sorted(root.iterdir()):
        if folder.is_symlink() or not folder.is_dir():
            continue
        receipt = _json(folder, "receipt.json")
        if receipt.get("schema") != RECEIPT_SCHEMA:
            continue
        run_id = receipt.get("run_id")
        if not isinstance(run_id, str) or not re.fullmatch(
            r"[A-Za-z0-9][A-Za-z0-9_.-]{0,199}", run_id
        ):
            raise ValueError("Invalid recorded RD-Agent run identity.")
        if run_id in seen:
            raise ValueError("Duplicate recorded RD-Agent run identity.")
        seen.add(run_id)
        result.append((folder, receipt))
    return sorted(result, key=lambda item: _started(item[1]), reverse=True)


def _started(receipt: dict[str, Any]) -> float:
    value = receipt.get("started_at")
    if value is None:
        return float("-inf")
    stamp = datetime.fromisoformat(value)
    if stamp.tzinfo is None:
        raise ValueError("RD-Agent timestamps must include a timezone.")
    return stamp.timestamp()


def _summary(
    folder: Path,
    receipt: dict[str, Any],
    panel: dict[str, Any],
    counts: dict[str, RecordedFact],
) -> RdAgentRun:
    exit_status = receipt.get("exit_status")
    reason = str(receipt.get("loop_reason", "")).lower()
    outcome = None
    if exit_status is not None:
        outcome = "completed" if exit_status == 0 else "error"
        if any(word in reason for word in ("budget_exhausted", "cap", "wall-clock limit")):
            outcome = "stopped by a cap"
    return RdAgentRun(
        run_id=receipt["run_id"],
        folder=_text(folder.name),
        started_at=fact(receipt.get("started_at")),
        ended_at=fact(receipt.get("ended_at")),
        outcome=fact(outcome),
        rounds_completed=fact(
            receipt.get("rounds_completed", _get(receipt, "memory.rounds_completed"))
        ),
        counted_calls=fact(
            receipt.get("counted_calls", _get(receipt, "gateway_status.this_run.calls"))
        ),
        local_embedding_calls=fact(receipt.get("local_embedding_calls")),
        provider_embedding_calls=fact(receipt.get("provider_embedding_calls")),
        cost_usd=fact(_get(receipt, "gateway_status.this_run.usd")),
        factors_proposed=counts["proposed"],
        stages=counts,
        universe_size=_universe_size(panel),
        universe_includes_delisted=fact(panel.get("universe_includes_delisted")),
    )


def _universe_size(panel: dict[str, Any]) -> RecordedFact:
    names = panel.get("instruments")
    if isinstance(names, (dict, list)):
        return counted(len(names), "counted from the instruments listed in the panel receipt")
    return fact(None)


def _ledger_factor_rows(
    ledger_rows: list[dict[str, Any]], run_id: str, folder: Path
) -> list[dict[str, Any]]:
    """Older runs recorded their folder name, not the receipt's run id, in the ledger."""
    return [
        row
        for row in ledger_rows
        if row.get("run_id") in {run_id, folder.name} and row.get("schema") in FACTOR_SCHEMAS
    ]


def _funnel(
    receipt: dict[str, Any],
    factor_rows: list[dict[str, Any]] | None,
    rounds: list[dict[str, Any]] | None,
) -> dict[str, RecordedFact]:
    """Recorded funnel figures win; gaps are filled only by counting recorded rows."""
    recorded = _object(receipt.get("funnel", {}))
    result = project(recorded, FUNNEL)
    basis_rows = "counted from the recorded factor trials"
    if factor_rows == [] and rounds is None:
        factor_rows = None  # nothing at all was recorded for this run
    derived: dict[str, RecordedFact] = {}
    refused = None
    if rounds is not None:
        refused = sum(1 for row in rounds if row.get("status") in REFUSED_STATUSES)
        derived["refused_closed_family"] = counted(
            refused, "counted from the proposals refused in rounds.jsonl"
        )
    if factor_rows is not None:
        own = [row for row in factor_rows if row.get("status") != "IMPORTED"]
        clocks = [
            clock
            for row in own
            for clock in _object(row.get("clocks") or {"daily": row}).values()
            if isinstance(clock, dict)
        ]
        derived["code_ran"] = counted(
            sum(1 for row in own if row.get("status") != "FAILED"), basis_rows
        )
        derived["passed_rank_screen"] = counted(
            sum(1 for row in own if _any_clock(row, SCREENED)), basis_rows
        )
        replayed = [c for c in clocks if c.get("status") in SPREAD_CHECKED]
        if all(_get(c, "spread.status") in ("PASS", "FAIL") for c in replayed):
            derived["passed_spread_check"] = counted(
                sum(1 for row in own if _any_clock(row, SPREAD_CHECKED)), basis_rows
            )
        else:
            derived["passed_spread_check"] = RecordedFact(
                value=None, reason="this run's trials were recorded before the spread check"
            )
        derived["passed_deflation"] = counted(
            sum(1 for row in own if _passed_deflation(row)), basis_rows
        )
        if refused is not None:
            derived["proposed"] = counted(
                len(own) + refused,
                "recorded factor trials plus proposals refused before coding;"
                " one proposal can hold several factors",
            )
    for key, value in derived.items():
        if result[key].value is None:
            result[key] = value
    return result


def _any_clock(row: dict[str, Any], statuses: frozenset[str]) -> bool:
    clocks = _object(row.get("clocks") or {"daily": row})
    return any(isinstance(c, dict) and c.get("status") in statuses for c in clocks.values())


def _passed_deflation(row: dict[str, Any]) -> bool:
    clocks = _object(row.get("clocks") or {"daily": row})
    return any(
        isinstance(c, dict) and _get(c, "replay.deflated_sharpe.passed") is True
        for c in clocks.values()
    )


def _ledger(ledger: Path) -> tuple[list[dict[str, Any]], str | None]:
    rows, reason = _lines(ledger.parent.parent, f"{ledger.parent.name}/{ledger.name}")
    return rows, "The factor trial ledger is absent." if not ledger.exists() else reason


def list_runs(root: Path, ledger: Path) -> RdAgentRunList:
    ledger_rows, ledger_reason = _ledger(ledger)
    has_ledger = ledger.exists()
    items = []
    for folder, receipt in _runs(root):
        rounds, _ = _lines(folder, "rounds.jsonl")
        has_rounds = (folder / "rounds.jsonl").exists()
        counts = _funnel(
            receipt,
            _ledger_factor_rows(ledger_rows, receipt["run_id"], folder) if has_ledger else None,
            rounds if has_rounds else None,
        )
        items.append(_summary(folder, receipt, _json(folder, "panel/panel-receipt.json"), counts))
    return RdAgentRunList(
        items=items,
        reason=None if items else "No recorded RD-Agent factor runs were found.",
        ledger_reason=ledger_reason if not has_ledger else None,
    )


def _clock(row: dict[str, Any]) -> RdAgentClock:
    return RdAgentClock(
        figures=project(row, ("status", "p", "q")),
        screen=project(_object(row.get("screen") or {}), SCREEN),
        spread=project(_object(row.get("spread") or {}), SPREAD),
        replay=project(_object(row.get("replay") or {}), REPLAY),
        deflation=project(_get(row, "replay.deflated_sharpe") or {}, DEFLATION),
        family_deflation=project(
            _get(row, "replay.deflated_sharpe_family") or {},
            ("n_trials", "benchmark_sharpe", "psr", "reason"),
        ),
    )


def _factor(row: dict[str, Any]) -> RdAgentFactor:
    status = row.get("status")
    if not isinstance(status, str):
        raise ValueError("Missing recorded factor status.")
    clocks = _object(row.get("clocks") or {"daily": row})
    if set(clocks) - {"daily", "weekly", "monthly"}:
        raise ValueError("Unknown recorded holding clock.")
    return RdAgentFactor(
        name=fact(row.get("name")),
        description=fact(row.get("description")),
        idea_families=fact(row.get("idea_families")),
        status=status,
        sentence=status_sentence(status, row.get("failure_reason")),
        failure_reason=fact(row.get("failure_reason")),
        figures=project(
            row, ("plain_name", "lead_clock", "family_size", "total_trials", "trial_index")
        ),
        clocks={key: _clock(_object(value)) for key, value in clocks.items()},
    )


def _caps(receipt: dict[str, Any]) -> dict[str, RdAgentCap]:
    stamp = receipt.get("ended_at") or receipt.get("started_at")
    month = datetime.fromisoformat(stamp).strftime("%Y-%m") if stamp else None
    values = {
        "calls": (
            receipt.get("counted_calls", _get(receipt, "gateway_status.this_run.calls")),
            _get(receipt, "gateway_status.caps.run_max_calls") or receipt.get("run_max_calls"),
        ),
        "run_usd": (
            _get(receipt, "gateway_status.this_run.usd"),
            _get(receipt, "gateway_status.caps.run_max_usd"),
        ),
        "month_usd": (
            _get(receipt, f"gateway_status.months.{month}.usd") if month else None,
            _get(receipt, "gateway_status.caps.month_max_usd"),
        ),
        "month_calls": (
            _get(receipt, f"gateway_status.months.{month}.calls") if month else None,
            _get(receipt, "gateway_status.caps.month_max_calls"),
        ),
    }
    return {
        name: RdAgentCap(used=fact(used), limit=fact(limit))
        for name, (used, limit) in values.items()
    }


def _identity(panel: dict[str, Any], key: str) -> list[dict[str, RecordedFact]]:
    rows = panel.get(key, [])
    if not isinstance(rows, list):
        raise ValueError("Invalid recorded identity corrections.")
    return [
        project(_object(row), ("instrument", "new_from", "reason", "new_name", "ratio"))
        for row in rows
    ]


def _stamp(value: Any) -> datetime:
    stamp = datetime.fromisoformat(value)
    if stamp.tzinfo is None:
        raise ValueError("RD-Agent timestamps must include a timezone.")
    return stamp


def _timing(steps: list[dict[str, Any]]) -> list[dict[str, RecordedFact]]:
    """One row per recorded step; minutes are the difference of its two recorded timestamps."""
    starts: dict[tuple[Any, Any, Any], dict[str, Any]] = {}
    ends: dict[tuple[Any, Any, Any], dict[str, Any]] = {}
    for row in steps:
        key = (row.get("loop"), row.get("step_index"), row.get("step"))
        if row.get("event") == "start":
            starts[key] = row
        elif row.get("event") == "end":
            ends[key] = row
    rows: list[dict[str, RecordedFact]] = []
    for key, start in starts.items():
        end = ends.get(key)
        minutes = (
            RecordedFact(value=None, reason="this step has no recorded end")
            if end is None
            else counted(
                round((_stamp(end["ts"]) - _stamp(start["ts"])).total_seconds() / 60, 2),
                "end time minus start time, both recorded",
            )
        )
        rows.append(
            {
                "loop": fact(key[0]),
                "step": fact(key[2]),
                "started_at": fact(start.get("ts")),
                "ended_at": fact(None if end is None else end.get("ts")),
                "minutes": minutes,
                "status": fact(None if end is None else end.get("status")),
            }
        )
    return rows


def read_run(root: Path, ledger: Path, run_id: str) -> RdAgentDetail:
    selected = next((item for item in _runs(root) if item[1]["run_id"] == run_id), None)
    if selected is None:
        raise FileNotFoundError("The requested RD-Agent run is not in the recorded run list.")
    folder, receipt = selected
    panel = _json(folder, "panel/panel-receipt.json")
    ledger_rows, ledger_reason = _ledger(ledger)
    factor_rows = _ledger_factor_rows(ledger_rows, run_id, folder)
    factors = [_factor(row) for row in factor_rows]
    unknown = [
        row
        for row in ledger_rows
        if row.get("run_id") == run_id
        and row.get("schema") not in FACTOR_SCHEMAS | {"AlphaRuleTrialV1"}
    ]
    if unknown:
        raise ValueError("This run has an unrecognised trial ledger schema.")
    rounds, refusal_reason = _lines(folder, "rounds.jsonl")
    funnel = _funnel(
        receipt,
        factor_rows if ledger.exists() else None,
        rounds if (folder / "rounds.jsonl").exists() else None,
    )
    steps, timing_reason = _lines(folder, "steps.jsonl")
    evaluations, evaluation_reason = _lines(folder, "evaluations.jsonl")
    usage = _get(receipt, "call_split.chat_usage") or {}
    providers = _object(usage.get("provider_calls") or {})
    months = _get(receipt, "gateway_status.months") or {}
    if any(not re.fullmatch(r"\d{4}-\d{2}", month) for month in months):
        raise ValueError("Invalid recorded gateway month.")
    notes = [
        str(value)
        for value in (
            receipt.get("call_cap_note"),
            receipt.get("memory_warning"),
            usage.get("summary"),
            panel.get("universe_text"),
            *[row.get("feedback_text") for row in evaluations],
        )
        if value
    ]
    if evaluation_reason and evaluation_reason != MISSING:
        notes.append(evaluation_reason)
    return RdAgentDetail(
        run=_summary(folder, receipt, panel, funnel),
        funnel=funnel,
        factors=factors,
        factor_reason=ledger_reason,
        refusals=[
            {
                **project(
                    row, ("status", "closed_families", "open_families", "attempt", "trial_created")
                ),
                "sentence": fact(status_sentence(row["status"], None)),
            }
            for row in rounds
            if row.get("status")
            in {"refused_closed_family", "no_admissible_idea", "abandoned_at_cap"}
        ],
        refusal_reason=refusal_reason,
        timing=_timing(steps),
        timing_reason=timing_reason,
        caps=_caps(receipt),
        months={
            month: project(_object(value), ("calls", "usd")) for month, value in months.items()
        },
        cache=project(usage, CACHE),
        providers={_text(name): fact(value) for name, value in providers.items()},
        universe=project(
            {
                **panel,
                "instruments": list(panel["instruments"])
                if isinstance(panel.get("instruments"), dict)
                else panel.get("instruments"),
            },
            UNIVERSE,
        )
        | {"instrument_count": _universe_size(panel)},
        identity_splits=_identity(panel, "identity_breaks"),
        identity_rescales=_identity(panel, "identity_rescales"),
        notes=[_text(note) for note in notes],
    )
