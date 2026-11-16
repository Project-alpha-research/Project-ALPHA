"""Heuristic checking of visible draft numbers; no claim about reasoning quality."""

from __future__ import annotations

import re
from collections.abc import Callable
from decimal import ROUND_HALF_EVEN, Decimal, localcontext
from typing import Any

from alpha_cli.spine.compare import Fact, Lookup, derived_fact, numeric_fact
from alpha_cli.spine.errors import SpineError

FlagLookup = Callable[[str], list[dict[str, str]]]
THRESHOLDS = {"dsr": 0.95, "trial_dsr": 0.95}
CONTRADICTIONS = {
    "*": (
        r"\bno (?:(?:warning|red|major|serious|significant) )?flags?\b|\bno warnings\b"
        r"|\bnothing (?:was )?flagged\b|\bzero (?:(?:warning|red) )?flags\b"
        r"|\bwithout (?:any )?(?:(?:warning|red) )?flags\b|\bflag free\b"
    ),
    "below-benchmark": (
        r"\b(?:beat|beats|outperformed|outperforms) (?:the )?(?:benchmark|buy and hold)\b"
    ),
    **{
        f"fragile-to-{kind}": r"\b(?:robust|insensitive|held up|holds up|unaffected)\b[^.\n]{0,40}"
        + suffix
        for kind, suffix in (
            ("costs", r"\bcosts?\b"),
            ("parameters", r"\b(?:parameters?|settings)\b"),
            ("delay", r"\bdelay"),
        )
    },
    "concentrated-profit": r"\b(?:spread|evenly|broad)\b[^.\n]{0,40}\btrades\b",
    "drawdown-with-market": r"\b(?:unrelated to|independent of) (?:the )?market\b",
}
_FINANCIAL = re.compile(
    r"\b(?:sharpe|dsr|cagr|returns?|drawdowns?|beta|exposure|profits?|volatility)\b",
    re.IGNORECASE,
)

# Required plain phrases (case insensitive; a hyphen also counts as a space).
LABEL_PHRASES = {
    "quick": "quick",
    "source-defaulted": "source defaulted",
    "short-history": "short history",
    "no-diagnostics": "no diagnostics",
}
_TAG = re.compile(
    r"\[([0-9a-fA-F]{8,16})(?:~([0-9a-fA-F]{8,16}))?:([A-Za-z_]\w*)(?::(diff|ratio))?\]"
)
_NUMBER = re.compile(r"(?<![\w.])[+-]?\d+(?:,\d{3})*(?:\.\d+)?(?:%|x|×)?(?!\w)")
_IGNORED = re.compile(
    r"\b\d{4}-\d{2}-\d{2}\b|\b\d{1,2}:\d{2}(?::\d{2}(?:\.\d+)?)?\b|"
    r"\b\d{1,2}\s+(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|"
    r"Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)\s+\d{4}\b|"
    r"(?<![\w.,])(?:0x[\da-f]+|[\da-f]{16,}|(?=[\da-f]*[a-f])[\da-f]{8,})(?![\w.,%×])|"
    r"(?m:^[ \t]*(?:\#{1,6}[ \t]+)?\d+[.)](?=\s))",
    re.IGNORECASE,
)


def _blank(match: re.Match[str]) -> str:
    return re.sub(r"[^\n]", " ", match.group())


def visible_text(text: str) -> str:
    """Mask fenced and inline code without moving any line or character offsets."""
    lines = []
    fence = ""
    for line in text.splitlines(keepends=True):
        marker = re.match(r"^ {0,3}(`{3,}|~{3,})", line)
        if fence:
            lines.append(re.sub(r"[^\n]", " ", line))
            if (
                marker
                and marker[1][0] == fence[0]
                and len(marker[1]) >= len(fence)
                and not line[marker.end() :].strip()
            ):
                fence = ""
        elif marker:
            fence = marker[1]
            lines.append(re.sub(r"[^\n]", " ", line))
        else:
            lines.append(line)
    return re.sub(r"(`+)(?!`)(.*?)(?<!`)\1(?!`)", _blank, "".join(lines), flags=re.DOTALL)


def _problem(
    text: str,
    offset: int,
    kind: str,
    message: str,
    *,
    stored: Any = None,
    known: list[str] | None = None,
    next_step: str = "Run alpha results cite and correct the draft.",
) -> Fact:
    line = text.count("\n", 0, offset) + 1
    return {
        "line": line,
        "excerpt": text.splitlines()[line - 1],
        "kind": kind,
        "message": message,
        "stored": stored,
        "known": known,
        "next": next_step,
    }


def _match_value(written: str, fact: Fact) -> tuple[str, str, Any] | None:
    fact = numeric_fact(fact)
    if fact["value"] is None:
        return "VALUE_NOT_COMPUTED", f"The record has no numeric value: {fact['reason']}", fact
    number = written.rstrip("%x×").replace(",", "")
    decimals = len(number.partition(".")[2])
    with localcontext() as context:
        context.prec = max(50, len(number) + 330)
        value = Decimal(str(fact["value"])) * (100 if written.endswith("%") else 1)
        rounded = value.quantize(Decimal(1).scaleb(-decimals), rounding=ROUND_HALF_EVEN)
    if rounded != Decimal(number):
        return (
            "VALUE_MISMATCH",
            f"Written {written}; stored {fact['value']}; at written precision {rounded}.",
            {"value": fact["value"], "rounded": str(rounded)},
        )
    threshold = THRESHOLDS.get(fact.get("metric", ""))
    stated = Decimal(number) / (100 if written.endswith("%") else 1)
    if threshold is not None and Decimal(str(fact["value"])) < Decimal(str(threshold)) <= stated:
        return (
            "ROUNDED_ACROSS_THRESHOLD",
            f"Stored {fact['value']} is below the pass line {threshold}; written {written} "
            "reads as passing. Write at least three decimals.",
            {"value": fact["value"], "threshold": threshold},
        )
    return None


def _financial_context(visible: str, number: re.Match[str]) -> bool:
    before = visible[visible.rfind("\n", 0, number.start()) + 1 : number.start()]
    return any(len(before) - word.end() <= 40 for word in _FINANCIAL.finditer(before)) or bool(
        re.match(
            r"\s+(?:trades?|percent|per cent|bps|basis points)\b",
            visible[number.end() :],
            re.IGNORECASE,
        )
    )


def _flag_problems(
    text: str, phrases: str, run_id: str, flags: FlagLookup, others: list[str]
) -> list[Fact]:
    problems = []
    stored_flags = flags(run_id)
    offset = 0
    for sentence in re.split(r"(?<=[.!?])\s+|\n", phrases):
        start = phrases.find(sentence, offset)
        offset = start + len(sentence)
        if run_id[:8] not in sentence and any(other[:8] in sentence for other in others):
            continue  # the sentence names a different cited run, so it is not about this one
        denied = re.search(CONTRADICTIONS["*"], sentence)
        negated = re.search(r"\b(?:not|never|no longer|failed to)\b|n't", sentence)
        seen = set()
        for flag in stored_flags:
            code = flag["flag"]
            pattern = CONTRADICTIONS.get(code)
            if code not in seen and (
                denied or (not negated and pattern and re.search(pattern, sentence))
            ):
                seen.add(code)
                problems.append(
                    _problem(
                        text,
                        start,
                        "FLAG_CONTRADICTED",
                        f"Run {run_id} carries the flag {code}: {flag['detail']}",
                        stored=code,
                        next_step="Report the flag in plain words; do not contradict it.",
                    )
                )
    return problems


def check_text(
    text: str, lookup: Lookup, allow_untagged: int = 0, flags: FlagLookup | None = None
) -> Fact:
    if allow_untagged < 0:
        raise ValueError("allow_untagged must be non-negative")
    visible = visible_text(text).replace("−", "-")
    scanned = _IGNORED.sub(_blank, _TAG.sub(_blank, visible))
    problems: list[Fact] = []
    warnings: list[Fact] = []
    cited: dict[str, tuple[Fact, int]] = {}
    checked = 0
    trial_count = False
    for number in _NUMBER.finditer(scanned):
        written = number.group()
        suffix = visible[number.end() :]
        tag = _TAG.match(suffix, len(suffix) - len(suffix.lstrip(" \t")))
        if tag is None and re.fullmatch(r"\+?\d+", written):
            integer = int(written)
            if 1900 <= integer <= 2100 or (
                0 <= integer <= 10 and not _financial_context(_TAG.sub(_blank, visible), number)
            ):
                continue
        checked += 1
        if tag is None:
            problem = _problem(
                text, number.start(), "UNTAGGED_NUMBER", f"Number {written} has no citation tag."
            )
            (warnings if len(warnings) < allow_untagged else problems).append(problem)
            continue
        first, second, metric, operation = tag.groups()
        try:
            base = lookup(first, metric)
            cited.setdefault(base["run_id"], (base, number.start()))
            fact = base
            if second and operation:
                other = lookup(second, metric)
                cited.setdefault(other["run_id"], (other, number.start()))
                fact = derived_fact(base, other, operation)
            elif second or operation:
                problems.append(
                    _problem(
                        text,
                        number.start(),
                        "UNTAGGED_NUMBER",
                        "Incomplete comparison tag; use [base~run:metric:diff] or :ratio.",
                    )
                )
                continue
            mismatch = _match_value(written, fact)
            if mismatch:
                kind, message, stored = mismatch
                step = f"Run alpha results cite {first} {metric} and copy its value."
                problems.append(
                    _problem(text, number.start(), kind, message, stored=stored, next_step=step)
                )
            elif metric == "total_trials" and second is None:
                trial_count = True
        except SpineError as exc:
            error = exc.payload
            problems.append(
                _problem(
                    text,
                    number.start(),
                    error["code"],
                    str(exc),
                    known=error["known"],
                    next_step=error["next"],
                )
            )
    phrases = _TAG.sub(_blank, visible).lower().replace("-", " ")
    for run_id, (fact, offset) in cited.items():
        if flags is not None:
            others = [other for other in cited if other != run_id]
            problems.extend(_flag_problems(text, phrases, run_id, flags, others))
        for label in fact.get("labels", []):
            phrase = LABEL_PHRASES.get(label)
            if phrase and not re.search(r"\b" + re.escape(phrase) + r"\b", phrases):
                problems.append(
                    _problem(
                        text,
                        offset,
                        "LABEL_OMITTED",
                        f"Run {run_id} requires the phrase {phrase!r}.",
                        stored=label,
                        next_step=f"Add the phrase {phrase!r} to the draft.",
                    )
                )
    if cited and not trial_count:
        offset = next(iter(cited.values()))[1]
        problems.append(
            _problem(
                text,
                offset,
                "TRIAL_COUNT_OMITTED",
                "No matched, tagged total_trials fact is stated.",
                next_step="Run alpha results cite <run_id> total_trials and tag its value.",
            )
        )
    return {
        "ok": not problems,
        "checked_numbers": checked,
        "problems": problems,
        "warnings": warnings,
        "cited_runs": list(cited),
    }


def render_check(result: Fact) -> str:
    lines = [
        f"{'OK' if result['ok'] else 'FAILED'}: checked {result['checked_numbers']} number(s)."
    ]
    for level in ("problems", "warnings"):
        for problem in result[level]:
            lines.append(
                f"{level}: line {problem['line']} {problem['kind']}: {problem['message']} "
                f"Excerpt: {problem['excerpt']} Next: {problem['next']}"
            )
    lines.append("This heuristic checks tagged numbers, labels and flags, not the reasoning.")
    return "\n".join(lines)
