"""The RD-Agent judge core: frozen-panel constants and checks, screen, spread check.

Split out of `rdagent_factor_eval` unchanged; that module re-exports these names. The ALPHA
replay lives in `_rdagent_judge_replay`."""

from __future__ import annotations

import hashlib
import io
import json
import math
import os
import re
import subprocess
from dataclasses import asdict
from datetime import date, timedelta
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
    SWING_CLOCKS,
    clock_samples,
)
from alpha_cli._rdagent_costs import judge_costs
from alpha_cli._rdagent_stats import autocorrelation_effective_size, screen_statistics
from alpha_cli.crypto_bulk_store import configured_crypto_bulk_store
from alpha_cli.toolbox.reserve import RESERVED_DAY, RESERVED_START
from alpha_core import DataError
from alpha_data.context.daily_funding import daily_funding_with_sources
from alpha_research.panel import cross_sectional_ic
from alpha_validation.bootstrap import block_bootstrap_ci

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
    "top_fraction": TOP_FRACTION,
    "annual_days": ANNUAL_DAYS,
    "min_names": MIN_NAMES,
    "q_threshold": Q_THRESHOLD,
    "bootstrap_resamples": BOOTSTRAP_RESAMPLES,
    "spread_check": (
        "ADR-0055: a screened clock passes only if the mean over its decision days of the top "
        "third's minus the bottom third's forward return (before costs, claimed direction) is "
        "positive with equal fractional boundary-tie weights; otherwise it is SPREAD_FAIL "
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
    result: dict[str, Any] = {
        "coverage": coverage,
        **tie_diagnostics(values),
        "all_tied_day_share": ties,
        "thin_days": thin_days,
    }
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


def tie_diagnostics(values: np.ndarray) -> dict[str, float]:
    tied_shares, boundary_shares = [], []
    for row in values:
        finite = row[np.isfinite(row)]
        if not len(finite):
            tied_shares.append(0.0)
            boundary_shares.append(0.0)
            continue
        _, counts = np.unique(finite, return_counts=True)
        tied_shares.append(float(counts[counts > 1].sum() / len(finite)))
        top = membership.third_weights(finite, 1, TOP_FRACTION)
        bottom = membership.third_weights(finite, -1, TOP_FRACTION)
        boundary_shares.append(
            float((((top > 0) & (top < 1)) | ((bottom > 0) & (bottom < 1))).mean())
        )
    return {
        "tie_share": math.fsum(tied_shares) / len(values),
        "boundary_tie_share": math.fsum(boundary_shares) / len(values),
    }


def _thirds(
    row: np.ndarray, direction: int, symbols: list[str], *, reverse_ties: bool
) -> tuple[list[int], list[int]]:
    """Names with positive fractional membership, listed in the legacy display order."""
    by_name = sorted(range(len(row)), key=lambda j: symbols[j], reverse=reverse_ties)
    ranked = sorted(by_name, key=lambda j: -direction * row[j] if np.isfinite(row[j]) else math.inf)
    top = membership.third_weights(row, direction, TOP_FRACTION)
    bottom = membership.third_weights(row, -direction, TOP_FRACTION)
    return [j for j in ranked if top[j] > 0], [j for j in ranked if bottom[j] > 0]


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
    positive mean spread in the claimed direction with fractional boundary ties; this adds a way to
    fail before the replay. Uncertainty reuses the screen's estimators: the autocorrelation-adjusted
    effective sample size (t-statistic) and the seeded stationary-bootstrap interval.
    """
    if direction not in (1, -1):
        raise DataError("spread check needs a claimed direction")
    observed, tops, bottoms, members = [], [], [], []
    skipped = 0
    for scores, returns in zip(np.asarray(signal, float), np.asarray(outcome, float), strict=True):
        n = int(np.isfinite(scores).sum())
        if gap_policy and n < MIN_NAMES:
            skipped += 1
            continue
        k = max(1, round(TOP_FRACTION * n))
        if 2 * k > n:
            raise DataError("spread check needs a top and a bottom third that do not overlap")
        top = membership.third_weights(scores, direction, TOP_FRACTION)
        bottom = membership.third_weights(scores, -direction, TOP_FRACTION)
        if not np.isfinite(returns[(top > 0) | (bottom > 0)]).all():
            raise DataError("spread check needs a forward return for every ranked name")
        high = math.fsum(returns[top > 0] * top[top > 0]) / k
        low = math.fsum(returns[bottom > 0] * bottom[bottom > 0]) / k
        observed.append(high - low)
        tops.append(high)
        bottoms.append(low)
        members.append((top, k))
    values = np.asarray(observed, dtype=float)
    if values.size < 2 or float(values.std(ddof=1)) <= 0:
        raise DataError("spread check needs at least two decision days with varying spreads")
    effective = autocorrelation_effective_size(values)
    mean = math.fsum(values) / values.size
    alternate = mean  # Retain the stored field; fractional ties have no alternate order.
    t = mean / (float(values.std(ddof=1)) / math.sqrt(effective))
    interval = block_bootstrap_ci(
        values,
        lambda x: float(np.mean(x)),
        seed=int(sha((digest + "spread").encode())[:8], 16),
        n_resamples=BOOTSTRAP_RESAMPLES if n_resamples is None else n_resamples,
    )
    changed = [
        math.fsum(np.maximum(b - a, 0.0)) / k
        for (a, _), (b, k) in zip(members, members[1:], strict=False)
    ]
    turnover = math.fsum(changed) / len(changed)
    costs = judge_costs()
    round_trip_bps = costs["fee_bps"] + costs["slippage_bps"]
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
        "estimated_annual_cost": turnover * 2 * round_trip_bps / 1e4 * annual / horizon,
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
