"""Fixed, source-addressed facts read from stored JSON; no metric computation."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from alpha_cli.spine import reserve
from alpha_cli.spine.errors import SpineError
from alpha_cli.toolbox.registry import ALIASES, METRIC_OUTPUTS

# Public vocabulary: one plain-English meaning per metric.
METRICS = {
    "data_period": "First and last loaded bar.",
    "traded_period": "First and last stored equity point.",
    "verdict": "The stored validation verdict.",
    "oos_sharpe": "Sharpe of walk-forward out-of-sample returns.",
    "psr": "Probabilistic Sharpe of walk-forward out-of-sample returns.",
    "dsr": "The gauntlet's Sharpe probability; its stored trial_basis states the family count.",
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
    "inverted_sharpe": "Net Sharpe of the opposite-direction research control.",
    "inverted_sharpe_se": "Annualised IID-normal approximate standard error of the control Sharpe.",
    "inverted_total_return": "Net total return of the opposite-direction research control.",
    "inverted_trades": "Closed trades in the opposite-direction research control.",
    "inverted_label": "The recorded inverted-signal control reading.",
    "wfe": (
        "Median annualised OOS / IS return; a practitioner rule of thumb, not a statistical test."
    ),
    "wfe_fold_count": (
        "Recorded WFE fold count; a practitioner rule of thumb, not a statistical test."
    ),
    "resized_entries": "Cash entries reduced to affordable size at the open in the scored run.",
    "trades": "Number of closed full-sample trades.",
    "exposure": "Share of full-sample bars with a long position.",
    "top_1_profit_share": "Share of total closed profit from the largest trade.",
    "top_3_profit_share": "Top three trades vs total profit; above 1 if the rest lost.",
    "delay_base_sharpe": "Base returns-level surrogate Sharpe.",
    "delayed_sharpe": "Surrogate Sharpe with weights delayed one bar.",
    "total_trials": "Ledger entry number of this run: an audit sequence, not ideas tried.",
    "trial_dsr": "Deflated Sharpe using the idea family's trial count from the one ledger.",
    "family_trials": (
        "Trials counted for the deflated Sharpe: the idea's family in the one ledger, "
        "this run and its variants."
    ),
    "variants_evaluated": "Number of sensitivity re-runs evaluated.",
}
NOISE_METRICS = {
    "price_noise_median_sharpe": ("median_sharpe", "ratio"),
    "price_noise_p05_sharpe": ("p05_sharpe", "ratio"),
    "price_noise_p95_sharpe": ("p95_sharpe", "ratio"),
    "price_noise_sign_flip_share": ("sign_flip_share", "fraction"),
    "price_noise_median_trades": ("median_trades", "count"),
}
METRICS.update(
    {
        name: f"Price-noise control {field.replace('_', ' ')}."
        for name, (field, _) in NOISE_METRICS.items()
    }
)
METRICS.update({name: output.gloss for name, (_, output) in METRIC_OUTPUTS.items()})
# Unit kind of each metric: "ratio" (Sharpe-like, written 0.81 or 0.81x), "fraction" (written
# 0.344 or 34.4%), "count" (a whole number) or "other" (not numeric). A percent sign is only
# valid on a fraction.
METRIC_UNITS = {
    "data_period": "other",
    "traded_period": "other",
    "verdict": "other",
    "oos_sharpe": "ratio",
    "dsr": "fraction",
    "psr": "fraction",
    **{name: unit for name, (_, unit) in NOISE_METRICS.items()},
    "inverted_sharpe": "ratio",
    "inverted_sharpe_se": "ratio",
    "inverted_total_return": "fraction",
    "inverted_trades": "count",
    "inverted_label": "other",
    "wfe": "fraction",
    "wfe_fold_count": "count",
    "resized_entries": "count",
    "trades": "count",
    "exposure": "fraction",
    "top_1_profit_share": "fraction",
    "top_3_profit_share": "fraction",
    "delay_base_sharpe": "ratio",
    "delayed_sharpe": "ratio",
    "total_trials": "count",
    "family_trials": "count",
    "trial_dsr": "fraction",
    "variants_evaluated": "count",
    **{
        name: "fraction" if output.unit == "p_value" else output.unit
        for name, (_, output) in METRIC_OUTPUTS.items()
    },
    **{
        f"{prefix}_{metric}": kind
        for prefix in ("full_sample", "benchmark")
        for metric, kind in (
            ("total_return", "fraction"),
            ("cagr", "fraction"),
            ("sharpe", "ratio"),
            ("max_drawdown", "fraction"),
        )
    },
}
SETUP_METRICS = {
    "setup_occurrences": "Complete separate occurrences at the primary horizon.",
    "setup_mean_net_return": "Mean primary-horizon return after round-trip costs.",
    "setup_median_net_return": "Median primary-horizon return after round-trip costs.",
    "setup_hit_rate": "Share of complete primary-horizon returns above zero.",
    "setup_excess_over_drift": "Primary-horizon mean net return less matched asset drift.",
    "setup_random_date_p": "Exploratory pooled primary-horizon random-date tail probability.",
}
METRICS.update(SETUP_METRICS)
METRIC_UNITS.update({k: "count" if k == "setup_occurrences" else "fraction" for k in SETUP_METRICS})

TRADE_METRICS = {
    "setup_trades": ("Completed setup trades.", "count"),
    "setup_trade_mean_net_return": ("Mean completed trade return after costs.", "fraction"),
    "setup_trade_hit_rate": ("Share of completed net trade returns above zero.", "fraction"),
    "setup_trade_mean_bars_held": ("Mean bars held per completed trade.", "ratio"),
    "setup_trade_excess_over_drift": ("Mean net trade return less matched exit drift.", "fraction"),
    "setup_trade_random_date_p": (
        "Exploratory pooled random-date trade tail probability.",
        "fraction",
    ),
    "setup_trade_mean_r": ("Mean net return divided by initial stop risk fraction.", "ratio"),
}
METRICS.update({k: v[0] for k, v in TRADE_METRICS.items()})
METRIC_UNITS.update({k: v[1] for k, v in TRADE_METRICS.items()})

_CONTROL_BASIS = "opposite-direction full-sample engine run; research control only"
_WFE_BASIS = "annualised OOS / IS return; a practitioner rule of thumb, not a statistical test"
_FIELDS = {
    "data_period": ("manifest.json", "spine.data_period", "loaded bars"),
    "traded_period": ("manifest.json", "spine.traded_period", "stored out-of-sample equity curve"),
    "resized_entries": ("manifest.json", "resized_entries", "scored engine execution"),
    **{
        name: ("diagnostics.json", f"inverted_signal.{name}", _CONTROL_BASIS)
        for name in (
            "inverted_sharpe",
            "inverted_sharpe_se",
            "inverted_total_return",
            "inverted_trades",
        )
    },
    "inverted_label": ("diagnostics.json", "inverted_signal.label", _CONTROL_BASIS),
    "wfe": ("diagnostics.json", "walk_forward_efficiency.wfe", _WFE_BASIS),
    "wfe_fold_count": ("diagnostics.json", "walk_forward_efficiency.fold_count", _WFE_BASIS),
    "verdict": ("manifest.json", "verdict.overall", "walk-forward validation gauntlet"),
    "oos_sharpe": ("manifest.json", "oos_metrics.sharpe", "walk-forward out-of-sample returns"),
    "dsr": ("manifest.json", "dsr.dsr", "walk-forward validation gauntlet"),
    "psr": ("manifest.json", "dsr.psr", "walk-forward validation gauntlet"),
    **{
        name: ("diagnostics.json", f"price_noise.{field}", "price-noise full-sample net controls")
        for name, (field, _) in NOISE_METRICS.items()
    },
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
            ("trial_dsr", "trials.dsr", "one trial ledger, idea family at the time of the run"),
            (
                "family_trials",
                "trials.family.n_trials_used",
                "one trial ledger, idea family at the time of the run",
            ),
            ("variants_evaluated", "variants_evaluated", "full-sample sensitivity engine re-runs"),
        )
    },
}


# Periods are quoted only when recorded. Legacy runs keep their original metric names.
_FACT_PERIOD = {
    **dict.fromkeys(("data_period", "trades", "exposure"), "full_history"),
    **dict.fromkeys(
        ("traded_period", "oos_sharpe", "dsr", "psr", "verdict", "resized_entries"), "scored"
    ),
    **dict.fromkeys(
        (name for name in _FIELDS if name.startswith(("full_sample_", "benchmark_"))),
        "full_history",
    ),
}
for _period in ("tradable", "scored"):
    for _kind, _prefix, _metrics in (
        ("strategy", "", ("total_return", "cagr", "max_drawdown", "sharpe", "trades")),
        ("benchmark", "benchmark_", ("total_return", "cagr", "max_drawdown", "sharpe")),
    ):
        for _metric in _metrics:
            _name = f"{_period}_{_prefix}{_metric}"
            _field = f"spine.periods.{_period}.{_kind}.{_metric}"
            _FIELDS[_name] = ("manifest.json", _field, f"{_period} {_kind}")
            _FACT_PERIOD[_name] = _period
            METRICS[_name] = f"{_period.capitalize()} {_kind} {_metric.replace('_', ' ')}."
            METRIC_UNITS[_name] = METRIC_UNITS[
                "trades" if _metric == "trades" else f"benchmark_{_metric}"
            ]


# A positive drawdown magnitude in prose needs a word such as "drawdown of".
NEGATIVE_BY_CONVENTION = frozenset(name for name in _FIELDS if name.endswith("max_drawdown"))


def read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path.name} must contain an object")
    return value


def build_facts(rdir: Path) -> list[dict[str, Any]]:
    if read_json(rdir / "manifest.json").get("schema") in {
        "AlphaSetupStudyV1",
        "AlphaSetupTradeV1",
    }:
        facts: list[dict[str, Any]] = read_study(rdir)["facts"]
        return facts
    documents = {name: read_json(rdir / name) for name in ("manifest.json", "diagnostics.json")}
    spine = documents["manifest.json"].get("spine", {})
    labels = reserve.read_labels(documents["manifest.json"])
    periods = spine.get("periods", {})
    fields = _FIELDS.copy()
    if periods.get("full_history"):
        for metric, (filename, field, basis) in _FIELDS.items():
            group, _, key = field.partition(".")
            if (
                filename == "diagnostics.json"
                and group in {"full_sample", "benchmark"}
                and key != "exposure"
            ):
                leg = "strategy" if group == "full_sample" else "benchmark"
                fields[metric] = ("manifest.json", f"spine.periods.full_history.{leg}.{key}", basis)
    facts = [
        dict(
            metric=metric,
            value=None,
            run_id=rdir.name,
            basis="setup study primary horizon or completed setup trades",
            source="summary.json:facts",
            labels=labels,
            reason="this run is not a setup study or trade",
        )
        for metric in (*SETUP_METRICS, *TRADE_METRICS)
    ]
    for metric, (filename, field, basis) in fields.items():
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
        if metric == "family_trials" and value is None:
            reason = "recorded before family counts were used"
        period = periods.get(_FACT_PERIOD.get(metric))
        basis = basis if metric == "total_trials" else parent.get("basis", basis)
        if period:
            basis = f"{period['period'].replace('_', ' ')}, {basis}, {period['price_basis']}"
        facts.append(
            {
                "metric": metric,
                "value": value,
                "run_id": rdir.name,
                "basis": basis,
                "source": f"{filename}:{field}",
                **(
                    {
                        key: (period or {}).get(key)
                        for key in ("period", "first_ts", "last_ts", "price_basis")
                    }
                    if metric in _FACT_PERIOD
                    else {}
                ),
                "labels": list(dict.fromkeys([*labels, *parent.get("labels", [])])),
                "unit": METRIC_UNITS[metric],
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
    from alpha_cli.spine.ledger import read_trials_readonly

    committed = {
        row.get("tool_output")
        for row in read_trials_readonly(home)
        if row.get("run_id") == run_id and row.get("outcome") == "ok"
    }
    outputs = []
    for path in sorted((home / "diagnostics" / run_id).glob("*-*.json")):
        document = read_json(path)
        if document.get("run_id") != run_id or "tool" not in document:
            raise ValueError(f"{path} is not a tool output of run {run_id}")
        relative = str(path.relative_to(home))
        if "cache_key" in document and relative not in committed:
            continue  # Publication was interrupted before its durable outcome.
        outputs.append(
            {
                "id": path.stem.rsplit("-", 1)[1],
                "file": relative,
                **{
                    key: document.get(key)
                    for key in ("tool", "params", "recorded_at", "labels", "reading")
                },
                "facts": document.get("facts", []),
            }
        )
    return sorted(outputs, key=lambda item: (str(item["recorded_at"]), item["file"]))


def tool_fact(home: Path, run_id: str, metric: str, output_id: str | None) -> dict[str, Any]:
    """Quote one stored tool fact; several outputs of the tool need an explicit choice."""
    spec, output = METRIC_OUTPUTS[metric]
    tool = spec.id
    outputs = [
        item
        for item in tool_outputs(home, run_id)
        if ALIASES.get(item["tool"], item["tool"]) == tool
    ]
    known = [item["id"] for item in outputs]
    if output_id is not None:
        outputs = [item for item in outputs if item["id"] == output_id]
    if not outputs:
        raise SpineError(
            "NO_TOOL_OUTPUT",
            f"Run {run_id} has no stored {tool} output"
            + (f" with id {output_id!r}." if output_id is not None else "."),
            f"Run alpha tool run {tool} {run_id} --json first.",
            known,
        )
    if len(outputs) > 1:
        raise SpineError(
            "AMBIGUOUS_TOOL_OUTPUT",
            f"Run {run_id} has {len(outputs)} stored {tool} outputs with different settings.",
            f"Run alpha results cite {run_id} {metric} --tool-output with one of the known ids.",
            known,
        )
    selected = outputs[0]
    if output_id is None and "non-default-params" in selected["labels"]:
        raise SpineError(
            "TOOL_OUTPUT_REQUIRED",
            "A non-default setting needs an explicit output id.",
            f"Use --tool-output {selected['id']}.",
            known,
        )
    names = {output.legacy_metric, f"{tool}.{output.key}"}
    for fact in selected["facts"]:
        if fact["metric"] in names:
            result = {**fact, "metric": metric}
            if "non-default-params" in selected["labels"]:
                from alpha_cli.toolbox.store import history, settings_tried

                result["settings_count"] = len(settings_tried(history(home, run_id), tool))
            return result
    raise ValueError(f"Stored output {selected['file']} lacks {metric}")


def read_study(folder: Path) -> dict[str, Any]:
    """Verify completed sidecars before citing or repeating stored results."""
    manifest = json.loads((folder / "manifest.json").read_text())
    for name in (
        ("trades.parquet", "summary.json", "trades.png")
        if manifest["schema"] == "AlphaSetupTradeV1"
        else ("outcomes.parquet", "summary.json", "event-study.png")
    ):
        data, expected = (folder / name).read_bytes(), manifest["files"][name]
        if hashlib.sha256(data).hexdigest() != expected["sha256"] or len(data) != expected["size"]:
            raise ValueError(f"study artifact changed: {name}")
    result: dict[str, Any] = json.loads((folder / "summary.json").read_text())
    if manifest.get("study_rule_version") == "setup-study-1":
        result["labels"] = [*result["labels"], "older-cost-rule"]
        result["facts"] = [{**f, "labels": result["labels"]} for f in result["facts"]]
    return result


def add_study_trial_fact(home: Path, summary: dict[str, Any]) -> None:
    """Freeze the observed row count plus this trial for the existing draft checker."""
    from alpha_cli.spine.ledger import read_trials

    summary["total_trials"] = len(read_trials(home)) + 1
    summary["facts"].append(
        dict(
            metric="total_trials",
            value=summary["total_trials"],
            run_id=summary.get("trade_id", summary.get("study_id")),
            basis="ledger rows observed before publication plus this test; not a deflation count",
            source="summary.json:total_trials",
            labels=summary["labels"],
            reason=None,
        )
    )
