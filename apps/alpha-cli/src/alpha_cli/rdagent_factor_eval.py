"""Exploratory RD-Agent factor screen and ALPHA replay; no admission authority."""

from __future__ import annotations

import argparse
import fcntl
import io
import json
import math
import os
import re
import sys
from collections.abc import Iterator
from dataclasses import asdict
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import numpy as np
import polars as pl

from alpha_cli import _rdagent_identity as identity
from alpha_cli import _rdagent_membership as membership
from alpha_cli import _rdagent_universe as universes
from alpha_cli._rdagent_clocks import (
    CLOCKS as CLOCKS,
)
from alpha_cli._rdagent_clocks import (
    clock_feedback,
    overall_status,
    trial_clocks,
)
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
    RESERVED_DAY as RESERVED_DAY,
)
from alpha_cli._rdagent_judge import (
    RESERVED_START as RESERVED_START,
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
from alpha_cli._rdagent_judge import panel_membership
from alpha_cli._rdagent_judge import (
    plain_name as plain_name,
)
from alpha_cli._rdagent_judge import (
    replay as replay,
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
from alpha_cli._rdagent_stability import failure_message, replay_output, writeoff_summary
from alpha_core import DataError
from alpha_validation.dsr import (
    deflated_sharpe,
    expected_max_sharpe,
    probabilistic_sharpe_ratio,
)
from alpha_validation.proportion import benjamini_hochberg


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
        + Path(__file__).with_name("_rdagent_membership.py").read_bytes()
        + Path(__file__).with_name("_rdagent_identity.py").read_bytes()
        + Path(__file__).with_name("_rdagent_clocks.py").read_bytes()
        + Path(__file__).with_name("_rdagent_universe.py").read_bytes()
        + Path(__file__).with_name("_rdagent_stability.py").read_bytes()
        + (Path(__file__).resolve().parents[4] / "uv.lock").read_bytes()
    )
    return (
        request,
        panel,
        values,
        {
            "panel_sha256": sha(panel_bytes),
            "request_sha256": sha(request_bytes),
            "factors_sha256": sha(value_bytes),
            "evaluator_fingerprint": fingerprint,
            "configuration_sha256": sha(canonical(CONFIG)),
            "universe_sha256": sha(canonical(universes.frozen(run / "panel"))),
        },
    )


def _deflate(
    rows: list[dict[str, Any]],
    history: list[dict[str, Any]],
    family: dict[tuple[str, str], dict[str, Any]],
    replay_returns: dict[tuple[str, str], np.ndarray],
) -> list[float]:
    """Deflate against every distinct replayed factor x clock in ledger order."""
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
            earliest = identities[row["code_sha256"]]
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
            row["lead_clock"] = earliest.get("lead_clock", "daily")
            row.update({k: row["clocks"]["daily"][k] for k in ("p", "q", "screen", "replay")})
            continue
        for clock, trial in trial_clocks(row).items():
            key = (row["code_sha256"], clock)
            if key not in replay_returns:
                continue
            returns = replay_returns[key]
            trial["replay"]["deflated_sharpe"] = asdict(
                deflated_sharpe(returns, trial_sharpes=trials)
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
    return trials


def shown(trial: dict[str, Any]) -> dict[str, Any]:
    """A trial's replay as a result; a counted-only replay (ADR-0055) shows nothing."""
    replay: dict[str, Any] = trial["replay"]
    return {} if "counted_only" in replay else replay_output(replay)


def _report(
    rows: list[dict[str, Any]],
    history: list[dict[str, Any]],
    family: dict[tuple[str, str], dict[str, Any]],
    trials: list[float],
    spec: dict[str, Any] | None = None,
    universe_text: str | None = None,
) -> tuple[dict[str, Any] | None, dict[str, Any], dict[str, Any], bool, str]:
    """Lead factor, RD-Agent's result keys, disclosures, ALPHA's decision and feedback text."""
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
        "direction": "chosen in-sample",
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
    }
    if spec != universes.DEFAULT:
        disclosures["universe"] = spec
    decision = any(row["status"] == "CANDIDATE" for row in rows)
    feedback = (
        f"{LABEL}. {survivorship}. "
        f"Factor-family trials (each factor x clock, unreadable rows too): {len(family)}; "
        f"distinct factors: {len({key[0] for key in family if key[1] != 'unknown'})}; "
        f"replayed trials: {len(trials)}. Screening only, adaptive family, no "
        "error rate claimed. Direction chosen in-sample. Exploration "
        f"{EXPLORATION[0]}..{EXPLORATION[1]}; history 2017-08-17..2020-12-31; panel ends "
        f"{PANEL_END}; {RESERVED_START}+ reserved, never evaluated. Decide at close, fill next "
        "open; daily (1-day), weekly (7-day), monthly (28-day) non-overlapping holding clocks "
        "phased at 2021-01-01; ALPHA canonical synchronized replay, not Nautilus; 10 bps "
        "fee + 6 bps slippage per side. Prefix invariance is a fixed-cut check, not proof. "
    )
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


def _bucket_frames(
    signal: np.ndarray, outcome: np.ndarray, days: list[date], symbols: list[str], direction: int
) -> tuple[pl.DataFrame, pl.DataFrame]:
    observations: dict[int, list[float]] = {bucket: [] for bucket in (1, 2, 3)}
    daily = []
    for day, scores, returns in zip(days, signal, outcome, strict=True):
        available = [i for i, score in enumerate(scores) if math.isfinite(score)]
        ranked = sorted(available, key=lambda i: (-direction * scores[i], symbols[i]))
        k = max(1, round(TOP_FRACTION * len(available)))
        groups: dict[int, list[float]] = {bucket: [] for bucket in (1, 2, 3)}
        for rank, i in enumerate(ranked):
            if math.isfinite(returns[i]):
                bucket = 3 if rank < k else 1 if rank >= len(ranked) - k else 2
                groups[bucket].append(float(returns[i]))
        for bucket, outcomes in groups.items():
            observations[bucket].extend(outcomes)
            daily.append(
                {
                    "clock": "daily",
                    "date": day,
                    "bucket": bucket,
                    "mean_outcome": math.fsum(outcomes) / len(outcomes) if outcomes else None,
                }
            )
    # Explicit ordered sums avoid floating-point reductions depending on worker scheduling.
    buckets = [
        {
            "clock": "daily",
            "bucket": bucket,
            "mean_outcome": math.fsum(outcomes) / len(outcomes) if outcomes else None,
            "observations": len(outcomes),
        }
        for bucket, outcomes in observations.items()
    ]
    return (
        pl.DataFrame(buckets).with_columns(pl.col("mean_outcome").cast(pl.Float64)),
        pl.DataFrame(daily).with_columns(pl.col("mean_outcome").cast(pl.Float64)),
    )


def _clock_series_frames(
    row: dict[str, Any],
    data: dict[str, Any],
    signal: np.ndarray,
    outcome: np.ndarray,
    days: list[date],
    symbols: list[str],
) -> Iterator[tuple[str, pl.DataFrame]]:
    if "daily_ic" in data:
        yield (
            "screen",
            pl.DataFrame(
                {
                    "clock": ["daily"] * len(days),
                    "date": days,
                    "rank_ic": pl.Series(data["daily_ic"], dtype=pl.Float64),
                    "names": data["names"],
                }
            ),
        )
    if row["screen"].get("status") == "OK":
        buckets, daily = _bucket_frames(signal, outcome, days, symbols, row["screen"]["direction"])
        yield "buckets", buckets
        yield "buckets_daily", daily
    if "periods" in data:
        periods = [
            {"clock": "daily", **{k: v for k, v in asdict(p).items() if k != "fold"}}
            for p in data["periods"]
        ]
        yield "replay", pl.DataFrame(periods).sort(["clock", "target_ts", "exit_ts"])
        yield (
            "holdings",
            pl.DataFrame(
                [
                    {
                        "clock": "daily",
                        "date": t.origin_ts.date(),
                        "instrument": t.symbol,
                        "target_weight": t.target_weight,
                        "score": t.score,
                    }
                    for t in data["targets"]
                ]
            ).sort(["clock", "date", "instrument"]),
        )

    if data.get("events"):
        yield "events", pl.DataFrame(data["events"]).with_columns(pl.lit("daily").alias("clock"))
    if data.get("positions"):
        yield (
            "positions",
            pl.DataFrame(
                [
                    {
                        "clock": "daily",
                        "date": snapshot["date"],
                        "instrument": name,
                        "quantity": snapshot["quantities"][j],
                        "cash": snapshot["cash"],
                        "equity": snapshot["equity"],
                    }
                    for snapshot in data["positions"]
                    for j, name in enumerate(symbols)
                ]
            ),
        )


def _series_frames(
    row: dict[str, Any],
    data: dict[str, Any],
    signal: np.ndarray,
    outcome: np.ndarray,
    days: list[date],
    symbols: list[str],
) -> Iterator[tuple[str, pl.DataFrame]]:
    frames: dict[str, list[pl.DataFrame]] = {}
    for clock in CLOCKS:
        if clock not in data:
            continue
        block = data[clock]
        if "days" not in block:
            continue
        for kind, frame in _clock_series_frames(
            row["clocks"][clock], block, block["signal"], block["outcome"], block["days"], symbols
        ):
            frames.setdefault(kind, []).append(frame.with_columns(pl.lit(clock).alias("clock")))
    for kind, blocks in frames.items():
        yield kind, pl.concat(blocks)


def _series_file(path: Path, payload: bytes) -> None:
    try:
        exclusive(path, payload)
    except FileExistsError:
        if path.read_bytes() != payload:
            raise DataError(f"conflicting series file: {path.name}") from None


def _write_series(
    run: Path,
    iteration: int,
    rows: list[dict[str, Any]],
    series: dict[str, dict[str, Any]],
    signals: dict[str, np.ndarray],
    outcome: np.ndarray,
    days: list[date],
    symbols: list[str],
) -> tuple[str, str, set[str]]:
    relative = f"evaluations/iter-{iteration}/series/series.json"
    folder = (run / relative).parent
    folder.mkdir(parents=True, exist_ok=True)
    factors = []
    written = set()
    for row in rows:
        digest = row["code_sha256"]
        if digest not in series or row["stage"] == "none":
            continue
        files = []
        try:
            for kind, frame in _series_frames(
                row, series[digest], signals[digest], outcome, days, symbols
            ):
                name = f"{digest}.{kind}.parquet"
                buffer = io.BytesIO()
                frame.write_parquet(buffer)
                payload = buffer.getvalue()
                _series_file(folder / name, payload)
                files.append({"name": name, "sha256": sha(payload)})
        except Exception as error:  # Series must not change evaluation outcomes.
            row["series_note"] = f"{type(error).__name__}: {error}"
        if files:
            factors.append({"code_sha256": digest, "files": files})
            written.add(digest)
    payload = canonical({"schema": "AlphaRdagentTrialSeriesV1", "factors": factors})
    _series_file(run / relative, payload)
    return relative, sha(payload), written


def _record_series(
    run: Path,
    iteration: int,
    rows: list[dict[str, Any]],
    series: dict[str, dict[str, Any]],
    signals: dict[str, np.ndarray],
    outcome: np.ndarray,
    days: list[date],
    symbols: list[str],
    inputs: dict[str, Any],
) -> str | None:
    try:
        relative, digest, written = _write_series(
            run, iteration, rows, series, signals, outcome, days, symbols
        )
    except Exception as error:  # Evidence failures are recorded, never scoring failures.
        return f"{type(error).__name__}: {error}"
    inputs["series_sha256"] = digest
    for row in rows:
        if row["code_sha256"] in written and row["stage"] != "none":
            row["evidence"] = {"series_manifest": relative, "sha256": digest}
    return None


def _screen_factors(
    run: Path,
    request: dict[str, Any],
    values: pl.DataFrame,
    inputs: dict[str, str],
    history: list[dict[str, Any]],
    identities: dict[str, dict[str, Any]],
    entries: Any,
    days: list[date],
    symbols: list[str],
    opens: np.ndarray,
    open_days: list[date],
    series: dict[str, dict[str, Any]],
    eligible: np.ndarray | None = None,
    survivorship: str = SURVIVORSHIP,
    gap_policy: bool = False,
    closes: np.ndarray | None = None,
) -> tuple[list[dict[str, Any]], dict[str, np.ndarray]]:
    from alpha_cli.rdagent_exposure import label_for

    screen_options: dict[str, Any] = {"gap_policy": True, "closes": closes} if gap_policy else {}
    if eligible is not None:
        screen_options["eligible"] = eligible
    rows: list[dict[str, Any]] = []
    signals: dict[str, np.ndarray] = {}
    identity_path = run / "run-identity.json"
    identity = (
        json.loads(identity_path.read_bytes()) if identity_path.exists() else {"run_id": run.name}
    )
    if not isinstance(identity.get("run_id"), str) or not identity["run_id"].strip():
        raise DataError("invalid run identity")
    for factor in request["factors"]:
        digest = factor["code_sha256"]
        row = {
            **factor,
            "schema": TRIAL_SCHEMA,
            "plain_name": plain_name(factor["name"]),
            "trial_index": len(history) + len(rows) + 1,
            "run_id": identity["run_id"],
            "recorded_at": datetime.now(UTC).isoformat(),
            "iteration": request["iteration"],
            "panel_sha256": inputs["panel_sha256"],
            "windows": WINDOWS,
            "instruments": symbols,
            "stage": "none",
            "p": 1.0,
            "q": 1.0,
            "screen": {},
            "replay": {},
            "lead_clock": "daily",
            "label": LABEL,
            "survivorship": survivorship,
            "authority": AUTHORITY,
            "clocks": {
                c: {"status": "ERROR", "p": 1.0, "q": 1.0, "screen": {}, "replay": {}}
                for c in CLOCKS
            },
        }
        row["exposure"] = label_for(row, entries)
        if digest in identities:
            earliest = identities[digest]
            row["status"] = "REPEAT"
            row["first_trial"] = {
                k: earliest[k] for k in ("run_id", "iteration", "name", "status", "screen")
            }
            # Copy: repeats must never mutate the original trial or create replay evidence.
            for c, trial in trial_clocks(earliest).items():
                row["clocks"][c] = {
                    k: trial[k]
                    for k in ("status", "p", "q", "screen", "replay", "spread")
                    if k in trial
                }
            row["lead_clock"] = earliest.get("lead_clock", "daily")
        else:
            if factor["status"] == "OK":
                row["stage"] = "screen"
                for clock in CLOCKS:
                    block = series.setdefault(digest, {}).setdefault(clock, {})
                    try:
                        if factor["name"] not in values.columns:
                            raise DataError(f"no value column for factor {factor['name']!r}")
                        if digest not in signals:
                            values_matrix = matrix(values, factor["name"], days, symbols)
                            # ADR-0055: a name outside the point-in-time liquid universe on a
                            # decision day has no rank that day.
                            signals[digest] = (
                                values_matrix
                                if eligible is None
                                else np.where(eligible, values_matrix, np.nan)
                            )
                        stats = screen_at_clock(
                            signals[digest],
                            opens,
                            days,
                            digest,
                            clock,
                            open_days=open_days,
                            series=block,
                            **screen_options,
                        )
                    except (DataError, ValueError, ZeroDivisionError, FloatingPointError) as error:
                        stats = {
                            "status": "ERROR",
                            "p": 1.0,
                            "error": f"{type(error).__name__}: {error}",
                        }
                    row["clocks"][clock].update(status=stats["status"], p=stats["p"], screen=stats)
                    if stats["status"] == "OK":
                        row["clocks"][clock]["spread"] = _spread_or_error(
                            signals[digest],
                            opens,
                            days,
                            digest,
                            clock,
                            open_days,
                            stats,
                            symbols,
                            gap_policy=gap_policy,
                            closes=closes,
                        )
            identities[digest] = row
        rows.append(row)
    return rows, signals


def _spread_or_error(
    signal: np.ndarray,
    opens: np.ndarray,
    days: list[date],
    digest: str,
    clock: str,
    open_days: list[date],
    stats: dict[str, Any],
    symbols: list[str],
    *,
    gap_policy: bool = False,
    closes: np.ndarray | None = None,
) -> dict[str, Any]:
    try:
        return spread_at_clock(
            signal,
            opens,
            days,
            digest,
            clock,
            open_days=open_days,
            direction=stats["direction"],
            symbols=symbols,
            gap_policy=gap_policy,
            closes=closes,
        )
    except (DataError, ValueError, ZeroDivisionError, FloatingPointError) as error:
        return {"status": "ERROR", "error": f"{type(error).__name__}: {error}"}


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
        digest = row["code_sha256"]
        row.update(family_size=len(family), distinct_factors=len(qvalues), total_trials=total_rows)
        for clock, trial in row["clocks"].items():
            trial["q"] = qvalues[digest].get(clock, 1.0)
            if row["status"] != "OK" or trial["status"] != "OK":
                continue
            trial["status"] = "SCREEN_FAIL"
            if trial["q"] < Q_THRESHOLD:
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
            row["status"], row["lead_clock"] = overall_status(row["clocks"])
        row.update({k: row["clocks"]["daily"][k] for k in ("p", "q", "screen", "replay")})
    return replay_returns, qvalues


def _eligibility(
    run: Path,
    panel: pl.DataFrame,
    days: list[date],
    symbols: list[str],
    spec: dict[str, Any],
) -> tuple[np.ndarray | None, bool]:
    receipt = json.loads((run / "panel/panel-receipt.json").read_bytes())
    policy = receipt.get("gap_policy")
    if policy is not None and policy != membership.POLICY:
        raise DataError("unknown frozen gap policy")
    mask = panel_membership(panel, days, symbols) if policy is not None else None
    if spec["liquidity"] is not None:
        start = min(panel["date"].to_list())
        volume_days = [start + timedelta(days=n) for n in range((days[-1] - start).days + 1)]
        liquidity = universes.eligibility(
            matrix(panel, "quote_volume", volume_days, symbols),
            volume_days,
            days,
            spec["liquidity"],
        )
        mask = liquidity if mask is None else mask & liquidity
    return mask, policy is not None


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
        **inputs,
        "exposure_log_sha256": sha(exposure_bytes) if exposure_bytes is not None else None,
    }
    all_history = _read_ledger(ledger)
    unknown = all_history.unknown_rows
    history = [
        row
        for row in all_history
        if row["schema"] in LEDGER_SCHEMAS and row["schema"] != "AlphaRuleTrialV1"
    ]
    identities: dict[str, dict[str, Any]] = {}
    for row in history:
        if row["status"] != "REPEAT":
            identities.setdefault(row["code_sha256"], row)
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
    )
    for row in rows:
        row["writeoff_count"], row["writeoff_message"] = writeoff_summary(
            row, membership.DELISTING_HAIRCUT
        )
    series_note = _record_series(
        run, request["iteration"], rows, series, signals, outcome, days, symbols, record_inputs
    )
    trials = _deflate(rows, history, family, replay_returns)
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
        "distinct_factors": len(identities),
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
    with ledger.open("ab", buffering=0) as stream:
        for row in rows:
            line = canonical(row)
            if stream.write(line) != len(line):
                raise DataError("short trial ledger write")
            os.fsync(stream.fileno())
    return record


def evaluate(run: Path, request_path: Path, out: Path, ledger: Path) -> dict[str, Any]:
    outside_git(ledger)
    if out.exists():
        raise DataError("evaluation output already exists")
    request, panel, values, inputs = _inputs(run, request_path)
    with Path(str(ledger) + ".lock").open("a+b") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        record = _evaluate_locked(run, request, panel, values, inputs, ledger)
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
    evaluating = sub.add_parser("evaluate")
    for name in ("run-dir", "request", "out", "ledger"):
        evaluating.add_argument(f"--{name}", type=Path, required=True)
    importing = sub.add_parser("import-historical")
    importing.add_argument("--ledger", type=Path, required=True)
    importing.add_argument("--file", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "freeze":
        freeze(args.data_dir, args.out, args.universe)
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
