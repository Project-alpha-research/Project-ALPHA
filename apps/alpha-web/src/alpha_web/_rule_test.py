"""What a rule test (``alpha test``) recorded, projected for the report screen.

A rule test is a run whose manifest carries a ``spine`` key. Everything here is read from the
run's own ``manifest.json`` and ``diagnostics.json``; no number is computed or re-derived. A part
the stored file does not carry is ``None``.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

MAX_DIAGNOSTICS_BYTES = 2 * 1024 * 1024
_METRICS = ("total_return", "cagr", "sharpe", "max_drawdown")


def _map(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _rows(value: Any) -> list[Mapping[str, Any]]:
    return [row for row in value if isinstance(row, Mapping)] if isinstance(value, list) else []


def _number(value: Any) -> float | None:
    return value if isinstance(value, int | float) and not isinstance(value, bool) else None


def _count(value: Any) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _text(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None


def _reasons(value: Any) -> dict[str, str]:
    return {str(key): str(reason) for key, reason in _map(value).items()}


def spine_of(manifest: Mapping[str, Any]) -> Mapping[str, Any] | None:
    """The manifest's ``spine`` block; ``None`` for every run that is not a rule test."""
    spine = manifest.get("spine")
    return spine if isinstance(spine, Mapping) else None


def labels_of(manifest: Mapping[str, Any]) -> list[str] | None:
    spine = spine_of(manifest)
    if spine is None:
        return None
    labels = spine.get("labels")
    return [str(label) for label in labels] if isinstance(labels, list) else []


def rule_sentence(
    kind: str | None, params: Mapping[str, int], metadata: Mapping[str, Any]
) -> str | None:
    """The rule as the strategy code states it, in one plain sentence; ``None`` if unknown."""
    unit = "day" if metadata.get("periods_per_year") in (252, 365) else "bar"
    fast, slow, window = params.get("fast"), params.get("slow"), params.get("window")
    lookback, skip = params.get("lookback"), params.get("skip", 0)
    if kind == "ma_cross" and fast and slow:
        rule = f"Long while the {fast}-{unit} average is above the {slow}-{unit} average"
    elif kind == "breakout" and window:
        rule = f"Long after a close above the highest high of the prior {window} {unit}s"
    elif kind == "tsmom" and lookback:
        recent = f"the close {skip} {unit}s ago" if skip else "the latest close"
        rule = f"Long while {recent} is above the close {skip + lookback} {unit}s ago"
    else:
        return None
    parts = [f"{rule}, otherwise flat", "decide at the close, fill at the next open"]
    if metadata.get("sizing") == "all_in" and metadata.get("max_leverage") == 1.0:
        parts.append("all capital in, no leverage")
    return "; ".join(parts)


def _performance(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, Mapping):
        return None
    return {
        "basis": _text(value.get("basis")),
        **{metric: _number(value.get(metric)) for metric in _METRICS},
        "reasons": _reasons(value.get("reasons")),
    }


def _with(value: Any, **extra: Any) -> dict[str, Any] | None:
    base = _performance(value)
    return None if base is None else {**base, **extra}


def _macro(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, Mapping):
        return None
    return {
        "available": value.get("available") is True,
        **{key: _text(value.get(key)) for key in ("reason", "basis", "start", "trough", "as_of")},
        "series": [
            {
                "series_id": str(row.get("series_id")),
                "start_value": _number(row.get("start_value")),
                "trough_value": _number(row.get("trough_value")),
                "change": _number(row.get("change")),
                "reason": _text(row.get("reason")),
            }
            for row in _rows(value.get("series"))
        ],
    }


def _section(value: Any, numbers: tuple[str, ...], counts: tuple[str, ...] = ()) -> Any:
    if not isinstance(value, Mapping):
        return None
    return {
        "basis": _text(value.get("basis")),
        **{key: _number(value.get(key)) for key in numbers},
        **{key: _count(value.get(key)) for key in counts},
        "reasons": _reasons(value.get("reasons")),
    }


def _diagnostics(document: Mapping[str, Any]) -> dict[str, Any]:
    full, benchmark = document.get("full_sample"), document.get("benchmark")
    difference = _map(benchmark).get("strategy_minus_benchmark")
    by_year, sensitivity = document.get("by_year"), document.get("sensitivity")
    episodes = _rows(_map(document.get("drawdowns")).get("episodes"))
    worst = episodes[0] if episodes else None
    return {
        "full_sample": _with(
            full,
            trades=_count(_map(full).get("trades")),
            exposure=_number(_map(full).get("exposure")),
        ),
        "benchmark": _with(
            benchmark,
            strategy_minus_benchmark={
                **{metric: _number(difference.get(metric)) for metric in _METRICS},
                "reasons": _reasons(difference.get("reasons")),
            }
            if isinstance(difference, Mapping)
            else None,
        ),
        "flags": [
            {"flag": str(row.get("flag")), "detail": str(row.get("detail"))}
            for row in _rows(document.get("flags"))
        ],
        "audit": [
            {
                "check": str(row.get("check")),
                "status": str(row.get("status")),
                "detail": str(row.get("detail")),
            }
            for row in _rows(document.get("audit"))
        ],
        "by_year": {
            "basis": _text(by_year.get("basis")),
            "strategy_positive_years": _count(by_year.get("strategy_positive_years")),
            "benchmark_positive_years": _count(by_year.get("benchmark_positive_years")),
            "years": [
                {
                    "year": row["year"],
                    "strategy_return": _number(row.get("strategy_return")),
                    "benchmark_return": _number(row.get("benchmark_return")),
                }
                for row in _rows(by_year.get("years"))
                if _count(row.get("year")) is not None
            ],
        }
        if isinstance(by_year, Mapping)
        else None,
        "concentration": _section(document.get("concentration"), ("top_1", "top_3")),
        "sensitivity": {
            "basis": _text(sensitivity.get("basis")),
            "variants": [
                _with(row, name=str(row.get("name")), kind=_text(row.get("kind")))
                for row in _rows(sensitivity.get("variants"))
            ],
        }
        if isinstance(sensitivity, Mapping)
        else None,
        "delay": _section(document.get("delay"), ("base_sharpe", "delayed_sharpe")),
        "trials": _section(document.get("trials"), ("dsr",), ("total_trials", "available_sharpes")),
        "worst_drawdown": {
            **{key: _text(worst.get(key)) for key in ("start", "trough", "recovery")},
            **{
                key: _number(worst.get(key))
                for key in ("depth", "benchmark_return", "share_explained")
            },
            "reasons": _reasons(worst.get("reasons")),
        }
        if worst is not None
        else None,
        "macro_window": _macro(document.get("macro_window")),
        "variants_evaluated": _count(document.get("variants_evaluated")),
    }


def _stored_diagnostics(rdir: Path) -> tuple[dict[str, Any] | None, str | None]:
    path = rdir / "diagnostics.json"
    if not path.exists():
        return None, "this run recorded no diagnostics.json"
    try:
        if path.stat().st_size > MAX_DIAGNOSTICS_BYTES:
            return None, "diagnostics.json is larger than the report reads"
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None, "diagnostics.json could not be read"
    if not isinstance(document, dict):
        return None, "diagnostics.json is not an object"
    return _diagnostics(document), None


def rule_test(manifest: Mapping[str, Any], rdir: Path) -> dict[str, Any] | None:
    """The run's rule-test block for ``RunDetail``; ``None`` when the manifest has no ``spine``."""
    spine = spine_of(manifest)
    if spine is None:
        return None
    metadata = _map(manifest.get("metadata"))
    rule = _map(spine.get("rule"))
    params = {
        str(key): value
        for key, value in rule.items()
        if key != "kind" and _count(value) is not None
    }
    diagnostics, reason = _stored_diagnostics(rdir)
    trials = (diagnostics or {}).get("trials") or {}
    return {
        "name": _text(spine.get("name")),
        "idea": _text(spine.get("idea")),
        "rule_kind": _text(rule.get("kind")),
        "rule_params": params,
        "rule_sentence": rule_sentence(_text(rule.get("kind")), params, metadata),
        "symbol": _text(metadata.get("symbol")),
        "source": _text(manifest.get("source")),
        "store": _text(spine.get("store")),
        "labels": labels_of(manifest) or [],
        "test_id": _text(spine.get("test_id")),
        "first_ts": _text(metadata.get("first_ts")),
        "last_ts": _text(metadata.get("last_ts")),
        "n_bars": _count(metadata.get("n_bars")),
        "fee_bps": _number(metadata.get("fee_bps")),
        "slippage_bps": _number(metadata.get("slippage_bps")),
        "total_trials": trials.get("total_trials"),
        "diagnostics": diagnostics,
        "diagnostics_reason": reason,
    }
