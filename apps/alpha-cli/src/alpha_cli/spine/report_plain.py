"""The plain one-screen summaries ``alpha report`` and ``alpha diagnose`` print by default.

Only arranges numbers a run stored; prints a sentence for each thing that was checked. A value that
was not stored gives no line: this module never prints a field name, ``None`` or a letter grade.
``--json`` keeps the full machine output. The stored files are never changed.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from typing import Any

from alpha_cli.spine.reading import plain, reading_word


def _num(value: Any) -> float | None:
    ok = isinstance(value, int | float) and not isinstance(value, bool) and math.isfinite(value)
    return float(value) if ok else None


def _map(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _pct(value: Any, digits: int = 1) -> str | None:
    number = _num(value)
    return None if number is None else f"{number * 100:.{digits}f}%"


def _x(value: Any) -> str | None:
    number = _num(value)
    return None if number is None else f"{number:.2f}"


def _sentence(text: str) -> str:
    return text if text.endswith((".", "!", "?")) else f"{text}."


def reading_sentence(manifest: Mapping[str, Any], found: Mapping[str, Any] | None) -> str:
    """``Reading: <word>.`` plus the stored caveat sentence, when the run has one."""
    text = f"Reading: {reading_word(found) if found else 'not recorded'}."
    verdict = _map(manifest.get("verdict"))
    if verdict.get("labels") and verdict.get("sentence"):
        text += f" {_sentence(str(verdict['sentence']))}"
    return text


def _result_line(metrics: Mapping[str, Any]) -> str | None:
    parts = [
        (label, text)
        for label, text in (
            ("Sharpe ratio", _x(metrics.get("sharpe"))),
            ("yearly return", _pct(metrics.get("cagr"))),
            ("worst drop", _pct(metrics.get("max_drawdown"))),
            ("yearly swing", _pct(metrics.get("annualized_vol"))),
        )
        if text is not None
    ]
    if not parts:
        return None
    return "On data the rule had not seen: " + ", ".join(f"{a} {b}" for a, b in parts) + "."


def _luck_line(manifest: Mapping[str, Any]) -> str | None:
    shares = [_num(_map(tier).get("p_value")) for tier in manifest.get("nulls") or []]
    known = [s for s in shares if s is not None]
    if not known:
        return None
    return (
        f"Random-data check: random prices did as well as the rule in up to {_pct(max(known), 0)} "
        "of draws, in the weakest of the checks. The higher this share, the more chance explains."
    )


def _range_line(manifest: Mapping[str, Any]) -> str | None:
    found = next((c for c in manifest.get("cis") or [] if _map(c).get("metric") == "sharpe"), None)
    low, high = _num(_map(found).get("lower")), _num(_map(found).get("upper"))
    point = _num(_map(found).get("point"))
    if low is None or high is None:
        return None
    where = "above zero" if low > 0 else "below zero" if high < 0 else "across zero"
    lead = f"the Sharpe ratio is {_x(point)}, and" if point is not None else "the Sharpe ratio"
    return f"Range check: {lead} its likely range is {low:.2f} to {high:.2f}, which is {where}."


def _deflated_line(manifest: Mapping[str, Any]) -> str | None:
    block = _map(manifest.get("dsr"))
    value = _x(block.get("dsr"))
    if value is None:
        return None
    return (
        f"Luck adjustment: the Sharpe ratio, adjusted for the ideas tried, scores {value} "
        "on a scale from 0 to 1."
    )


def _folds_line(manifest: Mapping[str, Any]) -> str | None:
    block = _map(manifest.get("cpcv"))
    mean, share = _x(block.get("mean_sharpe")), _pct(block.get("frac_positive"), 0)
    if mean is None or share is None:
        return None
    return (
        f"Split check: the mean Sharpe ratio over the test splits is {mean}; {share} of the "
        "splits are above zero."
    )


def _folds_count(manifest: Mapping[str, Any]) -> str | None:
    folds = manifest.get("folds")
    if not folds:
        return None
    noun = "period" if len(folds) == 1 else "periods"
    return f"Walk-forward: the rule was scored on {len(folds)} later {noun}, one after another."


def run_symbol(manifest: Mapping[str, Any]) -> str | None:
    symbol = _map(manifest.get("metadata")).get("symbol") or manifest.get("symbol")
    return symbol if isinstance(symbol, str) else None


def _count_paragraph(symbol: str | None, diagnostics: Mapping[str, Any] | None) -> str | None:
    """The one paragraph about the counts, the same as `alpha test` prints."""
    from alpha_cli.spine.tries import reading_count_sentence

    family = _map(_map(diagnostics).get("trials")).get("family")
    if not isinstance(family, Mapping) or symbol is None:
        return None
    return reading_count_sentence(dict(family), symbol)


def plain_report_lines(
    manifest: Mapping[str, Any],
    found: Mapping[str, Any] | None,
    diagnostics: Mapping[str, Any] | None = None,
) -> list[str]:
    """The summary of a stored gauntlet run: what was checked, the number, one sentence each."""
    spine = _map(manifest.get("spine"))
    costs = _map(spine.get("costs")).get("line")
    lines = [
        reading_sentence(manifest, found),
        _result_line(_map(manifest.get("oos_metrics"))),
        _folds_count(manifest),
        _luck_line(manifest),
        _range_line(manifest),
        _deflated_line(manifest),
        _count_paragraph(run_symbol(manifest), diagnostics),
        _folds_line(manifest),
        costs if isinstance(costs, str) else None,
    ]
    return [line for line in lines if line]


WARNINGS_HEAD = "Warnings recorded with this run:"
_CHECKS = {
    "fills-after-decisions": "Every fill came after its decision",
    "fills-inside-bar-range": "Every fill sits inside its bar's price range",
    "costs-charged": "Costs were charged",
    "enough-trades": "Enough closed trades",
    "benchmark-present": "The buy-and-hold comparison exists",
    "history-length": "Enough years of prices",
    "artifacts-intact": "Stored files are intact",
    "quick-run": "Full-size run",
    "variants-counted": "Nearby settings were counted",
}
_STATUS = {"PASS": "ok", "FLAG": "look closer", "NOT-CHECKED": "not checked"}


def _audit_lines(output: Mapping[str, Any]) -> list[str]:
    lines = []
    for item in output.get("audit") or []:
        item = _map(item)
        check = str(item.get("check") or "")
        status = _STATUS.get(str(item.get("status")))
        detail = item.get("detail")
        if not check or status is None or not isinstance(detail, str):
            continue
        name = _CHECKS.get(check, check.replace("-", " ").capitalize())
        lines.append(f"  {status}: {name}. {_sentence(detail)}")
    return lines


def _versus_buy_and_hold(output: Mapping[str, Any]) -> str | None:
    rule = _pct(_map(output.get("full_sample")).get("total_return"))
    bench = _pct(_map(output.get("benchmark")).get("total_return"))
    if rule is None or bench is None:
        return None
    return (
        f"Against buy and hold: the rule returned {rule} in total; buy and hold returned {bench}."
    )


def _delay_line(output: Mapping[str, Any]) -> str | None:
    block = _map(output.get("delay"))
    base, late, kept = (
        _x(block.get("base_sharpe")),
        _x(block.get("delayed_sharpe")),
        _pct(block.get("delayed_share_of_base"), 0),
    )
    if base is None or late is None or kept is None:
        return None
    return (
        f"One bar later: acting one bar late moves the Sharpe ratio from {base} to {late} "
        f"({kept} kept)."
    )


def _concentration_line(output: Mapping[str, Any]) -> str | None:
    block = _map(output.get("concentration"))
    best, top3 = _pct(block.get("top_1"), 0), _pct(block.get("top_3"), 0)
    if best is None or top3 is None:
        return None
    return (
        f"Trade spread: the best trade made {best} of the total gain; the best three made {top3}."
    )


def _noise_line(output: Mapping[str, Any]) -> str | None:
    """Price noise, in the diagnostic pass's own sentence: its range is the middle 90% only."""
    return _stored_sentence(output, "price_noise", "Price noise")


def _flag_lines(output: Mapping[str, Any]) -> list[str]:
    """Every recorded warning with its detail, as the diagnostic pass wrote it."""
    details = [_map(f).get("detail") for f in output.get("flags") or []]
    return [f"  {_sentence(d)}" for d in details if isinstance(d, str) and d]


def _stored_sentence(output: Mapping[str, Any], key: str, lead: str) -> str | None:
    """A sentence the diagnostic pass already wrote for one check, after its plain lead."""
    sentence = _map(output.get(key)).get("sentence")
    return f"{lead}: {sentence}" if isinstance(sentence, str) and sentence else None


def _settings_line(output: Mapping[str, Any]) -> str | None:
    variants = _map(output.get("sensitivity")).get("variants")
    sharpes = [s for s in (_num(_map(v).get("sharpe")) for v in variants or []) if s is not None]
    if not sharpes:
        return None
    return (
        f"Nearby settings: {len(sharpes)} changes to costs or settings gave Sharpe ratios "
        f"from {min(sharpes):.2f} to {max(sharpes):.2f}."
    )


def plain_diagnose_lines(
    output: Mapping[str, Any], found: Mapping[str, Any], symbol: str | None = None
) -> list[str]:
    """What the diagnostic pass checked and found, in about one screen."""
    summary = [
        _versus_buy_and_hold(output),
        _delay_line(output),
        _concentration_line(output),
        _noise_line(output),
        _stored_sentence(output, "inverted_signal", "Opposite rule"),
        _stored_sentence(output, "walk_forward_efficiency", "Later periods against earlier ones"),
        _settings_line(output),
    ]
    lines = [_sentence(plain(str(found.get("sentence") or f"Reading: {reading_word(found)}")))]
    lines += [line for line in (_count_paragraph(symbol, output), *summary) if line]
    flags = _flag_lines(output)
    if flags:
        lines += [WARNINGS_HEAD, *flags]
    audit = _audit_lines(output)
    if audit:
        lines += ["Fact checks:", *audit]
    return lines
