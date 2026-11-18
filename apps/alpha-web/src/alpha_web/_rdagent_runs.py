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
    RdAgentIdea,
    RdAgentRun,
    RdAgentRunList,
    RdAgentStory,
    RecordedFact,
)

MISSING = "not recorded by this run"
RECEIPT_SCHEMA = "AlphaRdagentFactorRunReceiptV1"
FACTOR_SCHEMAS = {f"AlphaRdagentFactorTrialV{version}" for version in (1, 2, 3)}
MAX_FILE_BYTES = 32 * 1024 * 1024
STATUS_SENTENCES = {
    "DIAGNOSTIC": (
        "Diagnostic only: cannot pass. Choosing the sign or clock after "
        "seeing this is a new trial and will be counted."
    ),
    "refused_missing_declaration": (
        "The proposal lacked a declared direction, primary clock or "
        "economic reason and was refused before coding."
    ),
    "proposal_failed_provider_timeout": (
        "The proposal provider timed out; no trial was invented and the "
        "loop moved to the next round."
    ),
    "proposal_failed_provider_error": (
        "The proposal provider failed; no trial was invented and the loop moved to the next round."
    ),
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
        "The declared primary clock and sign passed screening, spread, "
        "replay and deflation; this is a lead for one owner-approved "
        "reserved-data confirmation check, never evidence by itself."
    ),
    "DEFLATION_FAIL": (
        "A weekly or monthly clock passed screening, the spread check and replay, but not the"
        " multiple-testing (deflated Sharpe) test."
    ),
    "FAST_ONLY": "Only the daily clock passed; this is not a swing candidate.",
    "REPEAT": "This code was already evaluated and supplies no new evidence.",
    "IMPORTED": "This is a recorded historical trial, not a new evaluation by this run.",
    "refused_closed_family": (
        "The idea family was already closed, so the proposal was refused before coding."
    ),
    "no_admissible_idea": "Repeated closed-family proposals ended this round before coding.",
    "abandoned_at_cap": "The cap stopped an unfinished round; no trial was created for it.",
    "abandoned_after_error": "An error stopped an unfinished round; no trial was created for it.",
    "coding_failed_provider_timeout": (
        "The model provider did not reply in time after the allowed attempts, so this round"
        " stopped; no trial was invented and the next round ran."
    ),
    "coding_failed_provider_error": (
        "The model provider failed after the allowed attempts, so this round stopped; no trial"
        " was invented and the next round ran."
    ),
    "coding_failed_internal_error": (
        "An internal coding error ended this round; completed factors still went to ALPHA's "
        "judge. Two consecutive rounds with this error stop the run."
    ),
    "critic_unavailable_provider_timeout": (
        "The code critic timed out; execution and value checks supplied feedback, "
        "and later code critics in this round were skipped. ALPHA's judging rules stayed the same."
    ),
    "critic_unavailable_provider_error": (
        "The code critic's provider failed; execution and value checks supplied feedback, "
        "and later code critics in this round were skipped. ALPHA's judging rules stayed the same."
    ),
}
REFUSED_STATUSES = frozenset({"refused_closed_family", "no_admissible_idea"})
SCREENED = frozenset({"SPREAD_FAIL", "REPLAY_FAIL", "PASS"})
SPREAD_CHECKED = frozenset({"REPLAY_FAIL", "PASS"})
FUNNEL = (
    "proposed",
    "refused_closed_family",
    "stopped_by_provider",
    "code_ran",
    "passed_rank_screen",
    "passed_spread_check",
    "shortlisted",
    "passed_deflation",
)
SCREEN = (
    "status",
    "mean_ic",
    "n",
    "effective_n",
    "plain_p",
    "clustered_p",
    "two_sided_p",
    "dependence_rule",
    "newey_west.effective_n",
    "newey_west.lag",
    "newey_west.long_run_variance",
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
DEFLATION = (
    "sharpe",
    "psr",
    "dsr",
    "expected_max_sharpe",
    "n_trials",
    "threshold",
    "passed",
    "deflation_n",
    "deflation_variance",
    "deflation_variance_term",
    "deflation_rule",
)
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


def counted(value: int | float, basis: str) -> RecordedFact:
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
    stopped = 0
    if rounds is not None:
        refused = sum(1 for row in rounds if row.get("status") in REFUSED_STATUSES)
        derived["refused_closed_family"] = counted(
            refused, "counted from the proposals refused in rounds.jsonl"
        )
        stopped = sum(
            len(row.get("factor_names", []))
            for row in rounds
            if str(row.get("status", "")).startswith(
                ("coding_failed_provider_", "proposal_failed_provider_")
            )
            and not row.get("trial_created")
        )
        derived["stopped_by_provider"] = counted(
            stopped, "factors stopped by the model provider, counted from rounds.jsonl"
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
        derived["shortlisted"] = (
            counted(sum(row["shortlist"] is True for row in own), basis_rows)
            if all(type(row.get("shortlist")) is bool for row in own)
            else RecordedFact(value=None, reason="shortlist not recorded for every factor trial")
        )
        if refused is not None:
            derived["proposed"] = counted(
                len(own) + refused + stopped,
                "recorded factor trials, proposals refused before coding (one proposal can"
                " hold several factors) and factors stopped by the model provider",
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
        figures=project(
            row,
            (
                "status",
                "p",
                "q",
                "bh_q_diagnostic",
                "screen_cutoff",
                "screen_m",
                "screen_confirmed",
            ),
        ),
        screen=project(_object(row.get("screen") or {}), SCREEN),
        spread=project(_object(row.get("spread") or {}), SPREAD),
        replay=project(_object(row.get("replay") or {}), REPLAY),
        deflation=project(_get(row, "replay.deflated_sharpe") or {}, DEFLATION),
        family_deflation=project(
            _get(row, "replay.deflated_sharpe_family") or {},
            ("n_trials", "benchmark_sharpe", "psr", "reason"),
        ),
    )


def _derived_status(row: dict[str, Any]) -> str:
    # Mirror the ledger read model: importing it crosses the web's transitive package boundary.
    # test_web_and_ledger_derive_same_old_status pins this to the actual V3 shape.
    trial = row.get("clocks", {}).get(row.get("lead_clock", "daily"), row)
    result = trial.get("replay", {}).get("deflated_sharpe", {})
    if (
        row["status"] == "CANDIDATE"
        and result.get("dsr") is not None
        and result.get("threshold") is not None
        and not result["dsr"] >= result["threshold"]
    ):
        return "DEFLATION_FAIL"
    return str(row["status"])


def _honesty_sentence(row: dict[str, Any]) -> str:
    trial = row.get("clocks", {}).get(row.get("lead_clock", "daily"), row)
    result = trial.get("replay", {}).get("deflated_sharpe", {})
    parts = []
    if row.get("shortlist") is True:
        parts.append(
            "Shortlisted: passed the declared primary screen, spread check and replay. "
            "Shortlisted is not a pass, not a candidate, and not evidence of profit."
        )
    if row.get("composite_suspect") is True:
        parts.append("This factor looks like a blend of earlier tries; diagnostic only.")
    if result and result.get("deflation_rule") != "family-looks-x2-floor-1":
        parts.append("Stored deflated Sharpe: old rule (fewer looks counted).")
    if row.get("screen_rule"):
        parts.append(
            "The screen cutoff counts primary-clock looks and earlier "
            "confirmed candidates; BH q is diagnostic only. Plain and "
            "clustered p-values describe uncertainty; Newey-West estimates "
            "effective observations. Deflation counts twice every look and "
            "uses the larger of sample variance and the sampling floor. The "
            "declared direction, primary clock and economic reason were "
            "supplied before evaluation. Twin correlation identifies mirrors "
            "on the same panel; unavailable comparisons are counted."
        )
    if row.get("diagnostics"):
        parts.append(
            "Diagnostic only: cannot pass. Choosing the sign or clock after "
            "seeing this is a new trial and will be counted."
        )
    if row.get("chance_pass_message"):
        parts.append(str(row["chance_pass_message"]))
    return " ".join(parts)


def _factor(row: dict[str, Any]) -> RdAgentFactor:
    status = row.get("status")
    if not isinstance(status, str):
        raise ValueError("Missing recorded factor status.")
    clocks = _object(row.get("clocks") or {"daily": row})
    if set(clocks) - {"daily", "weekly", "monthly"}:
        raise ValueError("Unknown recorded holding clock.")
    status = _derived_status(row)
    sentence = status_sentence(status, row.get("failure_reason"))
    if status != row["status"]:
        sentence += " derived from recorded CANDIDATE; stored figures are unchanged."
    sentence += " " + _honesty_sentence(row)
    display = {
        **row,
        "diagnostics": list(row["diagnostics"])
        if isinstance(row.get("diagnostics"), dict)
        else row.get("diagnostics"),
        "twin": json.dumps(row["twin"], allow_nan=False)
        if isinstance(row.get("twin"), dict)
        else row.get("twin"),
    }
    return RdAgentFactor(
        name=fact(row.get("name")),
        description=fact(row.get("description")),
        idea_families=fact(row.get("idea_families")),
        status=status,
        sentence=sentence.strip(),
        failure_reason=fact(row.get("failure_reason")),
        figures=project(
            display,
            (
                "plain_name",
                "lead_clock",
                "family_size",
                "total_trials",
                "trial_index",
                "declared_direction",
                "primary_clock",
                "direction_reason",
                "screen_rule",
                "screen_cutoff",
                "screen_m",
                "screen_confirmed",
                "diagnostics",
                "twin",
                "twin_check",
                "shortlist",
                "lineage_r2",
                "lineage_regressors",
                "lineage_convention",
                "lineage_reason",
                "composite_suspect",
                "evaluable_factors",
                "chance_pass_message",
                "expected_chance_passes",
                "chance_pass_rate",
                "chance_pass_rate_date",
            ),
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


STORY_STAGES = ("proposed", "refused", "coded", "ran", "judged", "shortlisted", "candidate")
STORY_REFUSALS = REFUSED_STATUSES | {"refused_missing_declaration"}
STORY_FIELDS = (
    "schema",
    "iteration",
    "loop",
    "attempt",
    "name",
    "description",
    "code_sha256",
    "status",
    "reason",
    "message",
    "trial_created",
    "factor_names",
    "refused_families",
    "all_closed_families",
    "closed_families",
    "declared_direction",
    "primary_clock",
    "direction_reason",
    "failure_reason",
    "failure_detail",
    "shortlist",
    "composite_suspect",
    "eligibility",
    "idea_families",
    "trial_index",
    "stage",
)


def _story_key(row: dict[str, Any]) -> tuple[int, str, str] | None:
    iteration, name, digest = (row.get(key) for key in ("iteration", "name", "code_sha256"))
    if iteration is None or name is None or digest is None:
        return None
    if type(iteration) is not int or not isinstance(name, str) or not isinstance(digest, str):
        raise ValueError("Invalid recorded idea identity.")
    if not re.fullmatch(r"[a-f0-9]{64}", digest):
        raise ValueError("Invalid recorded idea code hash.")
    return iteration, name, digest


def _story_raw(row: dict[str, Any]) -> str:
    # Keep the existing closed projection: never return environments, prompts or paths.
    return json.dumps(
        {key: fact(row[key]).value for key in STORY_FIELDS if key in row},
        ensure_ascii=False,
        indent=2,
    )


BEFORE_SHORTLIST = frozenset(
    {"SCREEN_FAIL", "SPREAD_FAIL", "REPLAY_FAIL", "FAILED", "LOOKAHEAD", "UNSTABLE", "DEGENERATE"}
)


def _shortlisted(row: dict[str, Any]) -> bool | None:
    """The stored flag; else False only for a status the writer gives before the shortlist step."""
    if type(row.get("shortlist")) is bool:
        return bool(row["shortlist"])
    return False if row.get("status") in BEFORE_SHORTLIST else None


def _idea(
    identity: str,
    row: dict[str, Any],
    trial: dict[str, Any] | None = None,
    round_row: dict[str, Any] | None = None,
) -> RdAgentIdea:
    source = trial or row
    status = row.get("status") if trial is None else None
    if status:
        status_sentence(status, None)  # unknown stored states fail loud
    refused = status in STORY_REFUSALS
    stopped = (
        trial is None
        and row.get("trial_created") is False
        and row.get("coding_status") is None
        and str(status).startswith(("coding_failed_provider_", "proposal_failed_provider_"))
    )
    open_end = not (refused or stopped)  # only these stored states prove nothing was coded
    factor = _factor(trial) if trial is not None else None
    evaluated = factor is not None and factor.status not in {"IMPORTED", "REPEAT", "FAILED"}
    ran = evaluated or source.get("failure_reason") == "critic_rejected"
    feedback = _object((round_row or {}).get("feedback") or {})
    words = [
        feedback[key]
        for key in ("observations", "hypothesis_evaluation", "new_hypothesis", "reason")
        if feedback.get(key)
    ]
    if any(not isinstance(word, str) for word in words):
        raise ValueError("Invalid recorded feedback text.")
    labels = []
    for key in ("shortlist", "composite_suspect"):
        if source.get(key) is True:
            labels.append(key)
    if source.get("eligibility"):
        labels.append(str(source["eligibility"]))
    if source.get("label"):
        labels.append(str(source["label"]))
    if source.get("diagnostics"):
        labels.append("diagnostic clocks")
    if factor is not None:
        statuses = ["coded"] if ran else [source.get("failure_reason") or factor.status]
    else:
        statuses = [status] if status else []
    stages: dict[str, bool | None] = {
        "proposed": True,
        "refused": refused,
        "coded": True if ran or row.get("coding_status") == "coded" else None if open_end else False,
        "ran": True if ran else None if open_end else False,
        "judged": evaluated
        if trial is not None
        else False
        if refused or row.get("trial_created") is False
        else None,
        "shortlisted": _shortlisted(source) if trial is not None else False if refused else None,
        "candidate": factor.status == "CANDIDATE" if factor else False if refused else None,
    }
    return RdAgentIdea(
        id=identity,
        round=fact(source.get("iteration", source.get("loop"))),
        round_kind="evaluation" if trial is not None or round_row is not None else "loop",
        name=fact(row.get("name", source.get("name"))),
        description=fact(row.get("description", source.get("description"))),
        direction=fact(source.get("declared_direction")),
        clock=fact(source.get("primary_clock")),
        reason=fact(source.get("direction_reason")),
        system_statuses=statuses,
        refusal=fact(row.get("message") if refused else None),
        feedback=fact(" ".join(words) if words else None),
        feedback_scope="round" if words else "unknown",
        trial=factor,
        stages=stages,
        labels=labels,
        code_file=fact(None),
        raw=_story_raw(source),
    )


def _story_trials(
    ledger_rows: list[dict[str, Any]],
    evaluations: list[dict[str, Any]],
    run_ids: set[str],
) -> list[dict[str, Any]]:
    rows = list(ledger_rows)
    seen = {_story_key(row): row for row in rows if _story_key(row) is not None}
    if len(seen) != sum(_story_key(row) is not None for row in rows):
        raise ValueError("Duplicate recorded idea identity.")
    for evaluation in evaluations:
        for value in evaluation.get("factors", []):
            row = _object(value)
            if row.get("run_id") is not None and row["run_id"] not in run_ids:
                raise ValueError("Recorded evaluation belongs to a different run.")
            row = {"iteration": evaluation.get("iteration"), **row}
            key = _story_key(row)
            if key is None:
                rows.append(row)  # Keep it separate; its missing link must remain unknown.
                continue
            if row.get("iteration") != evaluation.get("iteration"):
                raise ValueError("Recorded evaluation and trial identifiers disagree.")
            previous = seen.get(key)
            if previous is not None:
                if previous != row:
                    raise ValueError("Recorded evaluation and ledger trial disagree.")
            else:
                rows.append(row)
                seen[key] = row
    return rows


def _story_tasks(
    rounds: list[dict[str, Any]],
) -> dict[tuple[int, str, str], tuple[dict[str, Any], dict[str, Any]]]:
    tasks = {}
    for record in rounds:
        for value in record.get("tasks", []):
            task = _object(value)
            key = _story_key({**task, "iteration": record.get("iteration")})
            if key is not None:
                if key in tasks:
                    raise ValueError("Duplicate recorded round task identity.")
                tasks[key] = (task, record)
    return tasks


def _story_ending(receipt: dict[str, Any]) -> str:
    reason = str(receipt.get("loop_reason", "")).lower()
    if any(
        word in reason
        for word in ("budget_exhausted", "budget exhausted", "cap", "wall-clock limit")
    ):
        return "budget"
    if "internal coding error" in reason:
        return "internal_error"
    if receipt.get("exit_status") == 0:
        return "finished"
    if any(word in reason for word in ("provider_timeout", "provider_error", "provider timeout")):
        return "provider"
    return "error" if receipt.get("exit_status") is not None else "not_recorded"


def _story(
    folder: Path,
    receipt: dict[str, Any],
    ledger_rows: list[dict[str, Any]],
    rounds: list[dict[str, Any]],
    evaluations: list[dict[str, Any]],
) -> RdAgentStory:
    tasks = _story_tasks(rounds)
    ideas = []
    missing = []
    events = []
    uncertain = bool(ledger_rows) and any(
        _story_key(row) is None
        for evaluation in evaluations
        for row in evaluation.get("factors", [])
    )
    if uncertain:
        missing.append(
            "An evaluation has no stored identity linking it to the ledger; counts are unknown."
        )
    for index, trial in enumerate(
        _story_trials(ledger_rows, evaluations, {receipt["run_id"], folder.name})
    ):
        if trial.get("status") == "IMPORTED":
            continue
        key = _story_key(trial)
        task, record = tasks.pop(key, ({}, {})) if key else ({}, {})
        idea = _idea(f"trial-{index}", task, trial, record)
        digest = trial.get("code_sha256")
        if key and _read(folder, f"code/{digest}.py") is not None:
            idea.code_file = fact(f"{digest}.py")
            idea.stages["coded"] = True
        if idea.round.value is None:
            idea.round_kind = "unknown"
        if not record:
            missing.append("The trial's link to recorded proposer feedback is not recorded.")
        ideas.append(idea)
    for key, (task, record) in tasks.items():
        ideas.append(_idea(f"task-{len(ideas)}", {**task, "iteration": key[0]}, round_row=record))
        uncertain = True
        missing.append("A task's link to its trial is not recorded.")
    for index, record in enumerate(rounds):
        if record.get("tasks") is not None:
            for position, task in enumerate(record["tasks"]):
                entry = {**_object(task), "iteration": record.get("iteration")}
                if _story_key(entry) is None:
                    ideas.append(
                        _idea(f"unlinked-task-{index}-{position}", entry, round_row=record)
                    )
                    uncertain = True
                    missing.append("A task has no stored identifier linking it to a trial.")
            continue
        if record.get("status"):
            status_sentence(record["status"], None)
            events.append(record["status"])
        names = record.get("factor_names", [])
        if not isinstance(names, list) or any(not isinstance(name, str) for name in names):
            raise ValueError("Invalid recorded proposal names.")
        if not names and record.get("trial_created") is False and record.get("status"):
            missing.append(
                "A round ended before any idea of it was recorded; ideas it may have "
                "proposed are not counted."
            )
        elif not names:
            missing.append("An event has no recorded idea names; its idea count is not recorded.")
            uncertain = True
        if record.get("trial_created") is not False and names:
            uncertain = True
            missing.append(
                "Loop event to evaluation/trial link is not recorded; "
                "these cards may describe the same idea."
            )
        per_factor = {row["name"]: row for row in record.get("factors", [])}
        for position, name in enumerate(names):
            entry = {**record, "name": name}
            if name in per_factor:
                entry["trial_created"] = per_factor[name].get("trial_created")
                entry["coding_status"] = per_factor[name].get("status")
            ideas.append(_idea(f"event-{index}-{position}", entry))
    if rounds:
        missing.append(
            "Evaluation numbers and loop round numbers have no stored link "
            "and are grouped separately."
        )
    present = bool(ideas or rounds or evaluations)
    no_trials = (
        bool(rounds)
        and not evaluations
        and not any(idea.trial is not None for idea in ideas)
        and all(row.get("trial_created") is False for row in rounds)
    )
    journey = {}
    for stage in STORY_STAGES:
        known = present and not uncertain and all(idea.stages[stage] is not None for idea in ideas)
        known = known or no_trials and stage in {"judged", "shortlisted", "candidate"}
        journey[stage] = (
            counted(
                sum(idea.stages[stage] is True for idea in ideas), "counted from linked idea cards"
            )
            if known
            else fact(None)
        )
    start, end = receipt.get("started_at"), receipt.get("ended_at")
    minutes = (
        counted((_stamp(end) - _stamp(start)).total_seconds() / 60, "recorded end minus start")
        if start and end
        else fact(None)
    )
    if isinstance(minutes.value, (int, float)) and minutes.value < 0:
        raise ValueError("Recorded run ends before it starts.")
    return RdAgentStory(
        events=list(dict.fromkeys(events)),
        ideas=ideas,
        journey=journey,
        missing_links=list(dict.fromkeys(missing)),
        ending=_story_ending(receipt),
        ending_reason=fact(receipt.get("loop_reason")),
        minutes=minutes,
    )


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
    story = _story(folder, receipt, factor_rows, rounds, evaluations)
    for issue in (refusal_reason, evaluation_reason):
        if issue and issue != MISSING:
            story.missing_links.append(issue)
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
        story=story,
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
            in {
                "refused_closed_family",
                "no_admissible_idea",
                "abandoned_at_cap",
                "abandoned_after_error",
                "coding_failed_provider_timeout",
                "coding_failed_provider_error",
                "coding_failed_internal_error",
                "proposal_failed_provider_timeout",
                "proposal_failed_provider_error",
                "critic_unavailable_provider_timeout",
                "critic_unavailable_provider_error",
            }
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
