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
# Facts written by the investigation tools (alpha tool ...): metric -> (tool, meaning).
TOOL_METRICS = {
    "market_beta": (
        "attribution",
        "How much the strategy moves when the benchmark moves by one (1 = one for one).",
    ),
    "market_alpha_annual": (
        "attribution",
        "Yearly return left over after removing the benchmark exposure.",
    ),
    "market_alpha_p": (
        "attribution",
        "Chance of a leftover return this large if the true leftover were zero (p-value).",
    ),
    "market_r_squared": (
        "attribution",
        "Share of the strategy's return variation explained by the benchmark.",
    ),
    "regime_turbulent_share_of_return": (
        "regimes",
        "Share of the strategy's total log return earned in the most turbulent market regime.",
    ),
    "regime_turbulent_share_of_time": (
        "regimes",
        "Share of bars the market spent in its most turbulent regime.",
    ),
    "changepoint_count": (
        "changepoints",
        "Number of dates at which the run's behaviour shifted, found with hindsight.",
    ),
}
METRICS.update({metric: meaning for metric, (_, meaning) in TOOL_METRICS.items()})
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
        parent: Any = documents[filename]
        parts = field.split(".")
        for part in parts[:-1]:
            # A stored null or bare number where an object is expected is an unavailable fact.
            parent = parent.get(part) if isinstance(parent, dict) else None
        parent = parent if isinstance(parent, dict) else {}
        value = parent.get(parts[-1])
        reasons = parent.get("reasons")
        reason = (reasons.get(parts[-1]) if isinstance(reasons, dict) else None) or (
            f"{filename}:{field} is unavailable"
        )
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


def tool_outputs(home: Path, run_id: str) -> list[dict[str, Any]]:
    """Stored investigation-tool outputs for a run, oldest first; they live outside the run."""
    outputs = []
    for path in sorted((home / "diagnostics" / run_id).glob("*-*.json")):
        document = read_json(path)
        if document.get("run_id") != run_id or "tool" not in document:
            raise ValueError(f"{path} is not a tool output of run {run_id}")
        outputs.append(
            {
                "id": path.stem.rsplit("-", 1)[1],
                "file": str(path.relative_to(home)),
                **{key: document.get(key) for key in ("tool", "params", "recorded_at", "labels")},
                "facts": document.get("facts", []),
            }
        )
    return sorted(outputs, key=lambda item: (str(item["recorded_at"]), item["file"]))


def tool_fact(home: Path, run_id: str, metric: str, output_id: str | None) -> dict[str, Any]:
    """Quote one stored tool fact; several outputs of the tool need an explicit choice."""
    tool = TOOL_METRICS[metric][0]
    outputs = [item for item in tool_outputs(home, run_id) if item["tool"] == tool]
    known = [item["id"] for item in outputs]
    if output_id is not None:
        outputs = [item for item in outputs if item["id"] == output_id]
    if not outputs:
        raise SpineError(
            "NO_TOOL_OUTPUT",
            f"Run {run_id} has no stored {tool} output"
            + (f" with id {output_id!r}." if output_id is not None else "."),
            f"Run alpha tool {tool} {run_id} --json first.",
            known,
        )
    if len(outputs) > 1:
        raise SpineError(
            "AMBIGUOUS_TOOL_OUTPUT",
            f"Run {run_id} has {len(outputs)} stored {tool} outputs with different settings.",
            f"Run alpha results cite {run_id} {metric} --tool-output with one of the known ids.",
            known,
        )
    fact: dict[str, Any] = next(item for item in outputs[0]["facts"] if item["metric"] == metric)
    return fact
