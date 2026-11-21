"""`alpha test <spec> --plan`: what a context gate would do on each asset, without the engine.

It reads bars and context (point-in-time, cut at the reserve), builds the gate and describes it.
It writes no ledger row, run folder, figure or lock file. Words are readings only.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import polars as pl

from alpha_cli import _context_gate, _runner
from alpha_cli.spine import reserve
from alpha_cli.spine.deflation import spine_test_key
from alpha_cli.spine.run import idea_id
from alpha_cli.spine.spec import IdeaSpec
from alpha_cli.spine.stores import annualisation, resolve_asset
from alpha_core import Bar, DataError
from alpha_data.timeframe import DAILY

REFUSAL = "Refused: the gated engine is not built yet; use --plan."


def _frame(bars: list[Bar]) -> pl.DataFrame:
    return pl.DataFrame(
        {
            "ts": [b.ts for b in bars],
            "open": [b.open for b in bars],
            "high": [b.high for b in bars],
            "low": [b.low for b in bars],
            "close": [b.close for b in bars],
            "volume": [b.volume for b in bars],
        }
    )


def sentence(first: str | None, last: str | None, years: float, on: int, n: int, runs: int) -> str:
    if first is None or last is None:
        return (
            "No bar has a usable value for every condition series. "
            "There is no span to read, and the gate is false on every bar."
        )
    return (
        f"The condition data covers {first[:7]} to {last[:7]} (about {years:.1f} years). "
        f"The condition was true on {on} of {n} days, in {runs} separate spells. "
        "The reading uses this span only."
    )


def _plan_asset(idea: IdeaSpec, asset: str, home: Path) -> dict[str, Any]:
    if idea.context is None or idea.when is None:
        raise DataError("the plan needs context and when")
    resolved = resolve_asset(asset, data_dir=home)
    labels: list[str] = []
    held_back = reserve.held_back_count(resolved)
    if held_back:
        labels.append(reserve.HELD_BACK)
    bars, _ = _runner.load_bars(resolved.symbol, data_dir=resolved.data_dir, as_of=reserve.CUTOFF)
    dividends = _runner.load_dividends(
        resolved.symbol, data_dir=resolved.data_dir, as_of=reserve.CUTOFF
    )
    store = resolved.daily_store()
    calendar = _runner._calendar_for(resolved.symbol, store.read_provenance(resolved.symbol))
    gate = _context_gate.build_gate(
        _frame(bars),
        context=idea.context,
        when=idea.when,
        calendar=calendar,
        data_dir=home,
        cutoff=reserve.CUTOFF,
        symbol=resolved.symbol,
    )
    first, last = gate.first_value, gate.last_value
    in_span = [ts for ts in gate.by_ts if first is not None and ts >= first]
    on = sum(gate.by_ts[ts] for ts in in_span)
    runs = _context_gate.spells(gate.by_ts)
    years = (last - first).total_seconds() / (365.25 * 86400) if first and last else 0.0
    if _context_gate.short_history(gate):
        labels.append(_context_gate.SHORT_HISTORY)
    ppy, _ = annualisation([b.ts for b in bars], bar_size=DAILY)
    fingerprint = _runner.source_fingerprint(bars, dividends=dividends)
    data_id = idea_id(
        idea.spec_sha256, hashlib.sha256((fingerprint + gate.fingerprint).encode()).hexdigest()
    )
    key = spine_test_key(
        idea.spec_sha256,
        resolved.symbol,
        bars[0].ts.isoformat(),
        bars[-1].ts.isoformat(),
        ppy,
        store=resolved.store_name,
        data_id=data_id,
    )
    first_text = first.date().isoformat() if first else None
    last_text = last.date().isoformat() if last else None
    return {
        "asset": asset,
        "symbol": resolved.symbol,
        "store": resolved.store_name,
        "error": None,
        "bars": len(bars),
        "context_span": {"first": first_text, "last": last_text, "years": round(years, 2)},
        "span_bars": len(in_span),
        "gate_true_bars": on,
        "spells": runs,
        "null_counts": gate.null_reasons,
        "labels": labels,
        "recipe": gate.attach.recipe,
        "context_fp": gate.fingerprint,
        "data_id": data_id,
        "test_key": list(key) if key is not None else None,
        "sentence": sentence(first_text, last_text, years, on, len(in_span), runs),
    }


def plan_idea(idea: IdeaSpec, *, home: Path) -> dict[str, Any]:
    """One plan per asset. An asset that cannot be read reports its error; others continue."""
    results: list[dict[str, Any]] = []
    for asset in idea.assets:
        try:
            results.append(_plan_asset(idea, asset, home))
        except DataError as exc:
            results.append({"asset": asset, "error": f"{type(exc).__name__}: {exc}"})
    spec_key = json.dumps(idea.context, sort_keys=True)
    return {
        "plan": True,
        "spec_sha256": idea.spec_sha256,
        "name": idea.name,
        "context": json.loads(spec_key),
        "when": idea.when,
        "note": "A plan only. The engine did not run; no ledger row or run folder was written.",
        "results": results,
    }


def plan_lines(output: dict[str, Any]) -> list[str]:
    lines = [f"Plan for {output['name']}: {output['when']}  ({output['note']})"]
    for r in output["results"]:
        if r["error"]:
            lines.append(f"{r['asset']}: {r['error']}")
            continue
        span = r["context_span"]
        nulls = ", ".join(f"{k}: {n}" for k, n in r["null_counts"].items()) or "none"
        lines += [
            f"{r['asset']}: {r['bars']} bars; context span {span['first']} to {span['last']} "
            f"({span['years']} years)",
            f"  gate true on {r['gate_true_bars']} of {r['span_bars']} span bars; "
            f"{r['spells']} separate spells",
            f"  null gate bars by reason: {nulls}",
            f"  labels: {', '.join(r['labels']) or 'none'}",
            f"  test key: {hashlib.sha256(json.dumps(r['test_key']).encode()).hexdigest()[:16]}"
            f"  data id: {r['data_id']}  context fingerprint: {r['context_fp'][:16]}",
            r["sentence"],
        ]
    return lines
