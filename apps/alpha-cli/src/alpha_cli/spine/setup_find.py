"""Causal setup loading, clustering and bounded panel selection."""

from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Any

from alpha_cli.spine.contact_sheet import Panel
from alpha_cli.spine.errors import SpineError, setup_error
from alpha_core import DataError

CLUSTER_GAP_BARS = 10


def cluster_candidates(frame: Any, candidates: Any) -> Any:
    import polars as pl

    positions = {ts: i for i, ts in enumerate(frame["ts"])}
    previous, cluster, accepted = -CLUSTER_GAP_BARS - 1, 0, set()
    ids, first = [], []
    for row in candidates.iter_rows(named=True):
        pos = positions[row["event_ts"]]
        cluster += pos - previous > CLUSTER_GAP_BARS
        ids.append(cluster)
        first.append(row["status"] == "accepted" and cluster not in accepted)
        if row["status"] == "accepted":
            accepted.add(cluster)
        previous = pos
    return candidates.with_columns(
        pl.Series("cluster_id", ids, dtype=pl.Int64),
        pl.Series("cluster_first", first, dtype=pl.Boolean),
    )


def panel_window(frame: Any, row: dict[str, Any], context_bars: int, *, mode: str) -> Panel:
    positions = {ts: i for i, ts in enumerate(frame["ts"])}
    event = positions[row["event_ts"]]
    trigger = positions.get(row["trigger_ts"])
    end = trigger if mode == "accepted" or row["reason"] == "no-next-bar" else event
    if mode == "rejected" and row["reason"] == "no-trigger":
        end = min(event + row["within"], frame.height - 1)
    if mode not in {"accepted", "rejected"} or row["status"] != mode or end is None:
        raise ValueError("panel requires an accepted or rejected candidate with its boundary")
    if row["reason"] == "warm-up":
        raise ValueError("warm-up candidates are not drawn")
    start = max(0, event - context_bars)
    candles = tuple(
        (i + start - event, *bar)
        for i, bar in enumerate(
            frame.slice(start, end - start + 1).select("open", "high", "low", "close").iter_rows()
        )
    )
    title = f"{row['symbol']} #{row['candidate_id']} {row['event_ts']:%Y-%m-%d}"
    more = row.get("more_days", 0)
    if more:
        title += f" (+{more} more day{'s' if more > 1 else ''})"
    if mode == "rejected":
        title += f" rejected: {row['reason']}"
    return Panel(
        title,
        mode,
        candles,
        0,
        trigger - event if trigger is not None else None,
        end - event + 1 if mode == "accepted" else None,
        row["entry_price"] if mode == "accepted" else None,
        tuple((k[4:], v) for k, v in row.items() if k.startswith("ref_") and v is not None),
    )


def sample_rejected(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    counts = Counter(
        r["reason"] for r in rows if r["status"] == "rejected" and r["reason"] != "warm-up"
    )
    selected: list[dict[str, Any]] = []
    for reason in sorted(counts, key=lambda r: (-counts[r], r))[:4]:
        group = [r for r in rows if r["status"] == "rejected" and r["reason"] == reason]
        positions = (
            range(len(group))
            if len(group) <= 4
            else [round(i * (len(group) - 1) / 3) for i in range(4)]
        )
        selected.extend(group[i] for i in positions)
    return selected


def sheet_panels(
    spec: Any,
    frames: dict[str, Any],
    rows: list[dict[str, Any]],
    context_bars: int,
    max_sheets: int,
) -> tuple[list[tuple[str, list[Panel]]], dict[str, Any]]:
    accepted = sorted(
        (r for r in rows if r["cluster_first"]), key=lambda r: (r["event_ts"], r["symbol"])
    )
    days = Counter((r["symbol"], r["cluster_id"]) for r in rows if r["status"] == "accepted")
    drawn = accepted[: max_sheets * 16]
    rejected = sample_rejected(rows)
    batches = [
        (
            "accepted",
            drawn[i : i + 16],
            f"accepted {i + 1}–{min(i + 16, len(drawn))} of {len(accepted)}",
        )
        for i in range(0, len(drawn), 16)
    ]
    if rejected:
        batches.append(("rejected", rejected, "rejected, sampled by reason"))
    sheets = []
    for mode, group, title in batches:
        panels = [
            panel_window(
                frames[r["symbol"]],
                {
                    **r,
                    "within": spec.trigger.within if spec.trigger else 0,
                    "more_days": days[(r["symbol"], r["cluster_id"])] - 1
                    if mode == "accepted"
                    else 0,
                },
                context_bars,
                mode=mode,
            )
            for r in group
        ]
        sheets.append((f"{spec.setup.name}: {title}", panels))
    return sheets, dict(
        accepted=len(drawn),
        accepted_not_drawn=len(accepted) - len(drawn),
        rejected_sampled=dict(Counter(r["reason"] for r in rejected)),
    )


def _asset(spec: Any, asset: str, home: Path, result: dict[str, Any]) -> tuple[Any, Any]:
    import polars as pl

    from alpha_cli import _runner
    from alpha_cli.spine.stores import periods_per_year, resolve_asset
    from alpha_study.setup.evaluate import find_candidates

    resolved = resolve_asset(asset, data_dir=home)
    result.update(symbol=resolved.symbol, store=resolved.store_name, source=resolved.source)
    if resolved.defaulted:
        result["labels"].append("source-defaulted")
    bars, _ = _runner.load_bars(resolved.symbol, data_dir=resolved.data_dir)
    if periods_per_year([b.ts for b in bars]) not in {252, 365}:
        raise SpineError("NOT_DAILY_BARS", f"{asset}: bars are not daily", "Use stored daily bars.")
    result.update(
        n_bars=len(bars),
        first_bar=bars[0].ts.isoformat(),
        last_bar=bars[-1].ts.isoformat(),
        source_fingerprint=_runner.source_fingerprint(bars),
    )
    if (bars[-1].ts - bars[0].ts).total_seconds() < 3 * 365.25 * 86400:
        result["labels"].append("short-history")
    schema: dict[str, Any] = {
        "ts": pl.Datetime("us", "UTC"),
        **dict.fromkeys(("open", "high", "low", "close", "volume"), pl.Float64),
    }
    frame = pl.DataFrame({k: [getattr(b, k) for b in bars] for k in schema}, schema=schema)
    candidates = cluster_candidates(frame, find_candidates(spec, frame, symbol=asset))
    return frame, candidates.with_columns(
        pl.lit(resolved.symbol).alias("resolved_symbol"),
        pl.lit(resolved.store_name).alias("store"),
        pl.lit(resolved.source).alias("source"),
    )


def prepare_assets(spec: Any, home: Path, assets: list[str] | None) -> tuple[Any, Any, Any]:
    from alpha_cli.spine.stores import _stores

    results, candidates, frames = [], [], {}
    for asset in spec.setup.assets:
        if assets and asset not in assets:
            continue
        result = dict.fromkeys(
            (
                "symbol",
                "store",
                "source",
                "n_bars",
                "first_bar",
                "last_bar",
                "source_fingerprint",
                "error",
            )
        )
        result.update(asset=asset, labels=[])
        try:
            frame, rows = _asset(spec, asset, home, result)
            frames[asset] = frame
            candidates.append(rows)
        except (DataError, ValueError, OSError) as exc:
            result["error"] = setup_error(exc, list(_stores(home))).payload
        results.append(result)
    return results, candidates, frames


def _counts(candidates: Any) -> dict[str, Any]:
    from alpha_study.setup.evaluate import summarise

    summary = summarise(candidates)
    return dict(
        events=candidates.height,
        accepted=summary["accepted"],
        pending=summary["pending"],
        rejected=sum(summary["rejected"].values()),
        rejected_by_reason=summary["rejected"],
        clusters=candidates["cluster_id"].n_unique(),
        accepted_clusters=sum(candidates["cluster_first"]),
        first_event=summary["first_event"],
        last_event=summary["last_event"],
    )


def load_spec(path: Path, assets: list[str] | None) -> Any:
    from alpha_study.setup.spec import SetupSpec

    try:
        spec = SetupSpec.load(path)
    except (DataError, ValueError, OSError) as exc:
        raise SpineError(
            "SPEC_INVALID", str(exc), "Fix the spec file and run alpha setup find again."
        ) from exc
    for asset in assets or []:
        if asset not in spec.setup.assets:
            raise SpineError(
                "ASSET_NOT_IN_SPEC",
                asset,
                "Choose an asset verbatim from setup.assets.",
                list(spec.setup.assets),
            )
    return spec
