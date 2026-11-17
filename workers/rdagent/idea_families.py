"""Construct-name classification for ALPHA proposals; no prose inference."""

from __future__ import annotations

import re
from typing import Any

# Construct names only (ADR-0055). Estimator words say how an idea is fitted, not its
# mechanism, so they are never family keywords ("volatility and beta" keeps explicit betas).
GENERIC_ESTIMATOR_WORDS = frozenset(
    {"beta", "slope", "regression", "ols", "ridge", "huber", "lasso", "lightgbm", "gbm"}
    | {"model", "residual", "rank", "zscore"}
)
# Keywords are matched on name tokens (hyphens, spaces and case normalised), longest first,
# and a matched keyword consumes its tokens. A final keyword token of four or more letters
# also matches as a prefix (prox -> proximity, skew -> skewness). The table order decides a
# single name's family when it matches several.
FAMILY_KEYWORDS = (
    (
        "price near its high / range position",
        ("high_prox", "near_high", "distance_to_high", "stoch", "rangepos", "range_position", "hp"),
    ),
    (
        "short-term reversal and gaps",
        ("reversal_3d", "reversal_5d", "short_term_reversal", "gap", "gaps", "intraday_reversal"),
    ),
    ("long-term reversal", ("long_term_reversal", "ltr")),
    ("illiquidity", ("amihud", "illiquid")),
    ("return-volume relation", ("ret_vol_corr", "volume_return", "signed_volume", "flow_conf")),
    ("skewness and lottery returns", ("skew", "coskew", "max_return", "up_day")),
    ("drawdown", ("drawdown", "mdd")),
    (
        "momentum and trend",
        ("momentum", "mom", "trend", "sma_distance", "autocorr", "cumret")
        + ("ac", "m", "ret", "return", "roc"),
    ),
    (
        "volatility and beta",
        ("volatil", "vol", "semivariance", "std", "stdev", "rv")
        + ("market_beta", "downside_beta", "btc_beta"),
    ),
    ("range and compression", ("range",)),
    ("volume level and trend", ("volume", "dollar_volume", "turnover", "vt", "ldv")),
    ("VWAP distance", ("vwap", "volume_weighted_average_price", "clv", "close_location")),
)
# Short or generic abbreviations classify only with a window (m20, hp126, ret_60d), so math
# symbols in a variable list (m(t) a month start, m_s the market return, ret_{i,t}) never do.
WINDOW_ONLY = frozenset({"m", "hp", "vt", "ac", "rv", "ldv", "ret", "return", "roc"})
# A mix or learned model over several features. Prose may identify a mix; it never classifies.
COMPOSITE = re.compile(
    r"\b(?:composite|ensemble|ml|machine learning|ridge|lasso|elastic net|gradient boost\w*|"
    r"random forest|neural|lightgbm|lgbm|xgboost|catboost|gbm|gbdt|pca|principal component\w*|"
    r"linear combination|logistic mix|weighted (?:sum|average|combination)|"
    r"(?:combination|blend|mix) of|"
    r"multi factor)\b"
)
# A regression is one construct (price delay, a lag slope) unless it lists two known features.
WEAK_COMPOSITE = re.compile(r"\b(?:regress\w*|ols)\b")


def name_tokens(name: str) -> list[str]:
    """Lower-case tokens of a name, a window number attached to letters removed (vol60 -> vol)."""
    return [
        re.sub(r"(?<=[a-z])\d+$", "", token) for token in re.findall(r"[a-z0-9]+", name.lower())
    ]


def name_matches(name: str) -> list[str]:
    """Every family whose keyword a name contains, in table order; estimator words never match."""
    raw = re.findall(r"[a-z0-9]+", name.lower())
    tokens = name_tokens(name)
    keywords = sorted(
        ((word.split("_"), family) for family, words in FAMILY_KEYWORDS for word in words),
        key=lambda pair: (-len(pair[0]), -len("".join(pair[0]))),
    )
    matched: set[str] = set()
    consumed: set[int] = set()
    for keyword, family in keywords:
        last = len(keyword) - 1
        for start in range(len(tokens) - last):
            span = tokens[start : start + last + 1]
            if set(range(start, start + last + 1)) & consumed or span[:last] != keyword[:last]:
                continue
            tail = keyword[last]
            if not (span[last] == tail or len(tail) >= 4 and span[last].startswith(tail)):
                continue
            if "_".join(keyword) in WINDOW_ONLY and not (
                raw[start] != tokens[start]
                or start + 1 < len(raw)
                and re.fullmatch(r"\d+[a-z]{0,2}", raw[start + 1])
            ):
                continue
            matched.add(family)
            consumed.update(range(start, start + last + 1))
    return [family for family, _ in FAMILY_KEYWORDS if family in matched]


def input_families(*names: str) -> set[str]:
    """Each named input contributes one family, including unfamiliar constructs."""
    return {name_family(name) for name in names}


def name_family(name: str) -> str:
    found = name_matches(name)
    if found:
        return found[0]
    tokens = name_tokens(name)
    while tokens and re.fullmatch(r"(?:skip)?\d+[a-z]*", tokens[-1]):
        tokens.pop()
    return "other: " + "_".join(tokens or name_tokens(name) or ["unnamed"])


# Indexed math symbols and estimator settings are not features.
SYMBOLS = frozenset(
    [
        "alpha",
        "beta",
        "gamma",
        "delta",
        "epsilon",
        "theta",
        "lambda",
        "mu",
        "sigma",
        "tau",
        "phi",
        "psi",
        "omega",
        "rho",
        "eta",
        "kappa",
        "nu",
        "xi",
        "pi",
        "zeta",
        "iota",
        "chi",
        "upsilon",
        "omicron",
        "ret",
        "return",
    ]
)
SETTINGS = frozenset({"max_depth", "num_leaves", "learning_rate", "rank_t"})
PLACEHOLDER = re.compile(r"(?:x|f|feat|feature|z)_?\d+(?:_[a-z])*$")


def input_names(variables: Any) -> list[str]:
    entries = (
        variables.items()
        if isinstance(variables, dict)
        else (((key, "") for key in variables) if isinstance(variables, (list, tuple)) else [])
    )
    names: list[str] = []
    for key, value in entries:
        key = str(key).lower()
        if PLACEHOLDER.fullmatch(key):
            candidates = re.findall(r"\b[a-zA-Z][a-zA-Z0-9_]*\b", str(value))
            candidates = [n for n in candidates if "_" in n or any(c.isdigit() for c in n)]
        else:
            candidates = [key]
        for candidate in candidates:
            # LaTeX indices, or plain one-letter index suffixes, do not name a construct.
            stem = re.sub(r"_?\{.*$|\(.*$", "", candidate.lower()).strip("\\")
            stem = re.sub(r"(?:_[a-z])+$", "", stem)
            if (
                not re.search(r"[a-z]", stem)
                or len(stem) == 1
                or stem in SYMBOLS | SETTINGS
                or PLACEHOLDER.fullmatch(stem)
            ):
                continue
            if stem not in names:
                names.append(stem)
    return names


def idea_family(
    name: str, description: str = "", formulation: str = "", variables: Any = None
) -> str:
    """Only names classify; prose may identify a composite but never its mechanism."""
    listed = input_names(variables)
    inputs = input_families(*listed)
    text = " ".join(re.findall(r"[a-z0-9]+", f"{name} {description}".lower()))
    text = text.replace("volume weighted average price", "vwap")
    if COMPOSITE.search(text) or (WEAK_COMPOSITE.search(text) and len(inputs) >= 2):
        return "; ".join(sorted(inputs)) or "composite: unknown inputs"
    return name_family(name)


def recorded_status(row: dict[str, Any]) -> str:
    """Old candidate rows retain their bytes, but a recorded failed deflation rejects them."""
    trial = row.get("clocks", {}).get(row.get("lead_clock", "daily"), row)
    result = trial.get("replay", {}).get("deflated_sharpe", {})
    if (
        row["status"] == "CANDIDATE"
        and result.get("dsr") is not None
        and result.get("threshold") is not None
        and result["dsr"] < result["threshold"]
    ):
        return "DEFLATION_FAIL"
    return str(row["status"])
