"""Construct-name classification for ALPHA proposals; no prose inference."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
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
# single name's family when it matches several; funding comes first, so a funding construct
# (funding_momentum_7d) is never filed under a price family.
FAMILY_KEYWORDS = (
    ("futures funding", ("funding", "carry", "basis", "perp")),
    (
        "price near its high / range position",
        ("high_prox", "near_high", "distance_to_high", "stoch", "rangepos", "range_position", "hp"),
    ),
    (
        "intraday return and gaps",
        ("gap", "gaps", "intraday_reversal"),
    ),
    ("illiquidity", ("amihud", "illiquid")),
    ("return-volume relation", ("ret_vol_corr", "volume_return", "signed_volume", "flow_conf")),
    ("skewness and lottery returns", ("skew", "coskew", "max_return", "up_day")),
    ("drawdown", ("drawdown", "mdd")),
    (
        "past return (momentum or reversal)",
        (
            "reversal_3d",
            "reversal_5d",
            "short_term_reversal",
            "long_term_reversal",
            "ltr",
            "momentum",
            "mom",
            "trend",
            "sma_distance",
            "autocorr",
            "cumret",
        )
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
# Keep these existing unknown-construct identities and their ledger counts intact.
SESSION_FAMILIES = frozenset(
    {"other: overnight_drift", "other: intraday_drift", "other: overnight_minus_intraday"}
)


def offered_families(families: set[str], source: str | None) -> set[str]:
    """Session splits are not useful open suggestions for midnight-to-midnight crypto bars."""
    return families - SESSION_FAMILIES if source == "binance-spot" else families


def universe_source(run: str | None) -> str | None:
    """Read available frozen source metadata; a missing binding or a changed file fails loud.

    Family refusal can run before panel setup. No source metadata means no market filter;
    old frozen receipts without a universe file used Binance spot.
    """
    if run is None:
        return None
    root = Path(run) / "panel"
    path, receipt_path = root / "universe.json", root / "panel-receipt.json"
    if not path.exists() and not receipt_path.exists():
        return None
    receipt = json.loads(receipt_path.read_bytes())
    spec = json.loads(path.read_bytes()) if path.exists() else None
    if "universe_sha256" in receipt:
        canonical = (json.dumps(spec, sort_keys=True, separators=(",", ":")) + "\n").encode()
        if spec is None or hashlib.sha256(canonical).hexdigest() != receipt["universe_sha256"]:
            raise ValueError("universe file differs from the frozen receipt")
    source = spec.get("source") if spec is not None else "binance-spot"
    if source is not None and not isinstance(source, str):
        raise ValueError("universe source must be a string")
    return source


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
    tokens = [
        t
        for t in name_tokens(name)
        if t not in {"negative", "neg", "inverse", "inverted", "positive"}
    ]
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
SETTINGS = frozenset(
    {"max_depth", "num_leaves", "learning_rate", "rank_t", "reg_lambda", "reg_alpha"}
)
# An unrecognised name is a feature only if it reads like one. These are not: names led by an
# index letter (r_1, b_0, y_raw, l2_penalty, n_estimators), by a LaTeX or operator word (tilde_x,
# max_iter, rolling_20d), estimator settings, and one short or generic word (SSR, SST, var, rank).
OPERATOR_WORDS = frozenset(
    {"tilde", "hat", "bar", "frac", "left", "right", "cdot", "ln", "log", "exp", "sqrt", "sum"}
    | {"prod", "max", "min", "mathbb", "mathrm", "operatorname", "text", "rolling", "target"}
)
SETTING_WORDS = frozenset(
    {"iter", "iterations", "estimators", "samples", "leaf", "leaves", "depth", "regularization"}
    | {"subsample", "colsample", "bytree", "refit", "frequency", "epochs", "seed", "penalty"}
    | {"intercept"}
)
# A generic placeholder key (x1, x_2, f3, feat1, feature_4, z1, x1_i_s) names its input in its
# value.
PLACEHOLDER = re.compile(r"(?:x|f|feat|feature|z)_?\d+$")


def _stem(raw: str) -> str | None:
    """A key or token without LaTeX indices, exponents or one-letter subscripts, else None."""
    if raw.strip().startswith("\\"):
        return None  # a LaTeX command (beta, hat y, frac): never a feature name
    stem = re.sub(r"_?\{.*$|\(.*$|\^.*$|_[^_,]*,.*$", "", raw.strip().lower())
    stem = re.sub(r"(?:_[a-z])+$", "", stem)
    return stem if re.fullmatch(r"[a-z][a-z0-9_]*", stem) else None


def _is_input(stem: str) -> bool:
    if name_matches(stem):
        return True  # a keyword-recognised feature is always an input, whatever it looks like
    tokens = stem.split("_")
    words = [t for t in name_tokens(stem) if not re.fullmatch(r"(?:skip)?\d+[a-z]*", t)]
    return bool(
        words
        and not re.fullmatch(r"[a-z]\d*", tokens[0])
        and stem not in SYMBOLS | SETTINGS
        and tokens[0] not in OPERATOR_WORDS | SYMBOLS
        and not set(words) & SETTING_WORDS
        and not (len(words) == 1 and (len(words[0]) < 4 or words[0] in GENERIC_ESTIMATOR_WORDS))
    )


def read_inputs(variables: Any) -> tuple[list[str], list[str]]:
    """Named inputs of a variable list, and placeholder keys whose value names no input."""
    entries = (
        variables.items()
        if isinstance(variables, dict)
        else (((key, "") for key in variables) if isinstance(variables, (list, tuple)) else [])
    )
    names: list[str] = []
    unreadable: list[str] = []
    for key, value in entries:
        stem = _stem(str(key))
        if stem is None:
            continue
        if PLACEHOLDER.fullmatch(stem):
            tokens = re.findall(r"\b[a-zA-Z][a-zA-Z0-9_]*\b", str(value))
            found = [
                s
                for t in tokens
                if ("_" in t or any(c.isdigit() for c in t))
                and (s := _stem(t)) is not None
                and _is_input(s)
            ]
            if not found:
                unreadable.append(str(key))
        else:
            found = [stem] if _is_input(stem) else []
        names.extend(name for name in found if name not in names)
    return names, unreadable


def input_names(variables: Any) -> list[str]:
    return read_inputs(variables)[0]


UNKNOWN = "composite: unknown inputs"


def idea_family(
    name: str, description: str = "", formulation: str = "", variables: Any = None
) -> str:
    """Only names classify; prose may identify a composite but never its mechanism.

    A composite takes the families of its name and of every named input (an unrecognised one is
    its own ``other:`` family). It is ``composite: unknown inputs`` when it names no input, and
    also carries that family when a placeholder input's value names none, so an unnamed input
    cannot hide a closed family's feature. A regression is one construct unless it lists two
    keyword-recognised features. The formulation never classifies.
    """
    listed, unreadable = read_inputs(variables)
    # Every family a recognised input's name matches, as for a single name's keywords.
    inputs = {f for item in listed for f in name_matches(item) or [name_family(item)]}
    known = {found[0] for item in listed if (found := name_matches(item))}
    text = " ".join(re.findall(r"[a-z0-9]+", f"{name} {description}".lower()))
    text = text.replace("volume weighted average price", "vwap")
    if COMPOSITE.search(text) or (WEAK_COMPOSITE.search(text) and len(known) >= 2):
        families = inputs | set(name_matches(name))
        if unreadable or not families:
            families.add(UNKNOWN)
        return "; ".join(sorted(families))
    return name_family(name)


def task_family(task: Any) -> str:
    return idea_family(
        task.factor_name,
        getattr(task, "description", "") or "",
        getattr(task, "factor_formulation", "") or "",
        getattr(task, "variables", None),
    )


def recorded_status(row: dict[str, Any]) -> str:
    """Old candidate rows retain their bytes, but a recorded failed deflation rejects them."""
    trial = row.get("clocks", {}).get(row.get("lead_clock", "daily"), row)
    result = trial.get("replay", {}).get("deflated_sharpe", {})
    if (
        row["status"] == "CANDIDATE"
        and result.get("dsr") is not None
        and result.get("threshold") is not None
        and not result["dsr"] >= result["threshold"]
    ):
        return "DEFLATION_FAIL"
    return str(row["status"])


def family_failure_counts(rows: list[dict[str, Any]]) -> dict[str, int]:
    """Use the closure's statuses and first distinct factor rows, excluding candidates."""
    distinct: dict[str, dict[str, Any]] = {}
    for row in rows:
        if row.get("schema") in {
            "AlphaRdagentFactorTrialV1",
            "AlphaRdagentFactorTrialV2",
            "AlphaRdagentFactorTrialV3",
        } and row["status"] not in {"REPEAT", "IMPORTED"}:
            distinct.setdefault(row["code_sha256"], row)
    counts: dict[str, int] = {}
    for row in distinct.values():
        if recorded_status(row) not in {
            "SCREEN_FAIL",
            "SPREAD_FAIL",
            "REPLAY_FAIL",
            "FAST_ONLY",
            "DEFLATION_FAIL",
        }:
            continue
        for family in idea_family(
            row["name"],
            row.get("description") or "",
            row.get("formulation") or "",
            row.get("variables"),
        ).split("; "):
            counts[family] = counts.get(family, 0) + 1
    return counts


DECLARATION_MESSAGE = (
    "Add declared_direction: +1 or -1; primary_clock: weekly or monthly; "
    "direction_reason: one non-empty sentence of economic reasoning to each factor description."
)


def declaration(description: str) -> dict[str, Any]:
    """Explicit, labelled description fields survive upstream's fixed FactorTask schema."""
    # A field ends at ; , . or a line end, so "+1 or -1" or "weekly or monthly" never parse.
    end = r"\s*(?:[;,.\n]|$)"
    direction = re.search(r"\bdeclared_direction\s*[:=]\s*([+\-\u2212]?1)" + end, description)
    clock = re.search(r"\bprimary_clock\s*[:=]\s*(weekly|monthly)" + end, description, re.I)
    reason = re.search(r"\bdirection_reason\s*[:=]\s*([^;\n]+)", description)
    if not direction or not clock or not reason or not reason.group(1).strip():
        raise ValueError(DECLARATION_MESSAGE)
    return {
        "declared_direction": int(direction.group(1).replace("\u2212", "-")),
        "primary_clock": clock.group(1).lower(),
        "direction_reason": reason.group(1).strip(),
    }


def row_families(row: dict[str, Any]) -> list[str]:
    return (
        row["family"]
        if "family" in row
        else idea_family(
            row["name"],
            row.get("description") or "",
            row.get("formulation") or "",
            row.get("variables"),
        )
    ).split("; ")


def mentions_family(text: str, families: set[str]) -> bool:
    """Match named families and construct names despite case, spacing or window suffixes."""
    normalized = " " + re.sub(r"[^a-z0-9]+", " ", text.lower()) + " "
    for family in families:
        name = family.removeprefix("other: ")
        words = re.sub(r"[^a-z0-9]+", " ", name.lower()).strip()
        if " " + words + " " in normalized:
            return True
    return False


def count_note(family: str, count: int, limit: int | None, closed: bool) -> str:
    if limit is not None and count > limit:
        return (
            f"failed tries in this idea family ({family}): "
            + ("closed: " if closed else "")
            + f"{count} failed tries (limit {limit})"
        )
    return f"failed tries in this idea family ({family}): {count} of the limit {limit}"


def hidden_families(source: str | None) -> set[str]:
    return set(SESSION_FAMILIES) - offered_families(set(SESSION_FAMILIES), source)


def suggestion_reason(text: str, closed: set[str], hidden: set[str]) -> str | None:
    if mentions_family(text, hidden):
        return "Dropped suggestion because its family is not offered on this venue."
    if mentions_family(text, closed) or closed.intersection(name_matches(text)):
        return "Dropped suggestion because its family is closed."
    return None


def filter_history(text: str, hidden: set[str], closed: set[str]) -> str:
    lines: list[str] = []
    for line in text.split("\n"):
        if mentions_family(line, hidden):
            line = "Dropped earlier text because its family is not offered on this venue."
        elif re.search(
            r"\b(?:try|propose|explore|suggest|recommend|next hypothesis)\b", line, re.I
        ):
            line = suggestion_reason(line, closed, hidden) or line
        if not (line.startswith("Dropped ") and lines and lines[-1] == line):
            lines.append(line)
    return "\n".join(lines)


def closed_groups(groups: dict[str, list[dict[str, Any]]], limit: int) -> set[str]:
    return {
        name
        for name, members in groups.items()
        if len(members) >= limit and not any(m["status"] == "CANDIDATE" for m in members)
    }
