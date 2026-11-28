"""Screening for the RD-Agent factor evaluator: eligibility, the screen and the spread."""

from __future__ import annotations

import ast
import io
import json
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import numpy as np
import polars as pl

from alpha_cli import _rdagent_membership as membership
from alpha_cli import _rdagent_universe as universes
from alpha_cli._rdagent_clocks import CLOCKS
from alpha_cli._rdagent_judge import (
    SURVIVORSHIP,
    _days,
    matrix,
    screen_at_clock,
    sha,
    spread_at_clock,
)
from alpha_cli._rdagent_judge_replay import panel_membership
from alpha_cli._rdagent_ledger import new_factor_row
from alpha_cli._rdagent_twins import find_twin
from alpha_cli.toolbox.reserve import RESERVED_DAY
from alpha_core import DataError


def _keep_first_costs(row: dict[str, Any], earliest: dict[str, Any]) -> None:
    """A repeat copies its first trial's replay, so it keeps that trial's costs (none: older)."""
    row.pop("costs", None)
    if "costs" in earliest:
        row["costs"] = earliest["costs"]


def source_columns(code: bytes) -> list[str]:
    """Literal column selectors in Python syntax; comments and standalone strings do not count.

    This is syntax detection, not data-flow proof: dynamic column construction is not detected,
    and an unused subscript still counts. The factor output never chooses its eligibility.
    """
    tree = ast.parse(code)
    selectors = [node.slice for node in ast.walk(tree) if isinstance(node, ast.Subscript)]
    selectors.extend(
        argument
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr in {"get", "filter", "__getitem__"}
        for argument in [*node.args, *(kw.value for kw in node.keywords)]
    )
    return sorted(
        {
            node.value
            for selector in selectors
            for node in ast.walk(selector)
            if isinstance(node, ast.Constant)
            and isinstance(node.value, str)
            and node.value.startswith("$")
        }
    )


def reads_funding(code: bytes) -> bool:
    """Keep the eligibility rule tied to the same literal selector analysis."""
    return any(column.startswith("$funding_") for column in source_columns(code))


def funding_eligibility(
    run: Path, days: list[date], symbols: list[str], eligible: np.ndarray | None
) -> np.ndarray:
    path = run / "panel/funding.parquet"
    receipt = json.loads((run / "panel/panel-receipt.json").read_bytes())
    raw = path.read_bytes()
    if receipt.get("funding", {}).get("sha256") != sha(raw):
        raise DataError("funding sha256 differs from panel receipt")
    funding = pl.read_parquet(io.BytesIO(raw))
    funding = funding.with_columns(_days(funding))
    if funding.filter(pl.col("date") >= RESERVED_DAY).height:
        raise DataError("funding reaches reserved window")
    if funding.select("date", "instrument").is_duplicated().any():
        raise DataError("duplicate funding data keys")
    present = np.isfinite(matrix(funding, "funding_count", days, symbols))
    return np.asarray(present if eligible is None else present & eligible, dtype=bool)


def _factor_eligibility(
    run: Path,
    factor: dict[str, Any],
    row: dict[str, Any],
    days: list[date],
    symbols: list[str],
    eligible: np.ndarray | None,
) -> np.ndarray | None:
    path = run / "code" / f"{factor['code_sha256']}.py"
    row["input_columns_method"] = (
        "fallback: archived source unavailable; columns not listed, as before"
    )
    if not path.exists():
        if (run / "panel/funding.parquet").exists() and factor["status"] == "OK":
            raise DataError("funding-enabled evaluation requires archived factor source")
        return eligible
    code = path.read_bytes()
    if sha(code) != factor["code_sha256"]:
        raise DataError("factor source sha256 differs from request")
    if factor["status"] != "OK":
        row["input_columns_method"] = "fallback: unsuccessful factor; columns not listed, as before"
        return eligible
    columns = source_columns(code)
    row["input_columns_method"] = (
        "source-selectors"
        if columns
        else "fallback: no literal selectors; columns not listed, as before"
    )
    if columns:
        row["input_columns"] = columns
    if not reads_funding(code):
        return eligible
    mask = funding_eligibility(run, days, symbols, eligible)
    row.update(eligibility="perp-funding", mean_eligible_names=float(mask.sum(axis=1).mean()))
    row["funding_sha256"] = sha((run / "panel/funding.parquet").read_bytes())
    return mask


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
        row = new_factor_row(
            factor,
            inputs,
            len(history) + len(rows) + 1,
            identity["run_id"],
            request["iteration"],
            symbols,
            survivorship,
            datetime.now(UTC).isoformat(),
        )
        factor_eligible = _factor_eligibility(run, factor, row, days, symbols, eligible)
        screen_options: dict[str, Any] = (
            {"gap_policy": True, "closes": closes} if gap_policy else {}
        )
        if factor_eligible is not None:
            screen_options["eligible"] = factor_eligible
        row["exposure"] = label_for(row, entries)
        if (
            digest not in identities
            and factor["status"] == "OK"
            and factor["name"] in values.columns
        ):
            twin, details = find_twin(
                matrix(values, factor["name"], days, symbols),
                [*history, *rows],
                inputs["panel_sha256"],
                days,
                symbols,
            )
            row.update(details)
            if twin is not None:
                row["repeat_code_sha256"] = twin["code_sha256"]
                identities[digest] = twin
        if digest in identities:
            earliest = identities[digest]
            if earliest["code_sha256"] != digest:
                row["repeat_code_sha256"] = earliest["code_sha256"]
            row["status"] = "REPEAT"
            row["first_trial"] = {
                k: earliest[k] for k in ("run_id", "iteration", "name", "status", "screen")
            }
            # Copy: repeats must never mutate the original trial or create replay evidence.
            for c, trial in earliest.get("clocks", {"daily": earliest}).items():
                row["clocks"][c] = {
                    k: trial[k]
                    for k in ("status", "p", "q", "screen", "replay", "spread")
                    if k in trial
                }
            _keep_first_costs(row, earliest)
            row["diagnostics"] = earliest.get("diagnostics", {})
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
                                if factor_eligible is None
                                else np.where(factor_eligible, values_matrix, np.nan)
                            )
                        stats = screen_at_clock(
                            signals[digest],
                            opens,
                            days,
                            digest,
                            clock,
                            open_days=open_days,
                            series=block,
                            declared_direction=factor["declared_direction"],
                            **screen_options,
                        )
                    except (DataError, ValueError, ZeroDivisionError, FloatingPointError) as error:
                        stats = {
                            "status": "ERROR",
                            "p": 1.0,
                            "error": f"{type(error).__name__}: {error}",
                        }
                    row["clocks"][clock].update(status=stats["status"], p=stats["p"], screen=stats)
                    if clock != factor["primary_clock"]:
                        row["diagnostics"][clock] = {
                            "label": "diagnostic only: cannot pass",
                            "screen": stats,
                        }
                        row["clocks"][clock]["status"] = "DIAGNOSTIC"
                        continue
                    row["diagnostics"]["opposite_direction"] = stats.get("diagnostics", {})
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
