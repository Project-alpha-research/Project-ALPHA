"""Replay of screened factor clocks and the RD-Agent evaluation disclosures."""

from __future__ import annotations

from datetime import date
from typing import Any

import numpy as np
import polars as pl

from alpha_cli import _rdagent_membership as membership
from alpha_cli._rdagent_clocks import overall_status, trial_clocks
from alpha_cli._rdagent_judge import Q_THRESHOLD
from alpha_cli._rdagent_judge_replay import replay
from alpha_cli._rdagent_stats import chance_fields, screen_cutoff
from alpha_core import DataError
from alpha_validation.proportion import benjamini_hochberg


def _replay_clocks(
    rows: list[dict[str, Any]],
    panel: pl.DataFrame,
    signals: dict[str, np.ndarray],
    days: list[date],
    series: dict[str, dict[str, Any]],
    family: dict[tuple[str, str], dict[str, Any]],
    total_rows: int,
    gap_policy: bool = False,
    identity_segments: frozenset[str] = frozenset(),
    confirmed: int = 0,
) -> tuple[dict[tuple[str, str], np.ndarray], dict[str, dict[str, float]]]:
    q = benjamini_hochberg([trial["p"] for trial in family.values()], alpha=Q_THRESHOLD).qvalues
    qvalues: dict[str, dict[str, float]] = {}
    for (digest, clock), value in zip(family, q, strict=True):
        if clock != "unknown":
            qvalues.setdefault(digest, {})[clock] = float(value)
    replay_returns = {}
    replay_options: dict[str, Any] = {"gap_policy": True} if gap_policy else {}
    if identity_segments:
        replay_options["identity_segments"] = identity_segments
    for row in rows:
        digest = row.get("repeat_code_sha256", row["code_sha256"])
        row.update(
            screen_cutoff=screen_cutoff(len(family), confirmed),
            screen_m=len(family),
            screen_confirmed=confirmed,
        )
        row.update(family_size=len(family), distinct_factors=len(qvalues), total_trials=total_rows)
        for clock, trial in row["clocks"].items():
            trial["q"] = qvalues.get(digest, {}).get(clock, 1.0)
            trial["bh_q_diagnostic"] = trial["q"]
            trial.update({k: row[k] for k in ("screen_cutoff", "screen_m", "screen_confirmed")})
            if row["status"] != "OK" or trial["status"] != "OK":
                continue
            trial["status"] = "SCREEN_FAIL"
            if clock == row["primary_clock"] and trial["p"] <= row["screen_cutoff"] / 2:
                # ADR-0055: a screened clock must first show its top third beating its bottom
                # third; only then is it replayed. A stricter, cheaper failure, never a pass.
                checked = trial.get("spread", {"status": "ERROR", "error": "spread not computed"})
                # A clock whose spread failed or could not be computed is still replayed, only so
                # the Deflated Sharpe counts it as a trial exactly as before ADR-0055; that replay
                # can never turn it into a pass.
                verdict = {"PASS": None, "ERROR": "ERROR"}.get(checked["status"], "SPREAD_FAIL")
                row["stage"] = "replay"
                try:
                    metrics, net = replay(
                        panel,
                        signals[digest],
                        days,
                        trial["screen"]["direction"],
                        clock=clock,
                        series=series[digest][clock],
                        **replay_options,
                    )
                except (DataError, ValueError, ZeroDivisionError, FloatingPointError) as error:
                    trial.update(
                        status="ERROR", replay={"error": f"{type(error).__name__}: {error}"}
                    )
                    continue
                if verdict is not None:
                    metrics["counted_only"] = (
                        f"spread check {checked['status']}; replayed only to count the trial, "
                        "not a result"
                    )
                    status = verdict
                else:
                    status = "PASS" if metrics["net"]["annualized_return"] > 0 else "REPLAY_FAIL"
                trial.update(replay=metrics, status=status)
                replay_returns[(digest, clock)] = net
        if row["status"] == "OK":
            row["status"], row["lead_clock"] = overall_status(
                row["clocks"], row.get("primary_clock")
            )
        row.update({k: row["clocks"][row["lead_clock"]][k] for k in ("p", "q", "screen", "replay")})
    return replay_returns, qvalues


def _gap_disclosure(panel: pl.DataFrame, rows: list[dict[str, Any]]) -> tuple[dict[str, Any], str]:
    summary = membership.panel_summary(panel)
    replays = [
        t["replay"] for row in rows if row["status"] != "REPEAT" for t in row["clocks"].values()
    ]
    spreads = [
        t.get("spread", {})
        for row in rows
        if row["status"] != "REPEAT"
        for t in row["clocks"].values()
    ]
    summary["spread_haircuts_applied"] = sum(s.get("haircuts_applied", 0) for s in spreads)
    count = sum(r.get("haircuts_applied", 0) for r in replays)
    summary["haircuts_applied"] = count
    summary["written_off_at_panel_end"] = sum(r.get("written_off_at_panel_end", 0) for r in replays)
    note = (
        f" {summary['instruments_ended_early']} instruments ended early; "
        f"{summary['missing_instrument_days']} instrument-days were missing inside their spans; "
        f"{count} position haircuts across the new factor/clock replays "
        f"({summary['written_off_at_panel_end']} at panel end); "
        f"{summary['spread_haircuts_applied']} spread-leg haircuts. "
        + str(membership.POLICY["assumption"])
        + " "
    )
    return summary, note


def _chance_disclosure(rows: list[dict[str, Any]], history: list[dict[str, Any]]) -> None:
    evaluable = len(
        {
            r["code_sha256"]
            for r in [*history, *rows]
            if r["status"] != "REPEAT"
            and any(t.get("screen", {}).get("status") == "OK" for t in trial_clocks(r).values())
        }
    )
    for row in rows:
        row.update(chance_fields(evaluable))
