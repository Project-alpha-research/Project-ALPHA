"""Exploratory RD-Agent factor screen and ALPHA replay; no admission authority."""

from __future__ import annotations

import argparse
import fcntl
import io
import json
import os
import re
import sys
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import numpy as np
import polars as pl

from alpha_cli import _rdagent_identity as identity
from alpha_cli import _rdagent_membership as membership
from alpha_cli import _rdagent_universe as universes
from alpha_cli._factor_eval_replay import _chance_disclosure, _gap_disclosure, _replay_clocks
from alpha_cli._factor_eval_screen import _eligibility, _keep_first_costs, _screen_factors
from alpha_cli._factor_eval_series import _record_series
from alpha_cli._rdagent_checks import post_judge_checks
from alpha_cli._rdagent_clocks import (
    CLOCKS as CLOCKS,
)
from alpha_cli._rdagent_clocks import (
    clock_feedback,
    overall_status,
    trial_clocks,
)
from alpha_cli._rdagent_costs import costs_text, judge_costs, other_cost_note, other_cost_rows
from alpha_cli._rdagent_judge import (
    ANNUAL_DAYS as ANNUAL_DAYS,
)
from alpha_cli._rdagent_judge import (
    AUTHORITY as AUTHORITY,
)
from alpha_cli._rdagent_judge import (
    CONFIG as CONFIG,
)
from alpha_cli._rdagent_judge import (
    EXPLORATION as EXPLORATION,
)
from alpha_cli._rdagent_judge import (
    LABEL as LABEL,
)
from alpha_cli._rdagent_judge import (
    LEDGER_SCHEMAS as LEDGER_SCHEMAS,
)
from alpha_cli._rdagent_judge import LINEAGE_CONVENTION, lineage
from alpha_cli._rdagent_judge import (
    LOOP_UNIVERSE as LOOP_UNIVERSE,
)
from alpha_cli._rdagent_judge import (
    MIN_NAMES as MIN_NAMES,
)
from alpha_cli._rdagent_judge import (
    PANEL_END as PANEL_END,
)
from alpha_cli._rdagent_judge import (
    Q_THRESHOLD as Q_THRESHOLD,
)
from alpha_cli._rdagent_judge import (
    SPREAD_REASON as SPREAD_REASON,
)
from alpha_cli._rdagent_judge import (
    SURVIVORSHIP as SURVIVORSHIP,
)
from alpha_cli._rdagent_judge import (
    TOP_FRACTION as TOP_FRACTION,
)
from alpha_cli._rdagent_judge import (
    TRIAL_SCHEMA as TRIAL_SCHEMA,
)
from alpha_cli._rdagent_judge import (
    WINDOWS as WINDOWS,
)
from alpha_cli._rdagent_judge import (
    _days as _days,
)
from alpha_cli._rdagent_judge import (
    _thirds as _thirds,
)
from alpha_cli._rdagent_judge import (
    canonical as canonical,
)
from alpha_cli._rdagent_judge import (
    exclusive as exclusive,
)
from alpha_cli._rdagent_judge import (
    freeze as freeze,
)
from alpha_cli._rdagent_judge import (
    matrix as matrix,
)
from alpha_cli._rdagent_judge import (
    outside_git as outside_git,
)
from alpha_cli._rdagent_judge import (
    screen as screen,
)
from alpha_cli._rdagent_judge import (
    screen_at_clock as screen_at_clock,
)
from alpha_cli._rdagent_judge import (
    sha as sha,
)
from alpha_cli._rdagent_judge import (
    spread as spread,
)
from alpha_cli._rdagent_judge import (
    spread_at_clock as spread_at_clock,
)
from alpha_cli._rdagent_judge import (
    validate_panel as validate_panel,
)
from alpha_cli._rdagent_judge_replay import (
    replay as replay,
)
from alpha_cli._rdagent_ledger import (
    LedgerRows as LedgerRows,
)
from alpha_cli._rdagent_ledger import (
    _ledger_family as _ledger_family,
)
from alpha_cli._rdagent_ledger import (
    _read_ledger as _read_ledger,
)
from alpha_cli._rdagent_ledger import (
    import_historical as import_historical,
)
from alpha_cli._rdagent_stability import (
    deflation_passes,
    failure_message,
    replay_output,
    status_reason,
    writeoff_summary,
)
from alpha_cli._rdagent_stability import plain_name as plain_name
from alpha_cli._rdagent_stats import (
    FACTOR_DEFLATION_RULE,
    factor_deflation,
)
from alpha_cli.toolbox.reserve import RESERVED_DAY as RESERVED_DAY
from alpha_cli.toolbox.reserve import RESERVED_START as RESERVED_START
from alpha_core import DataError
from alpha_validation.dsr import (
    expected_max_sharpe,
    probabilistic_sharpe_ratio,
)


def _inputs(
    run: Path, request_path: Path
) -> tuple[dict[str, Any], pl.DataFrame, pl.DataFrame, dict[str, str]]:
    request_bytes = request_path.read_bytes()
    request = json.loads(request_bytes)
    if (
        request.get("schema") != "AlphaRdagentFactorRequestV1"
        or type(request.get("iteration")) is not int
        or request["iteration"] < 0
        or not request.get("factors")
    ):
        raise DataError("invalid factor request")
    names = []
    for factor in request["factors"]:
        if (
            type(factor.get("declared_direction")) is not int
            or factor["declared_direction"] not in (-1, 1)
            or factor.get("primary_clock") not in ("weekly", "monthly")
            or not isinstance(factor.get("direction_reason"), str)
            or not factor["direction_reason"].strip()
        ):
            raise DataError(
                "Each factor must add declared_direction (+1 or -1), primary_clock"
                " (weekly or monthly), and direction_reason (one non-empty "
                "sentence of economic reasoning)."
            )
        if factor["status"] not in {"OK", "FAILED", "LOOKAHEAD", "UNSTABLE"} or not re.fullmatch(
            "[0-9a-f]{64}", factor["code_sha256"]
        ):
            raise DataError("invalid factor status or identity")
        names.append(factor["name"])
    if len(set(names)) != len(names) or any(not isinstance(n, str) or not n for n in names):
        raise DataError("factor names must be distinct non-empty strings")
    panel_bytes = (run / "panel/panel.parquet").read_bytes()
    receipt = json.loads((run / "panel/panel-receipt.json").read_bytes())
    if sha(panel_bytes) != receipt["panel_sha256"]:
        raise DataError("panel sha256 differs from receipt")
    if any(item["last_day"] >= RESERVED_START for item in receipt["instruments"].values()):
        raise DataError("panel receipt reaches reserved window")
    bound = (run / "panel/universe.json").exists() or "universe_sha256" in receipt
    if bound and receipt.get("universe_sha256") != sha(canonical(universes.frozen(run / "panel"))):
        # A universe chosen or edited after the freeze is a researcher choice made after seeing
        # data; only the file the freeze bound into its receipt is accepted.
        raise DataError("panel universe file differs from the one bound in the panel receipt")
    panel = validate_panel(pl.read_parquet(io.BytesIO(panel_bytes)))
    value_path = request_path.parent / request["values_file"]
    value_bytes = value_path.read_bytes()
    values = pl.read_parquet(io.BytesIO(value_bytes))
    if values.height:
        values = values.with_columns(_days(values))
    if values.height and (values["date"] >= RESERVED_DAY).any():
        raise DataError("factor values reach reserved window")
    if values.height and values.select(["date", "instrument"]).is_duplicated().any():
        raise DataError("duplicate factor value keys")
    if not set(values["instrument"].to_list()) <= set(panel["instrument"].to_list()):
        raise DataError("factor instruments outside panel")
    fingerprint = sha(
        Path(__file__).read_bytes()
        + Path(__file__).with_name("_rdagent_judge.py").read_bytes()
        + Path(__file__).with_name("_rdagent_judge_replay.py").read_bytes()
        + Path(__file__).with_name("_rdagent_membership.py").read_bytes()
        + Path(__file__).with_name("_rdagent_identity.py").read_bytes()
        + Path(__file__).with_name("_rdagent_clocks.py").read_bytes()
        + Path(__file__).with_name("_rdagent_universe.py").read_bytes()
        + Path(__file__).with_name("_rdagent_stability.py").read_bytes()
        + Path(__file__).with_name("_rdagent_ledger.py").read_bytes()
        + Path(__file__).with_name("_rdagent_stats.py").read_bytes()
        + Path(__file__).with_name("_rdagent_twins.py").read_bytes()
        + Path(__file__).with_name("_factor_eval_series.py").read_bytes()
        + Path(__file__).with_name("_factor_eval_replay.py").read_bytes()
        + Path(__file__).with_name("_factor_eval_screen.py").read_bytes()
        + (Path(__file__).resolve().parents[4] / "uv.lock").read_bytes()
    )
    return (
        request,
        panel,
        values,
        {
            "factor_values_path": str(value_path.resolve()),
            "panel_sha256": sha(panel_bytes),
            "request_sha256": sha(request_bytes),
            "factors_sha256": sha(value_bytes),
            "evaluator_fingerprint": fingerprint,
            "configuration_sha256": sha(canonical({**CONFIG, "costs": judge_costs()})),
            "universe_sha256": sha(canonical(universes.frozen(run / "panel"))),
        },
    )


def _deflate(
    rows: list[dict[str, Any]],
    history: list[dict[str, Any]],
    family: dict[tuple[str, str], dict[str, Any]],
    replay_returns: dict[tuple[str, str], np.ndarray],
) -> list[float]:
    """Count every screen look; estimate variance from distinct replayed trial Sharpes."""
    trials = [
        trial["replay"]["net"]["per_observation_sharpe"]
        for trial in family.values()
        if "net" in trial["replay"]
    ]
    identities: dict[str, dict[str, Any]] = {}
    for row in [*history, *rows]:
        if row["status"] != "REPEAT":
            identities.setdefault(row["code_sha256"], row)
    for row in rows:
        row["replayed_trials"] = len(trials)
        if row["status"] == "REPEAT":
            earliest = identities[row.get("repeat_code_sha256", row["code_sha256"])]
            row["first_trial"] = {
                k: earliest[k] for k in ("run_id", "iteration", "name", "status", "screen")
            }
            for clock, trial in trial_clocks(earliest).items():
                row["clocks"][clock].update(
                    {
                        k: trial[k]
                        for k in ("status", "p", "screen", "replay", "spread")
                        if k in trial
                    }
                )
            _keep_first_costs(row, earliest)
            row["diagnostics"] = earliest.get("diagnostics", {})
            row["lead_clock"] = earliest.get("lead_clock", "daily")
            row.update(
                {k: row["clocks"][row["lead_clock"]][k] for k in ("p", "q", "screen", "replay")}
            )
            continue
        for clock, trial in trial_clocks(row).items():
            key = (row["code_sha256"], clock)
            if key not in replay_returns:
                continue
            returns = replay_returns[key]
            trial["replay"]["deflated_sharpe"] = factor_deflation(returns, trials, len(family))
            trial["replay"].update(
                {
                    k: v
                    for k, v in trial["replay"]["deflated_sharpe"].items()
                    if k.startswith("deflation_")
                }
            )
            if len(trials) >= 2:
                benchmark = expected_max_sharpe(float(np.var(trials, ddof=1)), len(family))
                trial["replay"]["deflated_sharpe_family"] = {
                    "n_trials": len(family),
                    "benchmark_sharpe": benchmark,
                    "psr": probabilistic_sharpe_ratio(returns, benchmark_sr=benchmark),
                }
            else:
                trial["replay"]["deflated_sharpe_family"] = {
                    "n_trials": len(family),
                    "psr": None,
                    "reason": "fewer than two replayed trials: no cross-trial variance",
                }
        if row["status"] in {"CANDIDATE", "DEFLATION_FAIL"}:
            row["status"], row["lead_clock"] = overall_status(
                row["clocks"], row.get("primary_clock")
            )
    return trials


def finalize_rows(rows: list[dict[str, Any]]) -> None:
    for row in rows:
        if row["status"] in {"CANDIDATE", "DEFLATION_FAIL"}:
            row["status"], row["lead_clock"] = overall_status(
                row["clocks"], row.get("primary_clock")
            )
        row.update({k: row["clocks"][row["lead_clock"]][k] for k in ("p", "q", "screen", "replay")})
        row["figures_clock"] = row["lead_clock"]
        row["mean_ic"] = row["screen"].get("mean_ic")
        row["spread"] = row["clocks"][row["lead_clock"]].get("spread", {})
        row["bh_q_diagnostic"] = row["q"]
        row.update({k: v for k, v in row["replay"].items() if k.startswith("deflation_")})
        row["reason"] = status_reason(row)
        if row["status"] in {"CANDIDATE", "DEFLATION_FAIL"}:
            row["reason"] += " " + row["chance_pass_message"]


def shown(trial: dict[str, Any]) -> dict[str, Any]:
    """A trial's replay as a result; a counted-only replay (ADR-0055) shows nothing."""
    replay: dict[str, Any] = trial["replay"]
    return {} if "counted_only" in replay else replay_output(replay)


def record_shortlist(
    rows: list[dict[str, Any]],
    history: list[dict[str, Any]],
    values: pl.DataFrame,
    inputs: dict[str, str],
    days: list[date],
    symbols: list[str],
) -> None:
    """Append bookkeeping after every gate; never feed it back into trial accounting."""
    earlier = list(history)
    for row in rows:
        row["shortlist"] = row["status"] in {"CANDIDATE", "DEFLATION_FAIL"}
        if row["shortlist"]:
            try:
                figures = lineage(
                    matrix(values, row["name"], days, symbols),
                    earlier,
                    inputs["panel_sha256"],
                    days,
                    symbols,
                )
            except (
                DataError,
                ValueError,
                KeyError,
                OSError,
                MemoryError,
                FloatingPointError,
                np.linalg.LinAlgError,
                pl.exceptions.PolarsError,
            ) as error:
                # A diagnostic never decides or loses a verdict: record why it is missing.
                figures = {
                    "lineage_r2": None,
                    "lineage_regressors": 0,
                    "lineage_convention": LINEAGE_CONVENTION,
                    "lineage_reason": f"not computed: {type(error).__name__}: {error}",
                    "composite_suspect": None,
                }
            row.update(figures)
        earlier.append(row)


def _report(
    rows: list[dict[str, Any]],
    history: list[dict[str, Any]],
    family: dict[tuple[str, str], dict[str, Any]],
    trials: list[float],
    spec: dict[str, Any] | None = None,
    universe_text: str | None = None,
) -> tuple[dict[str, Any] | None, dict[str, Any], dict[str, Any], bool, str]:
    """Lead factor, RD-Agent's result keys, disclosures, ALPHA's decision and feedback text."""
    costs = judge_costs()
    # The lead is the best candidate when there is one, so RD-Agent's stored result matches the
    # decision; otherwise the lowest q among this request's new factors.
    candidates = [row for row in rows if row["status"] == "CANDIDATE"]
    eligible = candidates or [
        row
        for row in rows
        if row["status"] in {"FAST_ONLY", "REPLAY_FAIL", "SPREAD_FAIL", "SCREEN_FAIL"}
    ]
    lead = (
        min(eligible, key=lambda r: (r["clocks"][r["lead_clock"]]["q"], r["name"]))
        if eligible
        else None
    )
    lead_trial = lead["clocks"][lead["lead_clock"]] if lead else None
    if lead_trial is not None and "counted_only" in lead_trial["replay"]:
        lead_trial = {**lead_trial, "replay": {}}  # a failed clock's replay is not a result
    legacy = {
        "IC": lead_trial["screen"].get("mean_ic", float("nan")) if lead_trial else float("nan")
    }
    for cost, key in (("without", "gross"), ("with", "net")):
        for metric in ("annualized_return", "max_drawdown"):
            legacy[f"1day.excess_return_{cost}_cost.{metric}"] = (
                lead_trial["replay"].get(key, {}).get(metric, float("nan"))
                if lead_trial
                else float("nan")
            )
    for row in rows:
        for clock, trial in trial_clocks(row).items():
            prefix = f"{row['name']}.{clock}."
            legacy.update(
                {
                    prefix + "status": trial["status"],
                    prefix + "mean_ic": trial["screen"].get("mean_ic", float("nan")),
                    prefix + "q": trial["q"],
                    prefix + "net_annual_excess": shown(trial)
                    .get("net", {})
                    .get("annualized_return", float("nan")),
                    prefix + "mean_turnover": shown(trial).get("mean_turnover", float("nan")),
                }
            )
        legacy[f"{row['name']}.feedback"] = clock_feedback(row)
    spec = spec or universes.DEFAULT
    survivorship = universe_text or spec["survivorship"]
    disclosures = {
        "survivorship": survivorship,
        "multiple_testing": "screening only, adaptive family, no error rate claimed",
        "direction": "declared before evaluation",
        "replay_engine": "ALPHA canonical synchronized replay, not Nautilus",
        "legacy_result_keys": (
            "RD-Agent's 1day.* result keys carry the lead clock's metrics, whatever its horizon"
        ),
        "turnover_per_rebalance": (
            "all traded value over the span divided by the number of rebalances, so it includes "
            "the small residual trades between rebalances"
        ),
        "close_stamp": "origin + 23h; full UTC day bar known at its close",
        "lookahead_scope": (
            "prefix invariance at fixed cuts only; not proof against leakage within cuts"
        ),
        **CONFIG,
        "costs": costs,
    }
    if spec != universes.DEFAULT:
        disclosures["universe"] = spec
    decision = any(row["status"] == "CANDIDATE" for row in rows)
    feedback = (
        f"{LABEL}. {survivorship}. "
        f"looks so far across all ideas: {len(family)} (sets the screen cutoff); "
        "primary clocks now; legacy clocks and unreadable rows included; "
        f"distinct factors: {len({key[0] for key in family if key[1] != 'unknown'})}; "
        f"replayed trials: {len(trials)}. Screening only, adaptive family, no "
        "error rate claimed. Direction and primary clock declared before evaluation. Exploration "
        f"{EXPLORATION[0]}..{EXPLORATION[1]}; history 2017-08-17..2020-12-31; panel ends "
        f"{PANEL_END}; {RESERVED_START}+ reserved, never evaluated. Decide at close, fill next "
        "open; daily (1-day), weekly (7-day), monthly (28-day) non-overlapping holding clocks "
        "phased at 2021-01-01; ALPHA canonical synchronized replay, not Nautilus; "
        f"{costs_text(costs)} (cost table, {costs['asset_class']}). Prefix invariance is a "
        "fixed-cut check, not proof. "
    )
    feedback += other_cost_note(other_cost_rows(history, costs)) + " "
    feedback += CONFIG["residual_trades"] + " "
    feedback += " ".join(
        clock_feedback(row) + " " + row.get("writeoff_message", "") for row in rows
    )
    for row in rows:
        exposure = row["exposure"]
        if exposure["previously_exposed"]:
            families = ", ".join(f"{m['family_id']} ({m['status']})" for m in exposure["matches"])
            feedback += (
                f" {row['name']}: protected window {exposure['protected_window_start']}+ "
                f"previously exposed for family {families}; it cannot give fresh confirmation."
            )
    feedback += f" ALPHA decision: {decision}; admitted/evidence/approval/promotion all false."
    return lead, legacy, disclosures, decision, feedback


def _factor_identities(history: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    identities: dict[str, dict[str, Any]] = {}
    for row in history:
        if row["status"] != "REPEAT":
            identities.setdefault(row["code_sha256"], row)
    for row in history:
        target = row.get("repeat_code_sha256")
        if target in identities:
            identities.setdefault(row["code_sha256"], identities[target])
    return identities


def _evaluate_locked(
    run: Path,
    request: dict[str, Any],
    panel: pl.DataFrame,
    values: pl.DataFrame,
    inputs: dict[str, str],
    ledger: Path,
) -> dict[str, Any]:
    from alpha_cli.rdagent_exposure import snapshot

    entries, exposure_bytes = snapshot(ledger)
    record_inputs: dict[str, Any] = {
        **{k: v for k, v in inputs.items() if k != "factor_values_path"},
        "exposure_log_sha256": sha(exposure_bytes) if exposure_bytes is not None else None,
    }
    all_history = _read_ledger(ledger)
    unknown = all_history.unknown_rows
    history = [
        row
        for row in all_history
        if row["schema"] in LEDGER_SCHEMAS and row["schema"] != "AlphaRuleTrialV1"
    ]
    identities = _factor_identities(history)
    first, last = (date.fromisoformat(d) for d in EXPLORATION)
    days = [first + timedelta(days=n) for n in range((last - first).days + 1)]
    symbols = sorted(panel["instrument"].unique().to_list())
    open_days = [
        first + timedelta(days=n) for n in range((date.fromisoformat(PANEL_END) - first).days + 1)
    ]
    opens = matrix(panel, "open", open_days, symbols)
    outcome = opens[2 : len(days) + 2] / opens[1 : len(days) + 1] - 1
    spec = universes.frozen(run / "panel")
    universes.evaluable(spec)
    if spec["min_names"] != MIN_NAMES or spec["annual_periods"] != ANNUAL_DAYS:
        raise DataError(
            f"universe {spec['name']!r}: min_names {MIN_NAMES} and {ANNUAL_DAYS} days a year are "
            "the only values the evaluator applies yet"
        )
    receipt = json.loads((run / "panel/panel-receipt.json").read_bytes())
    breaks = receipt.get("identity_breaks", [])
    universe_info = universes.disclosure(spec, receipt)
    eligible, gap_policy = _eligibility(run, panel, days, symbols, spec)
    closes = matrix(panel, "close", open_days, symbols) if gap_policy else None
    series: dict[str, dict[str, Any]] = {}
    rows, signals = _screen_factors(
        run,
        request,
        values,
        inputs,
        history,
        identities,
        entries,
        days,
        symbols,
        opens,
        open_days,
        series,
        eligible,
        universe_info["universe_text"],
        gap_policy,
        closes,
    )
    all_count = len(all_history) + len(rows)
    for index, row in enumerate(rows, len(all_history) + 1):
        row.update(
            trial_index=index,
            ledger_trials_all_families=all_count,
            universe_includes_delisted=universe_info["universe_includes_delisted"],
        )
        if row["status"] in {"LOOKAHEAD", "UNSTABLE"}:
            row.update(failure_reason=row["status"], failure_detail=failure_message(row))
    family = _ledger_family([*history, *unknown, *rows])
    replay_returns, qvalues = _replay_clocks(
        rows,
        panel,
        signals,
        days,
        series,
        family,
        len(history) + len(unknown) + len(rows),
        gap_policy,
        frozenset(entry["new_name"] for entry in breaks),
        confirmed=sum(
            r["status"] == "CANDIDATE"
            and r.get("deflation_rule") == FACTOR_DEFLATION_RULE
            and deflation_passes(r["clocks"][r["lead_clock"]])
            for r in history
        ),
    )
    for row in rows:
        row["writeoff_count"], row["writeoff_message"] = writeoff_summary(
            row, membership.DELISTING_HAIRCUT
        )
    series_note = _record_series(
        run, request["iteration"], rows, series, signals, outcome, days, symbols, record_inputs
    )
    trials = _deflate(rows, history, family, replay_returns)
    _chance_disclosure(rows, history)
    finalize_rows(rows)
    record_shortlist(rows, history, values, inputs, days, symbols)
    lead, legacy, disclosures, decision, feedback = _report(
        rows, history, family, trials, spec, universe_info["universe_text"]
    )
    if "identity_breaks" in receipt:
        note = identity.disclosure(breaks)
        disclosures["identity_breaks"] = {
            "applied": breaks,
            "message": note,
            "jump_policy": receipt["identity_jump_policy"],
        }
        feedback += " " + note
        for row in rows:
            legacy[f"{row['name']}.feedback"] += " " + note
    if gap_policy:
        disclosure, note = _gap_disclosure(panel, rows)
        disclosures["missing_bars"] = disclosure
        feedback += note
        for row in rows:
            row["missing_bars"] = disclosure
            legacy[f"{row['name']}.feedback"] += note
    feedback += f" Ledger rows, all families (rules, repeats too): {all_count}."
    record = {
        "schema": "AlphaRdagentFactorEvaluationV1",
        "ledger_trials_all_families": all_count,
        "iteration": request["iteration"],
        "label": LABEL,
        "authority": AUTHORITY,
        "disclosures": disclosures,
        "inputs": record_inputs,
        "factors": rows,
        "family_size": len(family),
        "distinct_factors": len({key[0] for key in family if key[1] != "unknown"}),
        "total_trials": len(history) + len(unknown) + len(rows),
        "replayed_trials": len(trials),
        "qvalues": qvalues,
        "decision": decision,
        "lead_factor": lead["name"] if lead else None,
        "legacy_result": legacy,
        "feedback_text": feedback,
    }
    if series_note is not None:
        record["series_note"] = series_note
    if unknown:
        schemas = sorted({row["schema"] for row in unknown})
        record["ledger_unknown_rows"] = {"count": len(unknown), "schemas": schemas}
    _append_rows(ledger, rows)
    return record


def _append_rows(ledger: Path, rows: list[dict[str, Any]]) -> None:
    with ledger.open("ab", buffering=0) as stream:
        for row in rows:
            line = canonical(row)
            if stream.write(line) != len(line):
                raise DataError("short trial ledger write")
            os.fsync(stream.fileno())


def evaluate(run: Path, request_path: Path, out: Path, ledger: Path) -> dict[str, Any]:
    outside_git(ledger)
    if out.exists():
        raise DataError("evaluation output already exists")
    request, panel, values, inputs = _inputs(run, request_path)
    with Path(str(ledger) + ".lock").open("a+b") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        record = _evaluate_locked(run, request, panel, values, inputs, ledger)
        record["checks"], suffix = post_judge_checks(run, record)
        record["feedback_text"] += suffix
        rendered = canonical(record)
        exclusive(out, rendered)
        with (run / "evaluations.jsonl").open("ab", buffering=0) as stream:
            if stream.write(rendered) != len(rendered):
                raise DataError("short evaluation write")
            os.fsync(stream.fileno())
    return record


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Exploratory RD-Agent factor screen and ALPHA replay; no admission authority."
    )
    sub = parser.add_subparsers(dest="command", required=True)
    freezing = sub.add_parser("freeze")
    freezing.add_argument("--data-dir", type=Path, required=True)
    freezing.add_argument("--out", type=Path, required=True)
    freezing.add_argument("--universe", type=Path, help="universe file (ADR-0055)")
    freezing.add_argument("--funding-dir", type=Path)
    evaluating = sub.add_parser("evaluate")
    for name in ("run-dir", "request", "out", "ledger"):
        evaluating.add_argument(f"--{name}", type=Path, required=True)
    importing = sub.add_parser("import-historical")
    importing.add_argument("--ledger", type=Path, required=True)
    importing.add_argument("--file", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "freeze":
        freeze(args.data_dir, args.out, args.universe, args.funding_dir)
    elif args.command == "import-historical":
        import_historical(args.ledger, args.file)
    else:
        evaluate(args.run_dir, args.request, args.out, args.ledger)


if __name__ == "__main__":
    try:
        main()
    except DataError as error:  # a refusal is one plain line, not a traceback
        print(f"rdagent-factor-eval: {error}", file=sys.stderr)
        raise SystemExit(2) from None
