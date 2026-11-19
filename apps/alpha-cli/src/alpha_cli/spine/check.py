"""Heuristic checking of visible draft numbers; no claim about reasoning quality."""

from __future__ import annotations

import re
from collections.abc import Callable
from typing import Any

from alpha_cli.spine.check_flags import flag_hits
from alpha_cli.spine.check_rules import financial_context, match_value, spelled_numbers, unit_kind
from alpha_cli.spine.compare import Fact, Lookup, derived_fact
from alpha_cli.spine.errors import SpineError

FlagLookup = Callable[[str], list[dict[str, str]]]

# Required plain phrases (case insensitive; a hyphen also counts as a space).
LABEL_PHRASES = {
    "quick": "quick",
    "data-health-fail": "data health fail",
    "data-health-overridden": "data health overridden",
    "data-health-unchecked": "data health unchecked",
    "source-defaulted": "source defaulted",
    "short-history": "short history",
    "no-diagnostics": "no diagnostics",
    "too-few-trades": "too few trades",
    "reserved-period-held-back": "held back",
    "reserved-period-seen": "reserved period seen",
}
_TAG = re.compile(
    r"\[([0-9a-fA-F]{8,16})(?:~([0-9a-fA-F]{8,16}))?:([A-Za-z_][\w.]*(?:@[a-f0-9]{8})?)(?::(diff|ratio))?\]"
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


def check_text(
    text: str, lookup: Lookup, allow_untagged: int = 0, flags: FlagLookup | None = None
) -> Fact:
    if allow_untagged < 0:
        raise ValueError("allow_untagged must be non-negative")
    visible = re.sub(r"(?<![\w.])\u2013(?=\d)", "-", visible_text(text).replace("\u2212", "-"))
    scanned = _IGNORED.sub(_blank, _TAG.sub(_blank, visible))
    problems: list[Fact] = []
    warnings: list[Fact] = []
    cited: dict[str, tuple[Fact, int]] = {}
    checked = 0
    trial_count = False
    settings_spans: list[tuple[int, int]] = []
    for number in _NUMBER.finditer(scanned):
        if any(start <= number.start() < end for start, end in settings_spans):
            continue
        written = number.group()
        suffix = visible[number.end() :]
        tag = _TAG.match(suffix, len(suffix) - len(suffix.lstrip(" \t")))
        if tag is None and re.fullmatch(r"\+?\d+", written):
            integer = int(written)
            if 1900 <= integer <= 2100 or (
                0 <= integer <= 10
                and not financial_context(_TAG.sub(_blank, visible), number.start(), number.end())
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
            metric = metric.partition("@")[0]
            if "settings_count" in fact:
                end = number.end() + tag.end()
                disclosure = f" (1 of {fact['settings_count']} settings tried)"
                if visible.startswith(disclosure, end):
                    settings_spans.append((end, end + len(disclosure)))
                else:
                    problems.append(
                        _problem(
                            text,
                            number.start(),
                            "SETTINGS_OMITTED",
                            f"Follow this citation with {disclosure.strip()}.",
                        )
                    )
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
            before = re.split(r"(?<=[.!?])\s+|\n", visible[: number.start()])[-1]
            mismatch = match_value(written, fact, unit_kind(metric, operation), before)
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
    for spelled in spelled_numbers(_TAG.sub(_blank, visible)):
        checked += 1
        problem = _problem(
            text,
            spelled.start(),
            "UNTAGGED_NUMBER",
            f"Number written in words ({spelled.group()!r}) cannot be checked.",
            next_step="Write the number in digits with its citation tag.",
        )
        (warnings if len(warnings) < allow_untagged else problems).append(problem)
    phrases = _TAG.sub(_blank, visible).lower().replace("-", " ")
    # The printed verdict uses a colon and distinguishes a stale report from an absent one.
    health_phrases = re.sub(r"\bdata health:\s*", "data health ", phrases)
    health_phrases = re.sub(r"\bdata health out of date\b", "data health unchecked", health_phrases)
    for run_id, (fact, offset) in cited.items():
        if flags is not None:
            others = [other for other in cited if other != run_id]
            for start, code, detail in flag_hits(phrases, run_id, flags(run_id), others):
                problems.append(
                    _problem(
                        text,
                        start,
                        "FLAG_CONTRADICTED",
                        f"Run {run_id} carries the flag {code}: {detail}",
                        stored=code,
                        next_step="Report the flag in plain words; do not contradict it.",
                    )
                )
        for label in fact.get("labels", []):
            phrase = LABEL_PHRASES.get(label)
            words = health_phrases if label.startswith("data-health-") else phrases
            if phrase and not re.search(r"\b" + re.escape(phrase) + r"\b", words):
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
