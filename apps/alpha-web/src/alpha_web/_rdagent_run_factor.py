"""Project one recorded factor trial and its clocks for display."""

from __future__ import annotations

import json
from typing import Any

from alpha_web._rdagent_run_files import _get, _object, fact, project
from alpha_web._rdagent_run_words import DEFLATION, REPLAY, SCREEN, SPREAD, status_sentence
from alpha_web.api.rdagent_models import RdAgentClock, RdAgentFactor


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
