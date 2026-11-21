"""`alpha test <spec> --plan`: what a context gate would do on each asset, without the engine.

It reads bars and context (point-in-time, cut at the reserve), builds the gate and describes it.
It writes no ledger row, run folder, figure or lock file. Words are readings only.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from alpha_cli import _context_gate, _runner
from alpha_cli.spine import reserve, setup_context
from alpha_cli.spine.deflation import spine_test_key
from alpha_cli.spine.run import idea_id
from alpha_cli.spine.spec import IdeaSpec
from alpha_cli.spine.stores import annualisation, resolve_asset
from alpha_core import DataError
from alpha_data.timeframe import DAILY

REFUSAL = "Refused: the gated engine is not built yet; use --plan."


def sentence(span: dict[str, Any] | None, on: int, off: int, nulls: int, runs: int) -> str:
    """Plain words about stored data; a reading, never a verdict."""
    n = on + off + nulls
    if span is None:
        return (
            "No bar has a usable value for every condition series. "
            f"The gate is false on all {n} days."
        )
    return (
        f"The condition data covers {span['first'][:7]} to {span['last'][:7]} "
        f"(about {span['years']:.1f} years). The condition was true on {on} of {n} days, "
        f"in {runs} separate spells; false on {off} days; no value on {nulls} days "
        "(the gate is false there). The reading uses this span only."
    )


def _plan_asset(idea: IdeaSpec, asset: str, home: Path) -> dict[str, Any]:
    if idea.context is None or idea.when is None:
        raise DataError("the plan needs context and when")
    resolved = resolve_asset(asset, data_dir=home)
    labels: list[str] = []
    if reserve.held_back_count(resolved):
        labels.append(reserve.HELD_BACK)
    bars, _ = _runner.load_bars(resolved.symbol, data_dir=resolved.data_dir, as_of=reserve.CUTOFF)
    if not bars:
        raise DataError(f"{resolved.symbol}: no bars before the reserved period")
    dividends = _runner.load_dividends(
        resolved.symbol, data_dir=resolved.data_dir, as_of=reserve.CUTOFF
    )
    gate = _context_gate.build_gate(
        setup_context.frame_of(bars),
        context=idea.context,
        when=idea.when,
        calendar=setup_context.calendar_of(resolved),
        data_dir=home,
        symbol=resolved.symbol,
    )
    labels += setup_context.labels({"span": gate.span})
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
    nulls = sum(gate.null_reasons.values())
    return {
        "asset": asset,
        "symbol": resolved.symbol,
        "store": resolved.store_name,
        "error": None,
        "bars": len(gate.by_ts),
        "context_span": gate.span,
        "gate_true_bars": gate.true_bars,
        "gate_false_bars": gate.false_bars,
        "spells": gate.spells,
        "null_counts": gate.null_reasons,
        "labels": labels,
        "recipe": gate.attach.recipe,
        "context_fp": gate.fingerprint,
        "data_id": data_id,
        "test_key": list(key) if key is not None else None,
        "sentence": sentence(gate.span, gate.true_bars, gate.false_bars, nulls, gate.spells),
    }


def plan_idea(idea: IdeaSpec, *, home: Path) -> dict[str, Any]:
    """One plan per asset. An asset that cannot be read reports its error; others continue."""
    results: list[dict[str, Any]] = []
    for asset in idea.assets:
        try:
            results.append(_plan_asset(idea, asset, home))
        except DataError as exc:
            results.append({"asset": asset, "error": f"{type(exc).__name__}: {exc}"})
    return {
        "plan": True,
        "spec_sha256": idea.spec_sha256,
        "name": idea.name,
        "context": dict(idea.context or {}),
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
        span = r["context_span"] or {"first": None, "last": None, "years": 0.0}
        nulls = ", ".join(f"{k}: {n}" for k, n in r["null_counts"].items()) or "none"
        lines += [
            f"{r['asset']}: {r['bars']} bars; context span {span['first']} to {span['last']} "
            f"({span['years']} years)",
            f"  gate true on {r['gate_true_bars']} bars, false on {r['gate_false_bars']}; "
            f"{r['spells']} separate spells",
            f"  null gate bars by reason: {nulls}",
            f"  labels: {', '.join(r['labels']) or 'none'}",
            f"  test key: {hashlib.sha256(json.dumps(r['test_key']).encode()).hexdigest()[:16]}"
            f"  data id: {r['data_id']}  context fingerprint: {r['context_fp'][:16]}",
            r["sentence"],
        ]
    return lines
