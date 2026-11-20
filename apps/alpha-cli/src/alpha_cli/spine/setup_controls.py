"""Forward-outcome controls; these functions never select setup occurrences.

The Monte Carlo tail uses (b + 1)/(m + 1): Phipson & Smyth (2010),
Permutation P-values Should Never Be Zero, doi:10.2202/1544-6115.1585.
Dates are exchangeable under this exploratory random-date null, not reserved evidence.
"""

from __future__ import annotations

import hashlib
from typing import Any

from alpha_cli.spine.reading import LEGACY_SETUP_OUTCOMES, NOT_CLEAR, SOME, TOO_LITTLE
from alpha_cli.spine.setup_find import CLUSTER_GAP_BARS

RANDOM_DRAWS = 2000


def eligible_returns(
    opened: list[float], closed: list[float], warmup: int, horizon: int, cost: float
) -> tuple[Any, Any]:
    import numpy as np

    if horizon < 1 or warmup < 0 or len(opened) != len(closed):
        raise ValueError("invalid horizon, warm-up or bar lengths")
    op, cl = np.asarray(opened, dtype=float), np.asarray(closed, dtype=float)
    if not np.all(np.isfinite(op)) or not np.all(np.isfinite(cl)) or np.any(op <= 0):
        raise ValueError("control prices must be finite and opens positive")
    if not np.isfinite(cost) or cost < 0:
        raise ValueError("cost must be finite and non-negative")
    positions = np.arange(warmup, max(warmup, len(op) - horizon))
    # Future close is the measured outcome, never an input to detection or entry.
    returns = cl[positions + horizon] / op[positions + 1] - 1 - cost
    return positions, returns


def _capacity(size: int) -> int:
    """Most dates more than CLUSTER_GAP_BARS apart that fit in `size` consecutive bars."""
    return (size + CLUSTER_GAP_BARS) // (CLUSTER_GAP_BARS + 1)


def sample_dates(eligible: Any, count: int, rng: Any, draws: int = 1) -> Any:
    """Uniform draws from every spaced subset of a contiguous run of eligible positions.

    Returns one sorted array of `count` positions, or a (draws, count) array when draws > 1.
    """
    import numpy as np

    eligible = np.asarray(eligible)
    if count < 0 or draws < 1:
        raise ValueError("invalid random-date count or number of draws")
    if len(eligible) and np.any(np.diff(eligible) != 1):
        raise ValueError("random-date positions must be one contiguous run of bars")
    slots = len(eligible) - max(0, count - 1) * CLUSTER_GAP_BARS
    if count > slots:
        capacity = _capacity(len(eligible))
        raise ValueError(f"random-date spacing impossible: need {count}, capacity {capacity}")
    # Exact, not rejection: subtracting i * gap from the i-th smallest spaced position maps
    # spaced sets one-to-one onto plain subsets of `slots` positions, so uniform plain
    # subsets give uniform spaced sets in a single draw.
    offsets = np.arange(count) * CLUSTER_GAP_BARS
    picked = np.empty((draws, count), dtype=np.int64)
    for draw in range(draws):
        picked[draw] = np.sort(rng.choice(slots, size=count, replace=False)) + offsets
    out = (eligible[0] if len(eligible) else 0) + picked
    return out[0] if draws == 1 else out


def _stats(values: list[float]) -> dict[str, Any]:
    import numpy as np

    keys = ("mean", "median", "hit_rate", "best", "worst")
    if not values:
        return {**dict.fromkeys(keys), "reasons": dict.fromkeys(keys, "no complete occurrences")}
    a = np.asarray(values, dtype=float)
    if not np.all(np.isfinite(a)):
        raise ValueError("occurrence returns must be finite")
    return dict(
        mean=float(a.mean()),
        median=float(np.median(a)),
        hit_rate=float((a > 0).mean()),
        best=float(a.max()),
        worst=float(a.min()),
        reasons={},
    )


def _comparison(
    values: list[float], drift: tuple[Any, Any], means: Any, *, tested: bool
) -> dict[str, Any]:
    import numpy as np

    out = dict(occurrences=len(values), **_stats(values))
    baseline, weights = drift
    out.update(
        drift_mean=None,
        drift_median=None,
        excess=None,
        random_date_5=None,
        random_date_50=None,
        random_date_95=None,
        random_date_p=None,
    )
    if len(baseline):
        out["drift_mean"] = float(np.average(baseline, weights=weights))
        order = np.argsort(baseline)
        cumulative = np.cumsum(weights[order])
        # Weighted empirical median, interpolating when exactly half the mass lies below a gap.
        middle = int(np.searchsorted(cumulative, cumulative[-1] / 2))
        median = baseline[order[middle]]
        if cumulative[middle] == cumulative[-1] / 2 and middle + 1 < len(order):
            median = (median + baseline[order[middle + 1]]) / 2
        out["drift_median"] = float(median)
    if values:
        out["excess"] = out["mean"] - out["drift_mean"]
    if values and means is not None:
        for key, value in zip(
            ("random_date_5", "random_date_50", "random_date_95"),
            np.percentile(means, [5, 50, 95]),
            strict=True,
        ):
            out[key] = float(value)
        if tested:
            out["random_date_p"] = float((np.sum(means >= out["mean"]) + 1) / (RANDOM_DRAWS + 1))
    for key, value in out.items():
        if value is None:
            out["reasons"][key] = (
                "only the pooled primary horizon is tested"
                if key == "random_date_p" and not tested
                else "no complete occurrences"
                if not values
                else "random-date spacing impossible in this date range"
                if means is None and key.startswith("random_date")
                else "no eligible control dates"
            )
    return out


def control_summary(
    eligible: dict[str, tuple[Any, Any]], chosen: dict[str, list[float]], seed: str, *, tested: bool
) -> dict[str, Any]:
    """Per-asset controls pooled with the complete occurrence counts as asset weights."""
    import numpy as np

    pooled: Any = np.zeros(RANDOM_DRAWS)
    assets, baseline, weights = {}, [], []
    all_values = [value for asset in sorted(chosen) for value in chosen[asset]]
    for asset in sorted(eligible):
        positions, returns = eligible[asset]
        values = chosen.get(asset, [])
        rng = np.random.default_rng(
            int.from_bytes(hashlib.sha256(f"{seed}|{asset}".encode()).digest()[:8])
        )
        means: Any = np.zeros(RANDOM_DRAWS)
        if values and not tested and len(values) > _capacity(len(positions)):
            # Only a half can be this tight; its random-date figures are reported unavailable.
            means = pooled = None
        elif values:
            selected = sample_dates(positions, len(values), rng, RANDOM_DRAWS)
            means = returns[selected - positions[0]].mean(axis=1)
            if pooled is not None:
                pooled += means * len(values)
        if values:
            baseline.extend(returns)
            weights.extend([len(values) / len(returns)] * len(returns))
        assets[asset] = _comparison(values, (returns, np.ones(len(returns))), means, tested=False)
    if pooled is not None:
        pooled /= max(1, len(all_values))
    return dict(
        assets=assets,
        pooled=_comparison(
            all_values, (np.asarray(baseline), np.asarray(weights)), pooled, tested=tested
        ),
    )


def _half_controls(
    eligible: dict[str, tuple[Any, Any]], entry_times: dict[str, Any], keep: Any
) -> dict[str, tuple[Any, Any]]:
    """Controls restricted to the bars whose entry falls in the same chronological half."""
    import numpy as np

    out = {}
    for asset, (positions, returns) in eligible.items():
        mask = np.asarray([keep(ts) for ts in entry_times[asset]], dtype=bool)
        out[asset] = (positions[mask], returns[mask])
    return out


def horizon_summary(
    rows: list[dict[str, Any]],
    eligible: dict[str, tuple[Any, Any]],
    entry_times: dict[str, Any],
    seed: str,
    *,
    tested: bool,
) -> dict[str, Any]:
    """Same figures for each chronological half, each against controls from that half only.

    `entry_times[asset]` holds the entry timestamp of every eligible position. History is cut
    at the second half's first entry: the first half's controls are the eligible entries
    before it, the second half's from it on, so each half meets the market of its own years.
    Incomplete rows stay in their dated half.
    """
    ordered = sorted(rows, key=lambda r: (r["entry_ts"], r["asset"], r["candidate_id"]))
    first, second = ordered[: len(ordered) // 2], ordered[len(ordered) // 2 :]
    groups: dict[str, tuple[list[dict[str, Any]], dict[str, tuple[Any, Any]]]] = {
        "all": (ordered, eligible)
    }
    boundary = second[0]["entry_ts"] if first and second else None
    for name, group, keep in (
        ("first", first, lambda ts: ts < boundary),
        ("second", second, lambda ts: ts >= boundary),
    ):
        controls = eligible if boundary is None else _half_controls(eligible, entry_times, keep)
        groups[name] = (group, controls)
    summaries = {}
    for name, (group, controls) in groups.items():
        chosen = {
            a: [r["net_return"] for r in group if r["asset"] == a and r["complete"]]
            for a in eligible
        }
        summary = control_summary(
            controls, chosen, f"{seed}|{name}", tested=tested and name == "all"
        )
        summary["pooled"]["incomplete"] = sum(not r["complete"] for r in group)
        for asset, result in summary["assets"].items():
            result["incomplete"] = sum(not r["complete"] for r in group if r["asset"] == asset)
        summaries[name] = summary
    result = summaries["all"]
    result["pooled"]["stability"] = {k: summaries[k]["pooled"] for k in ("first", "second")}
    for asset in eligible:
        result["assets"][asset]["stability"] = {
            k: summaries[k]["assets"][asset] for k in ("first", "second")
        }
    result["labels"] = [] if tested else ["not-primary"]
    return result


MIN_OCCURRENCES = 30
P_LINE = 0.05


def study_evidence(primary: dict[str, Any], labels: list[str]) -> str:
    """The evidence word of one setup study. Never the top word: the p-value is not corrected."""
    if primary["occurrences"] < MIN_OCCURRENCES:
        return TOO_LITTLE
    p = primary["random_date_p"]
    agree = "halves-disagree" not in labels
    return SOME if p <= P_LINE and primary["excess"] > 0 and agree else NOT_CLEAR


def trade_evidence(primary: dict[str, Any], labels: list[str]) -> str:
    """The same word for a setup trade; it also needs a random control."""
    if primary["trades"] < MIN_OCCURRENCES:
        return TOO_LITTLE
    p, excess = primary["random_date_p"], primary["excess"]
    held = p is not None and p <= P_LINE and excess is not None and excess > 0
    clear = not {"halves-disagree", "no-random-control"}.intersection(labels)
    return SOME if held and clear else NOT_CLEAR


def reading(primary: dict[str, Any], horizon: int, labels: list[str]) -> tuple[str, str]:
    """The stored sentence and the stored outcome word (kept as written; the evidence is beside)."""
    n, mean, drift, p = (primary[k] for k in ("occurrences", "mean", "drift_mean", "random_date_p"))
    word = LEGACY_SETUP_OUTCOMES[study_evidence(primary, labels)]
    if n == 0:
        return "Too few occurrences (0) to judge. For the record: no complete outcomes.", word
    start = (
        f"After this setup the average {horizon}-bar return was {mean:.2%} "
        f"after costs, against {drift:.2%}"
    )
    if n < 30:
        return (
            f"Too few occurrences ({n}) to judge. For the record: {start} on any day; "
            f"random dates did as well or better in {p:.2%} of draws."
        ), word
    if word == LEGACY_SETUP_OUTCOMES[SOME]:
        return (
            f"{start} for the asset on any day; "
            f"random dates did this well in {p:.2%} of 2,000 draws. "
            "This is one counted test, not proof: it was not checked on reserved data. "
            "Beating random dates says these dates were unusual, not that the setup "
            "can be traded."
        ), word
    return (
        f"{start} on any day; random dates did as well or better in {p:.2%} of draws. "
        "No evidence the setup adds anything here."
    ), word


def study_labels(
    manifest: dict[str, Any],
    primary: dict[str, Any],
    paths: list[dict[str, Any]],
    bars: dict[str, Any],
    horizon: int,
) -> list[str]:
    copied = {"dev-machine-data", "daily-only", "source-defaulted", "short-history"}
    labels = ["exploratory", *sorted(copied.intersection(manifest["labels"]))]
    if primary["occurrences"] < 30:
        labels.append("too-few-occurrences")
    if len(bars) == 1:
        labels.append("single-asset")
    for asset, series in bars.items():
        indices = {b.ts: i for i, b in enumerate(series)}
        entries = sorted(indices[r["entry_ts"]] for r in paths if r["asset"] == asset)
        if any(b - a < horizon for a, b in zip(entries, entries[1:], strict=False)):
            labels.append("overlapping-outcomes")
            break
    halves = primary["stability"]
    left, right = halves["first"]["mean"], halves["second"]["mean"]
    if left is not None and right is not None and left * right < 0:
        labels.append("halves-disagree")
    return labels


def trade_measures(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Completed trades alone contribute returns; all occurrence dispositions are counted."""
    from collections import Counter

    import numpy as np

    done = [r for r in rows if r["complete"]]
    values = [r["net_return"] for r in done]
    stats = _stats(values)
    held = [r["bars_held"] for r in done]
    risks = [r["r_multiple"] for r in done if r["r_multiple"] is not None]
    risk_stats = _stats(risks)
    losses = -sum(v for v in values if v < 0)
    stats.update(
        trades=len(done),
        skipped=sum(r["reason"] == "skipped-in-trade" for r in rows),
        invalid=sum(r["reason"] == "invalid-levels" for r in rows),
        open_at_end=sum(r["reason"] == "open-at-end" for r in rows),
        mean_bars_held=float(np.mean(held)) if held else None,
        median_bars_held=float(np.median(held)) if held else None,
        mean_r=risk_stats["mean"],
        median_r=risk_stats["median"],
        share_above_zero_r=risk_stats["hit_rate"],
        expectancy_r=risk_stats["mean"],
        profit_factor=sum(v for v in values if v > 0) / losses if losses else None,
        by_reason=dict(Counter(r["reason"] for r in rows)),
        both_touched=sum(r["both_touched"] for r in rows),
    )
    if not risks:
        stats["reasons"].update(
            dict.fromkeys(
                ("mean_r", "median_r", "share_above_zero_r", "expectancy_r"),
                "no completed trades with a stop",
            )
        )
    for key in ("mean_bars_held", "median_bars_held", "profit_factor"):
        if stats[key] is None:
            stats["reasons"][key] = "no losses" if key == "profit_factor" else "no completed trades"
    return stats


def trade_report(
    rows: list[dict[str, Any]],
    cache: dict[str, dict[int, Any]],
    seed: str,
    control_reason: str | None = None,
) -> dict[str, Any]:
    """Chronological halves use only eligible entries in their own date range."""
    from alpha_cli.spine.setup_trade import trade_controls

    ordered = sorted(rows, key=lambda r: (r["entry_ts"], r["asset"], r["candidate_id"]))
    middle = len(ordered) // 2
    boundary = ordered[middle]["entry_ts"] if middle else None
    groups = {"all": ordered, "first": ordered[:middle], "second": ordered[middle:]}
    reports = {}
    for name, group in groups.items():
        eligible = {
            a: {
                p: r
                for p, r in values.items()
                if name == "all"
                or boundary is None
                or (r["entry_ts"] < boundary if name == "first" else r["entry_ts"] >= boundary)
            }
            for a, values in cache.items()
        }
        chosen = {
            a: [r["net_return"] for r in group if r["asset"] == a and r["complete"]] for a in cache
        }
        counts = {a: sum(r["asset"] == a for r in group) for a in cache}
        report = trade_controls(
            eligible,
            chosen,
            counts,
            f"{seed}|{name}",
            tested=name == "all",
            control_reason=control_reason,
        )
        for result, subset in [
            (report["pooled"], group),
            *[(report["assets"][a], [r for r in group if r["asset"] == a]) for a in cache],
        ]:
            measures = trade_measures(subset)
            measures["reasons"] = {**result["reasons"], **measures["reasons"]}
            result.update(measures)
        reports[name] = report
    report = reports["all"]
    report["pooled"]["stability"] = {k: reports[k]["pooled"] for k in ("first", "second")}
    for asset in cache:
        report["assets"][asset]["stability"] = {
            k: reports[k]["assets"][asset] for k in ("first", "second")
        }
    return report


def trade_reading(primary: dict[str, Any], labels: list[str]) -> tuple[str, str]:
    n, mean, drift, p = (primary[k] for k in ("trades", "mean", "drift_mean", "random_date_p"))
    word = LEGACY_SETUP_OUTCOMES[trade_evidence(primary, labels)]
    if n == 0:
        return "Too few trades (0) to judge. For the record: no completed trades.", word
    start = (
        f"Traded with these exits the average trade made {mean:.2%} after costs "
        f"(hit rate {primary['hit_rate']:.1%}, about {primary['mean_bars_held']:.1f} bars held)"
    )
    if drift is not None:
        start += f", against {drift:.2%} for the same exits started on any day"
    else:
        start += "; controls unavailable"
    if p is not None:
        start += f"; random dates did this well in {p:.2%} of 2,000 draws"
    start += "."
    if n < 30:
        return f"Too few trades ({n}) to judge. For the record: {start}", word
    if word == LEGACY_SETUP_OUTCOMES[SOME]:
        return (
            start + " Beating random dates says these dates were unusual, not that the setup "
            "can be traded. One counted test, not confirmed on reserved data."
        ), word
    return start + " No evidence the setup adds anything with these exits.", word


def trade_labels(
    manifest: dict[str, Any], primary: dict[str, Any], spec: Any, assets: int, occurrences: int
) -> list[str]:
    labels = [
        "exploratory",
        *sorted(
            set(manifest["labels"])
            - {"exploratory", "outcomes-not-viewed", "outcomes-viewed", "repeat"}
        ),
    ]
    if primary["trades"] < 30:
        labels.append("too-few-occurrences")
    if assets == 1:
        labels.append("single-asset")
    halves = primary["stability"]
    left, right = halves["first"]["mean"], halves["second"]["mean"]
    if left is not None and right is not None and left * right < 0:
        labels.append("halves-disagree")
    if not spec.exit.time_bars:
        labels.append("no-time-exit")
    if primary["random_date_p"] is None:
        labels.append("no-random-control")
    if primary["skipped"] > occurrences / 4:
        labels.append("many-skipped")
    return labels


def null_trade_controls(result: dict[str, Any], reason: str) -> None:
    for key in (
        "drift_mean",
        "drift_median",
        "excess",
        "random_date_5",
        "random_date_50",
        "random_date_95",
        "random_date_p",
    ):
        result[key] = None
        result["reasons"][key] = reason


def _draw_means(cache: dict[int, Any], count: int, seed: str) -> Any:
    import numpy as np

    positions = np.asarray(sorted(cache), dtype=int)
    if not count or count > (len(positions) + CLUSTER_GAP_BARS) // (CLUSTER_GAP_BARS + 1):
        return None
    rng = np.random.default_rng(int.from_bytes(hashlib.sha256(seed.encode()).digest()[:8]))
    dates = sample_dates(positions, count, rng, RANDOM_DRAWS)
    means = []
    for draw in dates:
        occupied, values = -1, []
        for position in draw:
            row = cache[int(position)]
            if row["entry_index"] <= occupied:
                continue
            if row["exit_index"] is not None:
                occupied = row["exit_index"]
            if row["complete"]:
                values.append(row["net_return"])
        if not values:
            return None  # A draw without a tested mean cannot silently be dropped.
        means.append(sum(values) / len(values))
    return np.asarray(means)
