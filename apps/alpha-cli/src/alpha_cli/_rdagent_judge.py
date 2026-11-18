"""The RD-Agent judge core: frozen-panel constants and checks, screen, ALPHA replay, spread check.

Split out of `rdagent_factor_eval` unchanged; that module re-exports these names."""

from __future__ import annotations

import hashlib
import io
import json
import math
import os
import re
import subprocess
from dataclasses import asdict
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from typing import Any

import numpy as np
import polars as pl

from alpha_backtest.portfolio_replay import run_weight_replay
from alpha_cli import _rdagent_identity as identity
from alpha_cli import _rdagent_membership as membership
from alpha_cli import _rdagent_universe as universes
from alpha_cli._rdagent_clocks import (
    CLOCKS as CLOCKS,
)
from alpha_cli._rdagent_clocks import (
    SWING_CLOCKS,
    clock_samples,
    clock_targets,
)
from alpha_cli._rdagent_stats import autocorrelation_effective_size, screen_statistics
from alpha_cli.crypto_bulk_store import configured_crypto_bulk_store
from alpha_core import Bar, DataError
from alpha_data.context.daily_funding import daily_funding_with_sources
from alpha_research.panel import cross_sectional_ic
from alpha_validation.bootstrap import block_bootstrap_ci

RESERVED_START = "2024-01-01"
PANEL_END = "2023-12-31"
EXPLORATION = ("2021-01-01", "2023-12-24")
CUTS = (
    ("2020-12-31",)
    + tuple(
        f"{year}-{day}"
        for year in (2021, 2022, 2023)
        for day in ("03-31", "06-30", "09-30", "12-31")
        if f"{year}-{day}" <= "2023-09-30"
    )
    + ("2023-12-24",)
)
FEE_BPS, SLIPPAGE_BPS = 10.0, 6.0
TOP_FRACTION, ANNUAL_DAYS, MIN_NAMES = 1 / 3, 365, 5
Q_THRESHOLD, BOOTSTRAP_RESAMPLES = 0.10, 2000
LABEL = "exploratory, not admitted, not yet confirmed"
SPREAD_REASON = "top-third-does-not-beat-bottom-third"
SURVIVORSHIP = (
    "15 coins chosen in 2026-11 from today's survivors; coins that were delisted or collapsed "
    "(for example LUNA, FTT) are absent, which biases results upward"
)
AUTHORITY = dict.fromkeys(("admitted", "evidence", "approval", "promotion"), False)
WINDOWS = {
    "history": ["2017-08-17", "2020-12-31"],
    "exploration": list(EXPLORATION),
    "panel_end": PANEL_END,
    "reserved_start": RESERVED_START,
}
CONFIG: dict[str, Any] = {
    "windows": WINDOWS,
    "clocks": CLOCKS,
    "swing_clocks": SWING_CLOCKS,
    "clock_phase": EXPLORATION[0],
    "forward_windows": "non-overlapping; open(d+1+h) / open(d+1) - 1",
    "residual_trades": (
        "Drifted holdings between rebalances; fill-price and fee differences cause small "
        "residual trades, executed and charged."
    ),
    "cuts": CUTS,
    "fee_bps": FEE_BPS,
    "slippage_bps": SLIPPAGE_BPS,
    "top_fraction": TOP_FRACTION,
    "annual_days": ANNUAL_DAYS,
    "min_names": MIN_NAMES,
    "q_threshold": Q_THRESHOLD,
    "bootstrap_resamples": BOOTSTRAP_RESAMPLES,
    "spread_check": (
        "ADR-0055: a screened clock passes only if the mean over its decision days of the top "
        "third's minus the bottom third's forward return (before costs, claimed direction) is "
        "positive under both tie orders; otherwise it is SPREAD_FAIL "
        f"({SPREAD_REASON}) whatever its replay shows. The bar is the sign only, not "
        "significance; the t-statistic and interval are reported, not applied. A spread failure "
        "is still replayed and counted as a trial, so the Deflated Sharpe's trials are unchanged"
    ),
}
TRIAL_SCHEMA = "AlphaRdagentFactorTrialV3"
LEDGER_SCHEMAS = {
    "AlphaRdagentFactorTrialV1",
    "AlphaRdagentFactorTrialV2",
    TRIAL_SCHEMA,
    "AlphaRuleTrialV1",
}
LOOP_UNIVERSE = (
    "ADAUSDT",
    "ATOMUSDT",
    "AVAXUSDT",
    "BCHUSDT",
    "BNBUSDT",
    "BTCUSDT",
    "DOGEUSDT",
    "DOTUSDT",
    "ETHUSDT",
    "LINKUSDT",
    "LTCUSDT",
    "SOLUSDT",
    "TRXUSDT",
    "XLMUSDT",
    "XRPUSDT",
)
STATUSES = frozenset(
    {
        "FAILED",
        "LOOKAHEAD",
        "UNSTABLE",
        "DEGENERATE",
        "ERROR",
        "SCREEN_FAIL",
        "SPREAD_FAIL",
        "REPLAY_FAIL",
        "CANDIDATE",
        "DEFLATION_FAIL",
        "FAST_ONLY",
        "REPEAT",
        "IMPORTED",
    }
)


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def plain_name(name: str) -> str:
    glossary = {
        "vol": "volatility",
        "ret": "return",
        "vwap": "volume-weighted average price",
        "ic": "information coefficient",
        "xs": "cross-sectional",
        "ma": "moving average",
        "sma": "moving average",
        "std": "standard deviation",
        "atr": "average true range",
        "pct": "percent",
        "zscore": "z-score",
    }
    tokens = name.lower().split("_")
    words = [glossary.get(token, token) for token in tokens]
    if re.fullmatch(r"[0-9]+d", tokens[-1]):
        words[-1] = f"over {tokens[-1][:-1]} days"
    return " ".join(words).capitalize()


def canonical(value: Any) -> bytes:
    # RD-Agent's Series contract explicitly represents unreplayed metrics as NaN.
    return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode()


def exclusive(path: Path, data: bytes) -> None:
    with path.open("xb") as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())


def outside_git(path: Path) -> None:
    if not path.is_absolute():
        raise DataError("trial ledger must be absolute and outside every git work tree")
    if not path.parent.is_dir():
        raise DataError("trial ledger parent must exist")
    result = subprocess.run(
        ["git", "-C", str(path.parent.resolve()), "rev-parse", "--is-inside-work-tree"],
        env={"PATH": "/usr/bin:/bin", "LANG": "C"},
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode == 0 and result.stdout.strip() == "true":
        raise DataError("trial ledger must be outside every git work tree")
    if result.returncode not in (0, 128):
        raise DataError("cannot determine trial ledger git location")


RESERVED_DAY = date.fromisoformat(RESERVED_START)
PRICE_COLUMNS = ("open", "high", "low", "close")
PANEL_COLUMNS = ("date", "instrument", *PRICE_COLUMNS, "volume", "quote_volume")


def _days(frame: pl.DataFrame, column: str = "date") -> pl.Series:
    """The column as calendar days; a timestamp must be exactly UTC midnight."""
    values = frame[column]
    if values.dtype == pl.Date:
        days = values
    elif isinstance(values.dtype, pl.Datetime):
        stamps = (
            values.dt.replace_time_zone("UTC")
            if values.dtype.time_zone is None
            else values.dt.convert_time_zone("UTC")
        )
        if (stamps != stamps.dt.truncate("1d")).any():
            raise DataError("panel dates must be UTC-midnight days")
        days = stamps.dt.date()
    else:
        raise DataError(f"{column} must be a date or timestamp column")
    if days.null_count():
        raise DataError("panel dates must be UTC-midnight days")
    return days.alias(column)


def validate_panel(frame: pl.DataFrame) -> pl.DataFrame:
    if frame.is_empty():
        raise DataError("empty panel")
    frame = frame.with_columns(_days(frame))
    if (frame["date"] >= RESERVED_DAY).any():
        raise DataError("panel reaches reserved window")
    if frame.select(["date", "instrument"]).is_duplicated().any():
        raise DataError("overlapping instrument-day artifacts")
    gaps = frame.group_by("instrument").agg(
        pl.col("date").diff().drop_nulls().dt.total_days().alias("step")
    )
    for name, steps in gaps.iter_rows():
        if any(step <= 0 for step in steps):
            raise DataError(f"disordered daily bars for {name}")
    prices = frame.select(PRICE_COLUMNS).to_numpy().astype(float)
    volumes = frame.select(["volume", "quote_volume"]).to_numpy().astype(float)
    if (
        not np.isfinite(prices).all()
        or (prices <= 0).any()
        or not np.isfinite(volumes).all()
        or (volumes < 0).any()
    ):
        raise DataError("invalid OHLC or volumes")
    low, high, open_, close = (frame[c].to_numpy() for c in ("low", "high", "open", "close"))
    if (low > np.minimum(open_, close)).any() or (high < np.maximum(open_, close)).any():
        raise DataError("inconsistent OHLC")
    return frame.sort(["date", "instrument"])


def _alpaca_viability(data_dir: Path, spec: dict[str, Any]) -> None:
    """Read-only count of a stock universe's names in the Alpaca store; refuses too few."""
    import tomllib

    registry = data_dir / "stores.toml"
    try:
        stores = tomllib.loads(registry.read_text()) if registry.exists() else {}
    except (OSError, ValueError) as error:
        raise DataError(f"unreadable stores.toml: {error}") from error
    if not isinstance(stores.get("alpaca"), str):
        raise DataError("no 'alpaca' store is registered in stores.toml")
    bars = (data_dir / stores["alpaca"]).resolve() / "store" / "bars"
    wanted = spec["instruments"]
    present = sorted(
        p.stem for p in bars.glob("*.parquet") if wanted == "all-in-store" or p.stem in wanted
    )
    if len(present) < spec["min_universe"]:
        raise DataError(
            f"universe {spec['name']!r}: the Alpaca store has {len(present)} of its names "
            f"({', '.join(present) or 'none'}); cross-sectional thirds need at least "
            f"{spec['min_universe']}"
        )


FUNDING_EXCLUSIONS = {"COCOSUSDT": "perp identity across the 2023 rename is unresolved"}
FUNDING_COLUMNS = ("funding_sum", "funding_last", "funding_count")


def _panel_funding(
    funding_dir: Path, raw_panel: pl.DataFrame, breaks: list[dict[str, Any]]
) -> tuple[pl.DataFrame, dict[str, str]]:
    names = sorted(
        name
        for name in raw_panel["instrument"].unique()
        if name not in FUNDING_EXCLUSIONS and not name.startswith("1000")
    )
    daily, sources = daily_funding_with_sources(
        funding_dir, names, min(raw_panel["date"]), max(raw_panel["date"])
    )
    daily = daily.rename({"symbol": "instrument"})
    for entry in breaks:
        if entry["reason"] == "ticker_reused":
            daily = daily.filter(
                ~(
                    (pl.col("instrument") == entry["instrument"])
                    & (pl.col("date") >= date.fromisoformat(entry["new_from"]))
                )
            )
    # Join on the exchange ticker first. Relabel carries the attached values along with bars.
    attached = raw_panel.join(daily, on=["date", "instrument"], how="left")
    labelled, _ = identity.relabel(attached, breaks)
    return (
        labelled.filter(pl.col("funding_count").is_not_null())
        .select("date", "instrument", *FUNDING_COLUMNS)
        .sort("date", "instrument"),
        sources,
    )


def _funding_receipt(
    out: Path, funding: pl.DataFrame, panel: pl.DataFrame, sources: dict[str, str]
) -> dict[str, Any]:
    buffer = io.BytesIO()
    funding.write_parquet(buffer)
    payload = buffer.getvalue()
    exclusive(out / "funding.parquet", payload)
    coverage = {
        str(year): funding.filter(pl.col("date").dt.year() == year).height
        / panel.filter(pl.col("date").dt.year() == year).height
        for year in sorted(panel["date"].dt.year().unique())
    }
    return {
        "sha256": sha(payload),
        "source_table_hashes": sources,
        "names": sorted(funding["instrument"].unique()),
        "coverage_by_year": coverage,
    }


def freeze(
    data_dir: Path, out: Path, universe: Path | None = None, funding_dir: Path | None = None
) -> dict[str, Any]:
    spec = universes.load(universe)
    data_dir = Path(spec.get("data_dir", data_dir))
    if "data_dir" in spec and not data_dir.is_dir():
        raise DataError(f"universe data_dir {data_dir} is not an existing directory")
    if spec["source"] == "alpaca-us-equities":
        _alpaca_viability(data_dir, spec)
    universes.evaluable(spec)
    if spec["source"] != "binance-spot":
        raise DataError(f"universe source {spec['source']!r} has no panel reader yet")
    store = configured_crypto_bulk_store(data_dir)
    frames: list[pl.DataFrame] = []
    manifests, hashes = [], set()
    selector = {
        "family": "market_bars",
        "venue": "binance",
        "market_type": "spot",
        "frequency": "1d",
        "timestamp_convention": "interval_start_utc",
    }
    for path in sorted((data_dir / "crypto/manifests").glob("*.json")):
        manifest = json.loads(path.read_bytes())
        if manifest.get("artifact_kind") != "normalized" or any(
            manifest.get("dataset", {}).get(k) != v for k, v in selector.items()
        ):
            continue
        verified, payload = store.read_verified_normalized(path.stem, max_bytes=32 * 1024 * 1024)
        quality: Any = verified["quality"]
        dataset: Any = verified["dataset"]
        # Missing days inside a month are the gaps the panel receipt records (decision 1), so a
        # month whose only warning is its cadence gap is accepted; anything else still fails.
        gap_only = quality["state"] == "warning" and list(quality["warnings"]) == ["cadence_gap"]
        if (quality["state"] != "qualified" and not gap_only) or quality["failures"]:
            raise DataError(f"unqualified normalized artifact: {path.stem}")
        digest = str(verified["artifact_sha256"])
        if (
            spec["instruments"] != "all-in-store"
            and dataset["instrument"] not in spec["instruments"]
        ):
            continue
        manifests.append({"manifest_id": path.stem, "artifact_sha256": digest})
        capture = (str(dataset["instrument"]), digest)
        if capture in hashes:
            continue
        hashes.add(capture)
        raw = pl.read_parquet(io.BytesIO(payload))
        days = _days(raw, "open_time")
        # Validate order within each artifact before merging chronological captures.
        if not days.is_sorted():
            raise DataError("disordered artifact")
        frame = (
            raw.with_columns(
                days.alias("date"), pl.lit(str(dataset["instrument"])).alias("instrument")
            )
            .rename({"base_volume": "volume"})
            .filter(pl.col("date") < RESERVED_DAY)
            .select(PANEL_COLUMNS)
            .with_columns(pl.col(PANEL_COLUMNS[2:]).cast(pl.Float64))
        )
        frames.append(frame)
    if not frames:
        raise DataError("no qualified Binance spot daily bars")
    panel = validate_panel(pl.concat(frames).sort(["date", "instrument"]))
    if universe is not None:
        present = panel["instrument"].n_unique()
        missing = (
            sorted(set(spec["instruments"]) - set(panel["instrument"].to_list()))
            if spec["instruments"] != "all-in-store"
            else []
        )
        if missing or present < spec["min_universe"]:
            raise DataError(
                f"universe {spec['name']!r}: the store has {present} of its instruments"
                + (f" (missing {', '.join(missing)})" if missing else "")
                + f"; cross-sectional thirds need at least {spec['min_universe']}"
            )
    funding = (
        _panel_funding(funding_dir, panel, spec.get("identity_breaks", []))
        if funding_dir is not None
        else None
    )
    panel, breaks = identity.relabel(panel, spec.get("identity_breaks", []))
    panel = validate_panel(panel)
    if universe is not None and panel["instrument"].n_unique() < spec["min_universe"]:
        raise DataError(
            f"universe after identity joins needs at least {spec['min_universe']} instruments"
        )
    identity.check_jumps(panel)
    summary = membership.panel_summary(panel)
    summary.update(universes.disclosure(spec, summary))
    out.mkdir(parents=True, exist_ok=False)
    buffer = io.BytesIO()
    panel.write_parquet(buffer)
    payload = buffer.getvalue()
    exclusive(out / "panel.parquet", payload)
    receipt = {
        "schema": "AlphaRdagentFactorPanelV1",
        "manifests": manifests,
        "identity_breaks": [b for b in breaks if b["reason"] == "ticker_reused"],
        "identity_rescales": [b for b in breaks if b["reason"] == "redenominated"],
        "identity_joins": [b for b in breaks if b["reason"] == "renamed"],
        "identity_jump_policy": identity.JUMP_POLICY,
        **summary,
        "rows": panel.height,
        "panel_sha256": sha(payload),
    }
    if universe is not None:
        receipt["universe_sha256"] = sha(canonical(spec))
        exclusive(out / "universe.json", canonical(spec))
    if funding is not None:
        receipt["funding"] = _funding_receipt(out, funding[0], panel, funding[1])
    exclusive(out / "panel-receipt.json", canonical(receipt))
    return receipt


def matrix(frame: pl.DataFrame, value: str, days: list[date], symbols: list[str]) -> np.ndarray:
    """Dense days x symbols float matrix of one column; absent cells are NaN."""
    wide = frame.select(["date", "instrument", value]).pivot(
        on="instrument", index="date", values=value
    )
    grid = pl.DataFrame({"date": days}, schema={"date": pl.Date}).join(wide, on="date", how="left")
    columns = [
        grid[name].cast(pl.Float64).fill_null(float("nan")).to_numpy()
        if name in grid.columns
        else np.full(len(days), np.nan)
        for name in symbols
    ]
    return np.column_stack(columns).astype(float)


LINEAGE_CONVENTION = "pooled-xs-rank-ols-v1"


def _lineage_ranks(values: np.ndarray) -> np.ndarray:
    """Average tied ranks, scaled to [-0.5, 0.5] within each finite cross-section."""
    ranked = np.full(values.shape, np.nan)
    for index, row in enumerate(values):
        finite = np.isfinite(row)
        count = int(finite.sum())
        if count < 2:
            ranked[index, finite] = 0.0
            continue
        _, inverse, counts = np.unique(row[finite], return_inverse=True, return_counts=True)
        average = np.cumsum(counts) - (counts + 1) / 2
        ranked[index, finite] = average[inverse] / (count - 1) - 0.5
    return ranked


def lineage(
    signal: np.ndarray,
    history: list[dict[str, Any]],
    panel_hash: str,
    days: list[date],
    symbols: list[str],
) -> dict[str, Any]:
    """Diagnostic pooled rank OLS against earlier hash-bound twin-check values only.

    With no intercept, adjusted R² is 1 - (SSE / (n - rank(X))) / (y'y / n).
    Missing earlier archives make the top-correlated selection unknowable, not a proxy fit.
    """
    if signal.shape != (len(days), len(symbols)) or any(d >= RESERVED_DAY for d in days):
        raise DataError("lineage requires a matching pre-reserved dated matrix")
    result: dict[str, Any] = {
        "lineage_r2": None,
        "lineage_regressors": 0,
        "lineage_convention": LINEAGE_CONVENTION,
        "lineage_reason": None,
        "composite_suspect": None,
    }
    target = _lineage_ranks(signal)
    finite = np.isfinite(target)
    y = target[finite]
    if y.size < 1000:
        return {**result, "lineage_reason": "fewer than 1,000 usable target rows"}
    total = float(y @ y)
    if total == 0:
        return {**result, "lineage_reason": "target cross-sectional ranks have no variation"}
    regressors: list[tuple[float, np.ndarray]] = []
    unavailable = 0
    for row in history:
        # These outcomes store no values of their own (look-ahead code is never written).
        if row["status"] in {"REPEAT", "FAILED", "UNSTABLE", "IMPORTED", "LOOKAHEAD"}:
            continue
        if row["panel_sha256"] != panel_hash:
            continue
        stored = row.get("factor_values", {})
        path = Path(stored["path"]) if stored else None
        if path is None or not path.exists():
            unavailable += 1
            continue
        raw = path.read_bytes()
        if sha(raw) != stored["sha256"]:
            raise DataError("earlier factor values differ from their recorded hash")
        values = pl.read_parquet(io.BytesIO(raw))
        if row["name"] not in values.columns:
            # The verified file holds no value for it: an all-centre regressor, which adds nothing.
            continue
        values = values.with_columns(_days(values))
        if (values["date"] >= RESERVED_DAY).any():
            raise DataError("earlier factor values reach reserved window")
        ranks = _lineage_ranks(matrix(values, row["name"], days, symbols))
        x = np.nan_to_num(ranks[finite], nan=0.0)
        centred = x - x.mean()
        norm = float(np.linalg.norm(centred) * np.linalg.norm(y))
        correlation = abs(float(centred @ y)) / norm if norm else 0.0
        regressors.append((correlation, x))
    if unavailable:
        return {
            **result,
            "lineage_reason": f"factor values unavailable for {unavailable} earlier judged factors",
        }
    if not regressors:
        return {**result, "lineage_reason": "no earlier judged factor on the same panel"}
    # Python's stable sort leaves equal correlations in ledger order.
    selected = sorted(regressors, key=lambda item: -item[0])[:20]
    design = np.column_stack([item[1] for item in selected])
    coefficients, _, rank, _ = np.linalg.lstsq(design, y, rcond=None)
    residual = y - design @ coefficients
    adjusted = max(0.0, 1 - float(residual @ residual) / total * y.size / (y.size - int(rank)))
    return {
        **result,
        "lineage_r2": adjusted,
        "lineage_regressors": len(selected),
        "composite_suspect": adjusted >= 0.5,
    }


def screen(
    signal: np.ndarray,
    outcome: np.ndarray,
    digest: str,
    *,
    series: dict[str, Any] | None = None,
    n_resamples: int | None = None,
    eligible: np.ndarray | None = None,
    gap_policy: bool = False,
    declared_direction: int | None = None,
) -> dict[str, Any]:
    values = np.asarray(signal, dtype=float)
    outcomes = np.asarray(outcome, dtype=float)
    skipped = 0
    keep = np.ones(len(values), dtype=bool)
    if gap_policy:
        keep = np.isfinite(values).sum(axis=1) >= MIN_NAMES
        skipped = int((~keep).sum())
        values, outcomes = values[keep], outcomes[keep]
        eligible = eligible[keep] if eligible is not None else None
        if not len(values):
            return {
                "status": "DEGENERATE",
                "p": 1.0,
                "breadth_skipped_days": skipped,
                "reason": "membership or liquidity rule left fewer than 5 names on every day",
            }
    finite = np.isfinite(values)
    # With a liquidity rule (ADR-0055) coverage is judged over the names the universe let rank;
    # without one every cell counts, as before.
    coverage = (
        float(finite.mean()) if eligible is None else float(finite.sum() / max(1, eligible.sum()))
    )
    ties = sum(
        bool(row.size and np.ptp(row) == 0) for row in (r[np.isfinite(r)] for r in values)
    ) / len(values)
    thin_days = int((finite.sum(axis=1) < MIN_NAMES).sum())
    result: dict[str, Any] = {"coverage": coverage, "tie_share": ties, "thin_days": thin_days}
    if gap_policy:
        result["breadth_skipped_days"] = skipped
    if eligible is not None:
        result["universe_thin_days"] = int((eligible.sum(axis=1) < MIN_NAMES).sum())
    if coverage < 0.8 or ties > 0.05 or thin_days:
        # thin_days: the canonical replay needs a full weight cross-section every day and
        # cannot hold cash, so a factor with any day under MIN_NAMES names cannot be replayed.
        if result.get("universe_thin_days"):
            result["reason"] = "the universe's liquidity rule left fewer than 5 names on some days"
        return {**result, "status": "DEGENERATE", "p": 1.0}
    ic = cross_sectional_ic(values, outcomes, min_names=MIN_NAMES)
    if series is not None:
        expanded: list[float | None] = [None] * len(signal)
        for index, value in zip(np.flatnonzero(keep), ic.values, strict=True):
            expanded[index] = value
        series.update(
            daily_ic=expanded, names=(np.isfinite(signal) & np.isfinite(outcome)).sum(axis=1)
        )
    daily = np.asarray([v for v in ic.values if v is not None], dtype=float)
    if len(daily) < 2 or float(np.std(daily, ddof=1)) == 0:
        return {**result, "status": "DEGENERATE", "p": 1.0, "reason": "IC has no usable variation"}
    inference = screen_statistics(values, outcomes, daily, declared_direction)
    mean = float(daily.mean())
    interval = block_bootstrap_ci(
        daily,
        lambda x: float(np.mean(x)),
        seed=int(digest[:8], 16),
        n_resamples=BOOTSTRAP_RESAMPLES if n_resamples is None else n_resamples,
    )
    return {
        **result,
        "status": "OK",
        "mean_ic": mean,
        "n": len(daily),
        "warnings": [f"low_sample: n={len(daily)}"] if len(daily) < 20 else [],
        **inference,
        "mean_ci_95": asdict(interval),
        "direction": declared_direction
        if declared_direction is not None
        else (1 if mean > 0 else -1 if mean < 0 else 0),
        "direction_selection": "declared before evaluation"
        if declared_direction is not None
        else "diagnostic only: cannot pass",
    }


def screen_at_clock(
    signal: np.ndarray,
    opens: np.ndarray,
    days: list[date],
    digest: str,
    clock: str,
    *,
    open_days: list[date],
    series: dict[str, Any] | None = None,
    n_resamples: int | None = None,
    eligible: np.ndarray | None = None,
    gap_policy: bool = False,
    closes: np.ndarray | None = None,
    declared_direction: int | None = None,
) -> dict[str, Any]:
    data = clock_samples(
        signal, opens, days, open_days, clock, closes=closes, gap_policy=gap_policy
    )
    if series is not None:
        series.update(data)
    seed_digest = digest if clock == "daily" else sha((digest + clock).encode())
    options: dict[str, Any] = {} if n_resamples is None else {"n_resamples": n_resamples}
    if eligible is not None:
        index = {day: i for i, day in enumerate(days)}
        options["eligible"] = eligible[[index[day] for day in data["days"]]]
    if gap_policy:
        options["gap_policy"] = True
    result = screen(
        data["signal"],
        data["outcome"],
        seed_digest,
        series=series,
        declared_direction=declared_direction,
        **options,
    )
    if gap_policy:
        result.update(data["gap_counts"])
    return result


def _return_metrics(values: np.ndarray) -> dict[str, float]:
    sd = float(values.std(ddof=1))
    if not np.isfinite(values).all() or sd <= 0:
        raise DataError("degenerate replay excess return series")
    curve = np.concatenate(([1.0], np.cumprod(1 + values)))
    return {
        "annualized_return": float(values.mean()) * ANNUAL_DAYS,
        "compounded_return": float(curve[-1] - 1),
        "sharpe": float(values.mean()) / sd * math.sqrt(ANNUAL_DAYS),
        "per_observation_sharpe": float(values.mean()) / sd,
        "max_drawdown": float(np.min(curve / np.maximum.accumulate(curve) - 1)),
    }


def replay(
    panel: pl.DataFrame,
    signal: np.ndarray,
    days: list[date],
    direction: int,
    *,
    clock: str = "daily",
    series: dict[str, Any] | None = None,
    gap_policy: bool = False,
    identity_segments: frozenset[str] = frozenset(),
) -> tuple[dict[str, Any], np.ndarray]:
    if gap_policy:
        return _gap_replay(
            panel,
            signal,
            days,
            direction,
            clock=clock,
            series=series,
            identity_segments=identity_segments,
        )
    sessions = [days[0] + timedelta(days=n) for n in range((days[-1] - days[0]).days + 3)]
    if sessions[-1] >= RESERVED_DAY or (panel["date"] >= RESERVED_DAY).any():
        raise DataError("replay reaches reserved window")
    rows = panel.filter(pl.col("date").is_between(sessions[0], sessions[-1]))
    symbols = sorted(panel["instrument"].unique().to_list())
    bars = {}
    for name in symbols:
        group = rows.filter(pl.col("instrument") == name).sort("date")
        if group["date"].to_list() != sessions:
            raise DataError("replay requires a complete daily session rectangle")
        bars[name] = [
            Bar(
                symbol=name,
                ts=datetime.combine(r["date"], time(), UTC),
                open=r["open"],
                high=r["high"],
                low=r["low"],
                close=r["close"],
                volume=r["volume"],
            )
            for r in group.iter_rows(named=True)
        ]
    targets, missing, cash_days, rebalances = clock_targets(
        signal,
        matrix(panel, "close", days, symbols),
        days,
        symbols,
        direction,
        clock,
        top_fraction=TOP_FRACTION,
        min_names=MIN_NAMES,
    )
    result = run_weight_replay(bars, targets, fee_bps=FEE_BPS, slippage_bps=SLIPPAGE_BPS)
    if series is not None:
        series.update(periods=result.periods, targets=targets)
    net = np.array([p.excess_return for p in result.periods])
    gross = np.array([p.gross_return - p.benchmark_return for p in result.periods])
    return {
        "net": _return_metrics(net),
        "gross": _return_metrics(gross),
        "mean_turnover": float(np.mean([p.turnover for p in result.periods])),
        "turnover_per_rebalance": sum(p.turnover for p in result.periods) / rebalances,
        "annual_cost": (
            sum(p.fees + p.slippage_cost for p in result.periods)
            / float(np.mean([equity for _, equity in result.backtest.equity_curve]))
            * ANNUAL_DAYS
            / len(result.periods)
        ),
        "rebalances": rebalances,
        "unrankable_instrument_rebalances": missing,
        "cash_days": cash_days,
        "tie_break": "instrument name ascending",
        "available_at": (
            "origin session + 23h (ALPHA canonical daily close stamp; bar d contains the full "
            "UTC day)"
        ),
    }, net


def _thirds(
    row: np.ndarray, direction: int, symbols: list[str], *, reverse_ties: bool
) -> tuple[list[int], list[int]]:
    """Top and bottom third by the claimed direction among names with a value at decision time.

    The replay's own order: k = round(n / 3) names, ties broken by instrument name ascending;
    ``reverse_ties`` breaks them descending instead, so a spread that only exists because of the
    tie order can be seen.
    """
    available = [j for j, value in enumerate(row) if math.isfinite(value)]
    by_name = sorted(available, key=lambda j: symbols[j], reverse=reverse_ties)
    ranked = sorted(by_name, key=lambda j: -direction * row[j])  # stable: name order breaks ties
    k = max(1, round(TOP_FRACTION * len(available)))
    return ranked[:k], ranked[len(ranked) - k :]


def spread(
    signal: np.ndarray,
    outcome: np.ndarray,
    direction: int,
    symbols: list[str],
    digest: str,
    *,
    horizon: int,
    annual: int = ANNUAL_DAYS,
    n_resamples: int | None = None,
    gap_policy: bool = False,
) -> dict[str, Any]:
    """Does the top third the factor would hold beat its bottom third, before costs (ADR-0055)?

    One observation per decision day: the mean forward return of the top third minus that of the
    bottom third, ranked at the decision day's close, returns from the next open (the screen's own
    non-overlapping windows, so consecutive observations share no return day). Passing needs a
    positive mean spread in the claimed direction under both tie orders; this only adds a way to
    fail before the replay. Uncertainty reuses the screen's estimators: the autocorrelation-adjusted
    effective sample size (t-statistic) and the seeded stationary-bootstrap interval.
    """
    if direction not in (1, -1):
        raise DataError("spread check needs a claimed direction")
    observed: dict[bool, list[float]] = {False: [], True: []}
    tops, bottoms, members = [], [], []
    skipped = 0
    for scores, returns in zip(np.asarray(signal, float), np.asarray(outcome, float), strict=True):
        if gap_policy and np.isfinite(scores).sum() < MIN_NAMES:
            skipped += 1
            continue
        for reverse in (False, True):
            top, bottom = _thirds(scores, direction, symbols, reverse_ties=reverse)
            if len(top) + len(bottom) > np.isfinite(scores).sum() or not top:
                raise DataError("spread check needs a top and a bottom third that do not overlap")
            held = returns[[*top, *bottom]]
            if not np.isfinite(held).all():
                # The replay needs every held name's bars too; dropping the name would keep only
                # the names that survived the holding period.
                raise DataError("spread check needs a forward return for every ranked name")
            high = math.fsum(returns[top]) / len(top)
            low = math.fsum(returns[bottom]) / len(bottom)
            observed[reverse].append(high - low)
            if not reverse:
                tops.append(high)
                bottoms.append(low)
                members.append(set(top))
    values = np.asarray(observed[False], dtype=float)
    if values.size < 2 or float(values.std(ddof=1)) <= 0:
        raise DataError("spread check needs at least two decision days with varying spreads")
    effective = autocorrelation_effective_size(values)
    mean = math.fsum(values) / values.size
    alternate = math.fsum(observed[True]) / len(observed[True])
    t = mean / (float(values.std(ddof=1)) / math.sqrt(effective))
    interval = block_bootstrap_ci(
        values,
        lambda x: float(np.mean(x)),
        seed=int(sha((digest + "spread").encode())[:8], 16),
        n_resamples=BOOTSTRAP_RESAMPLES if n_resamples is None else n_resamples,
    )
    changed = [len(b - a) / len(b) for a, b in zip(members, members[1:], strict=False)]
    turnover = math.fsum(changed) / len(changed)
    passed = mean > 0 and alternate > 0
    result = {
        "status": "PASS" if passed else "FAIL",
        "decision_days": int(values.size),
        "horizon_days": horizon,
        "top_third_mean_return": math.fsum(tops) / len(tops),
        "bottom_third_mean_return": math.fsum(bottoms) / len(bottoms),
        "mean_spread": mean,
        "annualized_spread": mean * annual / horizon,
        "alternate_tie_order_mean_spread": alternate,
        "effective_n": effective,
        "t": t,
        "mean_ci_95": asdict(interval),
        "top_share_changed_per_rebalance": turnover,
        "estimated_annual_cost": turnover * 2 * (FEE_BPS + SLIPPAGE_BPS) / 1e4 * annual / horizon,
        "warnings": [f"low_sample: n={values.size}"] if values.size < 20 else [],
        "basis": "before costs; mean over decision days; non-overlapping forward windows",
    }
    if gap_policy:
        result.update(breadth_skipped_days=skipped)
    if not passed:
        result["reason"] = SPREAD_REASON
    return result


def spread_at_clock(
    signal: np.ndarray,
    opens: np.ndarray,
    days: list[date],
    digest: str,
    clock: str,
    *,
    open_days: list[date],
    direction: int,
    symbols: list[str],
    n_resamples: int | None = None,
    gap_policy: bool = False,
    closes: np.ndarray | None = None,
) -> dict[str, Any]:
    data = clock_samples(
        signal, opens, days, open_days, clock, closes=closes, gap_policy=gap_policy
    )
    counts: dict[str, int] = {}
    if gap_policy:
        if closes is None:
            raise DataError("gap spread requires closes")
        index = {day: i for i, day in enumerate(open_days)}
        starts = [index[day + timedelta(days=1)] for day in data["days"]]
        ends = [index[day + timedelta(days=1 + CLOCKS[clock])] for day in data["days"]]
        counted = np.zeros(data["signal"].shape, dtype=bool)
        for i, row in enumerate(data["signal"]):
            if np.isfinite(row).sum() >= MIN_NAMES:
                top, bottom = _thirds(row, direction, symbols, reverse_ties=False)
                counted[i, [*top, *bottom]] = True
        data["outcome"], counts = membership.holding_returns(
            opens,
            closes,
            open_days,
            starts,
            ends,
            counted=counted,
        )
    result = spread(
        data["signal"],
        data["outcome"],
        direction,
        symbols,
        sha((digest + clock).encode()),
        horizon=CLOCKS[clock],
        n_resamples=n_resamples,
        **({"gap_policy": True} if gap_policy else {}),
    )
    if gap_policy:
        result.update(counts)
        result["basis"] = (
            "before costs; fixed non-overlapping decision schedule; delayed gap exits may "
            "overlap later holding windows; missing entry opens stay cash"
        )
    return result


def panel_membership(panel: pl.DataFrame, days: list[date], symbols: list[str]) -> np.ndarray:
    start = min(panel["date"].to_list())
    history = [start + timedelta(days=i) for i in range((days[-1] - start).days + 1)]
    return membership.membership(matrix(panel, "close", history, symbols), history, days)


def _gap_replay(
    panel: pl.DataFrame,
    signal: np.ndarray,
    days: list[date],
    direction: int,
    *,
    clock: str,
    series: dict[str, Any] | None,
    identity_segments: frozenset[str] = frozenset(),
) -> tuple[dict[str, Any], np.ndarray]:
    if (panel["date"] >= RESERVED_DAY).any() or days[-1] + timedelta(days=2) >= RESERVED_DAY:
        raise DataError("replay reaches reserved window")
    if days[0] != date.fromisoformat(EXPLORATION[0]) or any(
        (b - a).days != 1 for a, b in zip(days, days[1:], strict=False)
    ):
        raise DataError("replay needs consecutive days from the exploration phase")
    symbols = sorted(panel["instrument"].unique().to_list())
    last = max(panel["date"].to_list())
    if last < days[-1] + timedelta(days=2):
        raise DataError("replay needs two trailing panel days")
    sessions = [days[0] + timedelta(days=i) for i in range((last - days[0]).days + 1)]
    eligible = panel_membership(panel, days, symbols)
    scores = np.where(eligible, signal, np.nan)
    data = membership.run_gap_replay(
        matrix(panel, "open", sessions, symbols),
        matrix(panel, "close", sessions, symbols),
        sessions,
        scores,
        eligible,
        symbols,
        horizon=CLOCKS[clock],
        direction=direction,
        min_names=MIN_NAMES,
        fraction=TOP_FRACTION,
        fee_bps=FEE_BPS,
        slippage_bps=SLIPPAGE_BPS,
        identity_segments=identity_segments,
    )
    periods = data["periods"]
    net = np.array([p.excess_return for p in periods])
    gross = np.array([p.gross_return - p.benchmark_return for p in periods])
    if series is not None:
        series.update({key: data[key] for key in ("periods", "targets", "positions", "events")})
    metrics = {
        "net": _return_metrics(net),
        "gross": _return_metrics(gross),
        "mean_turnover": float(np.mean([p.turnover for p in periods])),
        "turnover_per_rebalance": sum(p.turnover for p in periods) / data["rebalances"],
        "annual_cost": sum(p.fees + p.slippage_cost for p in periods)
        / float(np.mean(data["equity_curve"]))
        * ANNUAL_DAYS
        / len(periods),
        "gap_policy": membership.POLICY,
        "unrankable_instrument_rebalances": data["missing_coin_days"],
        "writeoff_instruments": sorted(
            {
                e["instrument"]
                for e in data["events"]
                if e["basis"] in ("writeoff", "panel-end-writeoff")
            }
        ),
        **{
            key: data[key]
            for key in (
                "rebalances",
                "breadth_skipped_days",
                "haircuts_applied",
                "written_off_at_panel_end",
                "benchmark_haircuts_applied",
            )
        },
    }
    return metrics, net
