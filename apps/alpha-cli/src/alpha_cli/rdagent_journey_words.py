"""Plain-language projections of the judge's stored facts. No evaluation code runs here."""

from __future__ import annotations

import re
from typing import Any, cast

from alpha_cli._rdagent_judge import STATUSES
from alpha_cli._rdagent_stability import recorded_status
from alpha_cli.rdagent_discussion import summary_fields
from alpha_cli.spine.trial_record import universe_label

MISSING = "not recorded"
AI = "RD-Agent (AI)"
RULE = "ALPHA rule"
CLOCK = {"weekly": "7 days", "monthly": "28 days", "daily": "day"}
DIRECTION = {-1: "lower", 1: "higher"}
PEEK = {
    "PASS": "The earlier numbers did not change.",
    "LOOKAHEAD": "The earlier numbers changed when later data was hidden.",
    "UNSTABLE": "The code gave different numbers on identical inputs.",
    "ERROR": "The future-data check encountered an error.",
    "NOT_RUN": "The future-data check did not run.",
}
VERDICTS = {
    "FAILED": "The code for this idea failed to build or run.",
    "LOOKAHEAD": "It failed the future-data check.",
    "UNSTABLE": "It gave different numbers on identical inputs.",
    "DEGENERATE": "Too few usable numbers or too little variation for the quick test.",
    "ERROR": "The evaluation encountered an error.",
    "SCREEN_FAIL": "Failed the quick test.",
    "SPREAD_FAIL": "Failed the spread check.",
    "REPLAY_FAIL": "Failed the trading test with costs.",
    "CANDIDATE": (
        "It passed the quick test, spread check, trading test with costs and multiple-testing test."
    ),
    "DEFLATION_FAIL": "Failed the multiple-testing test.",
    "FAST_ONLY": (
        "Only the daily quick test, spread check and trading test with costs passed as a group."
    ),
    "REPEAT": "This idea repeated an earlier test.",
    "IMPORTED": "This result came from an earlier evaluation.",
}
EXPOSURE = {
    "known": "An earlier look at the reserved period is recorded.",
    "suspected": "An earlier look at the reserved period is suspected.",
    "unknown": "Prior exposure to the reserved period is unknown.",
    "no exposure log": "Prior exposure to the reserved period was not recorded.",
    "none": "The exposure log lists no matching earlier look.",
}
UNIVERSE = {
    "includes-delisted": "includes coins that later stopped trading",
    "survivor-universe": "contains only surviving coins",
    "universe-not-recorded": "delisted-coin coverage was not recorded",
}
SKIPS = {
    "signal": "Factor values and matching prices for one instrument were not recorded.",
    "quick-test": "Group returns by period and year were not recorded on the declared clock.",
    "over-time": "Dated rank correlations and a direction on the declared clock were not recorded.",
    "how-many-ideas": "Comparable ledger scores or this idea's pass line were not recorded.",
    "trading-test": "A costed replay was not recorded for this idea on its declared clock.",
}
NO_TRADING_TEST = "Only ideas that pass the quick test get a trading test."


def clock_of(row: dict[str, Any]) -> str | None:
    """The idea's declared clock; older records name only the lead clock."""
    return row.get("primary_clock") or row.get("lead_clock")


def trial_of(row: dict[str, Any]) -> dict[str, Any]:
    return cast(dict[str, Any], row.get("clocks", {}).get(clock_of(row), {}))


def direction_of(row: dict[str, Any]) -> int | None:
    return cast(
        int | None,
        row.get("declared_direction") or trial_of(row).get("screen", {}).get("direction"),
    )


def outcome(row: dict[str, Any]) -> str:
    if row["status"] not in STATUSES:
        raise ValueError(f"Unknown factor status {row['status']!r}")
    return VERDICTS[recorded_status(row)]


def lead_sentence(value: str) -> str:
    """The first sentence, cut at 200 characters on a word boundary."""
    first = re.split(r"\.(?:\s|$)", value.strip(), maxsplit=1)[0].strip()
    if len(first) <= 200:
        return first + "." if first else ""
    return first[:200].rsplit(" ", 1)[0].rstrip(",;:") + "…"


def idea_type(description: str) -> tuple[str, str]:
    """Split a leading bracketed tag, such as [Long-Term Reversal Factor], from the rest."""
    found = re.match(r"\s*\[([^\]]+)\]\s*", description)
    if not found:
        return "", description
    name = re.sub(r"\s*\bfactor\s*$", "", found.group(1).strip(), flags=re.I).lower()
    return name, description[found.end() :]


def display(value: float | None, percent: bool = False) -> str:
    if value is None:
        return MISSING
    return f"{value * 100:.3g}%" if percent else f"{value:.3g}"


def number(value: float | None, label: str, gloss: str, *, percent: bool = False) -> dict[str, Any]:
    return {"value": value, "display": display(value, percent), "label": label, "gloss": gloss}


def step(
    title: str,
    who: str,
    text: str,
    means: str,
    source: list[str],
    *numbers: dict[str, Any],
    **extra: Any,
) -> dict[str, Any]:
    return {
        "title": title,
        "who": who,
        "text": text,
        "numbers": list(numbers),
        "figure": None,
        "what_this_means": means,
        "source": source,
        **extra,
    }


def pass_line(row: dict[str, Any]) -> float | None:
    # The judge compares one-sided p to half the stored allocation.
    cutoff = row.get("screen_cutoff")
    return (
        cutoff / 2
        if row.get("screen_rule") == "alpha-investing-simple-1" and cutoff is not None
        else None
    )


def idea_step(row: dict[str, Any], task: dict[str, Any], sources: list[str]) -> dict[str, Any]:
    desc = task.get("description") or row.get("description") or ""
    cleaned = re.sub(
        r"(?im)\b(?:declared_direction|primary_clock|direction_reason)\s*[:=].*$", "", desc
    )
    kind, rest = idea_type(cleaned)
    summary = lead_sentence(rest)
    direction = DIRECTION.get(direction_of(row) or 0)
    clock = CLOCK.get(clock_of(row) or "")
    claim = (
        f"It expected coins with {direction} numbers to earn more over the following {clock}."
        if direction and clock
        else "The expected direction or holding period was not recorded."
    )
    if row.get("declared_direction") is None and direction:
        claim += " That direction was chosen after seeing these years, so it is not a prediction."
    sentences = [f"Idea type: {kind}." if kind else "", summary, claim]
    for source in (task, row):
        plain = source.get("plain_summary")
        if (
            isinstance(plain, str)
            and not source.get("plain_summary_status")
            and "plain_summary_status" not in summary_fields(plain)
        ):
            # The agent's own plain sentence replaces the lead taken from its description.
            sentence = plain.strip()
            sentence += "" if sentence.endswith((".", "!", "?")) else "."
            sentences = [sentence, sentences[0], claim]
            break
    return step(
        "The idea",
        AI,
        " ".join(filter(None, sentences)),
        "This is the relationship the AI expected before the test. Its full description is in "
        "its own words.",
        sources,
        own_words=desc or MISSING,
    )


def code_step(code: str, filename: str | None, sources: list[str]) -> dict[str, Any]:
    text = (
        "This is the archived factor program. The excerpt shows how it calculated the score."
        if filename
        else "The factor program was not recorded. Its calculation cannot be shown."
    )
    return step(
        "What the code calculates",
        AI,
        text,
        "The signal chart pairs one coin's price with the values the program produced.",
        sources,
        code=code,
        file=filename,
    )


def peek_step(row: dict[str, Any], sources: list[str]) -> dict[str, Any]:
    check = row.get("lookahead", {})
    status = check.get("status")
    cuts = check.get("cuts")
    verdict = PEEK[status] if status else "The future-data check result was not recorded."
    if cuts:
        count = len(cuts)
        failed = sum(c["status"] != "PASS" for c in cuts)
        dates = "date" if count == 1 else "dates"
        if status == "PASS" and not failed:
            verdict = "The earlier numbers did not change, so the code did not use future data."
        elif status == "LOOKAHEAD" and failed:
            failed_dates = "date" if failed == 1 else "dates"
            verdict = (
                f"The earlier numbers changed at {failed} {failed_dates}, "
                "so the code used future data."
            )
        elif failed:
            verdict += f" The future-data check did not pass at {failed} of those dates."
        text = f"ALPHA re-ran the idea's code with later data hidden, at {count} {dates}. {verdict}"
    else:
        text = f"{verdict} The dates checked were not recorded."
    return step(
        "Check: does it peek at the future?",
        RULE,
        text,
        "This check only covers the dates tested.",
        sources,
    )


def quick_step(row: dict[str, Any], trial: dict[str, Any], sources: list[str]) -> dict[str, Any]:
    sc = trial.get("screen", {})
    clock = CLOCK.get(clock_of(row) or "", MISSING)
    p = sc.get("p") if sc.get("status") == "OK" or "mean_ic" in sc else None
    return step(
        "Quick test",
        RULE,
        "Each period the coins were ranked by the idea's number, then the returns over the next "
        + (f"{clock} were checked. " if clock != MISSING else "period were checked. ")
        + (
            f"To pass, the chance score had to be at or below {display(pass_line(row), True)}."
            if pass_line(row) is not None
            else "The pass line was not recorded."
        ),
        "The bars show what each third earned in the next period. A rising cumulative "
        "score means the ranks tended to move in the proposed direction.",
        sources,
        number(
            sc.get("mean_ic"),
            "Rank correlation",
            "How closely the order of scores matched the order of returns.",
        ),
        number(
            p,
            "Chance score",
            "How often noise could give a result at least this strong in the proposed direction.",
            percent=True,
        ),
        number(
            sc.get("effective_n"),
            "Effective observations",
            "How many independent observations the periods represent.",
        ),
    )


def trading_step(row: dict[str, Any], trial: dict[str, Any], sources: list[str]) -> dict[str, Any]:
    clock = clock_of(row) or "daily"
    trial = trial_of(row) or row
    replay = trial.get("replay", {})
    spread = trial.get("spread", {})
    values = []
    if row["status"] == "SCREEN_FAIL":
        text = f"The quick test stopped this idea, so ALPHA ran no trading test. {NO_TRADING_TEST}"
    elif row["status"] == "REPEAT":
        text = "This idea repeats an earlier trial. ALPHA ran no new trading test."
    elif "counted_only" in replay:
        text = "The spread check stopped this idea. ALPHA ran the replay only to count the trial."
    elif replay.get("net"):
        text = (
            f"ALPHA replayed holding the top-ranked third of coins on the {clock} schedule, "
            "paying assumed trading costs, and compared it with holding every coin."
        )
    else:
        text = "A completed trading test was not recorded. The judge's outcome follows."
    if row.get("stage") == "replay" and spread.get("mean_spread") is not None:
        values.append(
            number(
                spread["mean_spread"],
                "Spread before costs",
                "Average return of the top third minus the bottom third.",
                percent=True,
            )
        )
    if replay.get("net") and "counted_only" not in replay and row["status"] != "REPEAT":
        values.extend(
            [
                number(
                    replay["net"].get("annualized_return"),
                    "Yearly return above the basket",
                    "Average per period scaled to a year, after trading costs; "
                    "not compounded, so it differs from the chart's end values.",
                    percent=True,
                ),
                number(
                    replay.get("mean_turnover"),
                    "Average turnover",
                    "Share of the portfolio traded per period.",
                    percent=True,
                ),
            ]
        )
    return step("Real trading test, with costs", RULE, text, outcome(row), sources, *values)


def quick_verdicts(row: dict[str, Any]) -> list[str]:
    clocks = row.get("clocks") or {clock_of(row) or "daily": row}
    if row["status"] == "REPEAT":
        return [outcome(row)]
    passed = []
    failed = []
    for clock in CLOCK:
        trial = clocks.get(clock, {})
        status = trial.get("status")
        if status in {"PASS", "SPREAD_FAIL", "REPLAY_FAIL", "CANDIDATE", "DEFLATION_FAIL"} or (
            status == "ERROR" and trial.get("replay", {}).get("error")
        ):
            passed.append(clock)
        elif status == "SCREEN_FAIL":
            failed.append(clock)
    sentences = []
    for verb, names in (("passed", passed), ("failed", failed)):
        if names:
            joined = " and ".join(filter(None, (", ".join(names[:-1]), names[-1])))
            test = "test" if len(names) == 1 else "tests"
            sentences.append(f"It {verb} the {joined} quick {test}.")
    return sentences


def feedback_step(
    row: dict[str, Any], feedback: dict[str, Any], sources: list[str]
) -> dict[str, Any]:
    words = " ".join(
        feedback[k]
        for k in ("observations", "hypothesis_evaluation", "new_hypothesis", "reason")
        if feedback.get(k)
    )
    sentences = quick_verdicts(row)
    if not sentences:
        sentences.append("A quick test verdict was not recorded.")
    if next_idea := feedback.get("new_hypothesis"):
        first = re.split(r"(?<=[.!?])\s+", next_idea.strip(), maxsplit=1)[0]
        if len(first) > 200:
            first = first[:200].rsplit(" ", 1)[0].rstrip(",;:") + "…"
        codes = set(re.findall(r"\b[A-Z][A-Z_]+\b", first))
        if codes.intersection(STATUSES | PEEK.keys()) or re.search(
            r"\b(?:[A-Z]+(?:_[A-Z]+)+\b|q\s*=|rank[ -]IC\b)", first, re.I
        ):
            sentences.append("RD-Agent recorded a follow-up idea.")
        elif first:
            punctuation = "" if first.endswith((".", "?", "!", "…")) else "."
            sentences.append(f"RD-Agent proposed “{first}{punctuation}”")
    return step(
        "What happened next",
        AI,
        " ".join(sentences),
        "ALPHA judged each idea separately. RD-Agent's feedback covers the whole round.",
        sources,
        own_words=words or MISSING,
    )


def limits_step(row: dict[str, Any], trial: dict[str, Any], sources: list[str]) -> dict[str, Any]:
    counts = row.get("screen_m", row.get("family_size"))
    window = row.get("windows", {})
    span = window.get("exploration")
    symbols = row.get("instruments")
    extent = f"{len(symbols)} coins" if symbols is not None else "coin count not recorded"
    years = f"{span[0][:4]}–{span[1][:4]}" if span else "years not recorded"
    elig = row.get("eligibility")
    eligibility = (
        "coins with recorded perpetual-contract funding"
        if elig == "perp-funding"
        else elig or MISSING
    )
    exposure = row.get("exposure", {}).get("worst_status", "no exposure log")
    facts = [
        f"Test coverage: {extent}, {years}.",
        f"Coin set: {UNIVERSE[universe_label(row)]}. Eligibility: {eligibility}.",
        "Shortlisted: " + {True: "yes", False: "no", None: MISSING}[row.get("shortlist")] + ".",
        f"Candidate: {'yes' if recorded_status(row) == 'CANDIDATE' else 'no'}.",
        (
            f"This evaluation ended before the reserved period on {window['reserved_start']}."
            if window.get("panel_end")
            and window.get("reserved_start")
            and window["panel_end"] < window["reserved_start"]
            else "Reserved-period boundary not recorded."
        ),
        EXPOSURE[exposure],
        row.get("label", MISSING),
    ]
    return step(
        "How sure can we be?",
        RULE,
        (
            f"The test covered {extent} ({years})."
            if symbols is not None and span
            else f"The test coverage was only partly recorded: {extent}, {years}."
        )
        + " Testing more ideas gives luck more chances.",
        "These findings are exploratory. Prior use of reserved data limits independent checks.",
        sources,
        number(
            counts,
            "Ideas tested so far",
            "Every idea tested makes a lucky result more likely, "
            "so the pass line rises with this count.",
        ),
        number(
            trial.get("screen", {}).get("coverage"),
            "Coins with a usable number",
            "This is the share of eligible coin observations with a usable number.",
            percent=True,
        ),
        facts=facts,
    )
