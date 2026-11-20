"""Fixed factor set, plain sentences and the all-signal search of the published-factor reading."""

from __future__ import annotations

from datetime import date
from typing import Any

# Chosen in code before any result: the source's acronym and a plain name. Years come from the file.
FIXED = (
    ("Mom12m", "momentum"),
    ("STreversal", "short-term reversal"),
    ("Size", "size"),
    ("BM", "book-to-market"),
    ("Beta", "low beta"),
    ("OperProf", "profitability"),
    ("AssetGrowth", "asset growth"),
)
MONTHLY = 12
NUMBERS = ("explained_share",)
BASIS = (
    "Compounded calendar-month returns of the scored walk-forward period (complete months only) "
    "against the stored monthly long-short returns of published US stock signals, matched by "
    "calendar month."
)
CAUTION = (
    "A clear exposure to a factor is not evidence of an edge, a low explained share does not "
    "show an edge either, and the ranges are too narrow when months are few."
)
NOT_US = (
    "Not applicable: these reference factors are US stock factors, and the stored data for "
    "this run is not a US stock or ETF."
)
UNKNOWN = (
    "Cannot read: the stored data for this run does not record what kind of asset it is, so it "
    "is not known whether these US stock factors apply."
)
SEARCH_STATEMENT = (
    "Picking the three closest of all stored signals is a search, not a test chosen in advance, "
    "and the correlation range assumes independent months."
)


def series_by_signal(rows: Any) -> tuple[dict[str, dict[date, float]], dict[str, int]]:
    by_signal: dict[str, dict[date, float]] = {}
    years: dict[str, int] = {}
    for signal, month, value, year in rows.select(
        "signal", "month", "long_short_return", "published_year"
    ).iter_rows():
        by_signal.setdefault(signal, {})[month] = value
        years[signal] = year
    return by_signal, years


def exposures(factors: list[dict[str, Any]]) -> str:
    parts = [
        f"{row['label']} (published {row['published_year']}) {row['beta']:.2f} "
        f"({row['ci95'][0]:.2f} to {row['ci95'][1]:.2f})"
        for row in factors
    ]
    return "Exposure to each factor, with its 95% range: " + "; ".join(parts) + "."


def search(
    strategy: list[float],
    used: list[date],
    by_signal: dict[str, dict[date, float]],
    years: dict[str, int],
) -> dict[str, Any]:
    from alpha_core import DataError
    from alpha_validation.correlation_interval import correlation_interval
    from alpha_validation.proportion import benjamini_hochberg

    rows = []
    for signal in sorted(by_signal):
        if not all(month in by_signal[signal] for month in used):
            continue
        try:
            ci = correlation_interval(strategy, [by_signal[signal][m] for m in used])
        except DataError:
            continue
        rows.append({"signal": signal, "published_year": years[signal], **ci})
    adjusted = benjamini_hochberg([row["p"] for row in rows]).qvalues.tolist()
    for row, q in zip(rows, adjusted, strict=True):
        row["q"] = float(q)
    top = sorted(rows, key=lambda row: (-abs(row["r"]), row["signal"]))[:3]
    label = f"search across all {len(by_signal)} — exploratory"
    shown = "; ".join(
        f"{row['signal']} (published {row['published_year']}) r {row['r']:.2f}, 95% range "
        f"{row['ci95'][0]:.2f} to {row['ci95'][1]:.2f}, adjusted p {row['q']:.3f}"
        for row in top
    )
    return {
        "label": label,
        "statement": SEARCH_STATEMENT,
        "compared": len(rows),
        "top": [
            {k: row[k] for k in ("signal", "published_year", "r", "ci95", "p", "q", "n", "edge")}
            for row in top
        ],
        "sentence": f"{label[0].upper()}{label[1:]}: {shown}. {SEARCH_STATEMENT}",
    }


def singles(strategy: list[float], matrix: Any, names: list[str]) -> list[dict[str, Any]]:
    from alpha_core import DataError
    from alpha_validation.factor_attribution import factor_attribution

    out = []
    for index, name in enumerate(names):
        try:
            fit = factor_attribution(
                strategy, matrix[:, [index]], periods_per_year=MONTHLY, factor_names=[name]
            )
        except DataError as exc:
            out.append({"signal": name, "refusal": str(exc)})
            continue
        out.append(
            {
                "signal": name,
                "beta": fit["factors"][0]["beta"],
                "ci95": fit["factors"][0]["ci95"],
                "r_squared": fit["r_squared"],
                "n": fit["n"],
            }
        )
    return out
