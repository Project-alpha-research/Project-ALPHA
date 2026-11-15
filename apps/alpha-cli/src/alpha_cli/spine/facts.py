"""Fixed, source-addressed facts read from stored JSON; no metric computation."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from alpha_cli.spine.errors import SpineError

# Public vocabulary: one plain-English meaning per metric.
METRICS = {
    "verdict": "The stored validation verdict.",
    "oos_sharpe": "Sharpe of walk-forward out-of-sample returns.",
    "dsr": "The validation gauntlet's stored deflated Sharpe probability.",
    **{
        f"{prefix}_{metric}": f"{label} {meaning}."
        for prefix, label in (
            ("full_sample", "Full-sample strategy"),
            ("benchmark", "Buy-and-hold benchmark"),
        )
        for metric, meaning in (
            ("total_return", "total return"),
            ("cagr", "annual growth rate"),
            ("sharpe", "Sharpe ratio"),
            ("max_drawdown", "maximum drawdown"),
        )
    },
    "trades": "Number of closed full-sample trades.",
    "exposure": "Share of full-sample bars with a long position.",
    "top_1_profit_share": "Share of total closed profit from the largest trade.",
    "top_3_profit_share": "Share of total closed profit from the largest three trades.",
    "delay_base_sharpe": "Base returns-level surrogate Sharpe.",
    "delayed_sharpe": "Surrogate Sharpe with weights delayed one bar.",
    "total_trials": "Ledger trial count observed for this diagnostic pass.",
    "trial_dsr": "Deflated Sharpe using available symbol trials and sensitivity variants.",
    "variants_evaluated": "Number of sensitivity re-runs evaluated.",
}
_FIELDS = {
    "verdict": ("manifest.json", "verdict.overall", "walk-forward validation gauntlet"),
    "oos_sharpe": ("manifest.json", "oos_metrics.sharpe", "walk-forward out-of-sample returns"),
    "dsr": ("manifest.json", "dsr.dsr", "walk-forward validation gauntlet"),
    **{
        f"{prefix}_{metric}": ("diagnostics.json", f"{prefix}.{metric}", basis)
        for prefix, basis in (
            ("full_sample", "full-sample backtest"),
            ("benchmark", "buy and hold, same bars, no costs"),
        )
        for metric in ("total_return", "cagr", "sharpe", "max_drawdown")
    },
    **{
        name: ("diagnostics.json", field, basis)
        for name, field, basis in (
            ("trades", "full_sample.trades", "full-sample backtest"),
            ("exposure", "full_sample.exposure", "full-sample backtest"),
            (
                "top_1_profit_share",
                "concentration.top_1",
                "full-sample closed-trade realized profit",
            ),
            (
                "top_3_profit_share",
                "concentration.top_3",
                "full-sample closed-trade realized profit",
            ),
            ("delay_base_sharpe", "delay.base_sharpe", "returns-level approximation"),
            ("delayed_sharpe", "delay.delayed_sharpe", "returns-level approximation"),
            ("total_trials", "trials.total_trials", "ledger at the time of the run"),
            ("trial_dsr", "trials.dsr", "available symbol trial Sharpes and sensitivity variants"),
            ("variants_evaluated", "variants_evaluated", "full-sample sensitivity engine re-runs"),
        )
    },
}


def read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path.name} must contain an object")
    return value


def build_facts(rdir: Path) -> list[dict[str, Any]]:
    documents = {name: read_json(rdir / name) for name in ("manifest.json", "diagnostics.json")}
    labels = documents["manifest.json"].get("spine", {}).get("labels", [])
    facts = []
    for metric, (filename, field, basis) in _FIELDS.items():
        parent = documents[filename]
        parts = field.split(".")
        for part in parts[:-1]:
            parent = parent.get(part, {})
        value = parent.get(parts[-1])
        reason = parent.get("reasons", {}).get(parts[-1]) or f"{filename}:{field} is unavailable"
        facts.append(
            {
                "metric": metric,
                "value": value,
                "run_id": rdir.name,
                "basis": basis if metric == "total_trials" else parent.get("basis", basis),
                "source": f"{filename}:{field}",
                "labels": labels,
                "reason": reason if value is None else None,
            }
        )
    return facts


def require_metric(metric: str) -> None:
    if metric not in METRICS:
        raise SpineError(
            "UNKNOWN_METRIC",
            f"Unknown metric {metric!r}.",
            "Run alpha results cite with one of the known metrics.",
            list(METRICS),
        )
