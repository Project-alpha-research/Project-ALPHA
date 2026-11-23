"""What each run label means, in one plain line: the one labels table of the command line.

The Workstation holds the same table in `ruleTestModel.ts` (`LABEL_MEANING`);
`tests/unit/test_label_meaning.py` fails when the two differ. A label that is not here is printed
under its own name, never with an invented meaning.
"""

from __future__ import annotations

from collections.abc import Iterable

from alpha_core.reserve import RESERVED_START

LABEL_MEANING: dict[str, str] = {
    "null-closes-for-high-low": (
        "The rule reads the high or low. The first random-price test has no daily range, "
        "so it uses closes for high and low."
    ),
    "exploratory": "Exploratory test. These results describe this run only.",
    "too-few-trades": "Too few closed trades in the walk-forward test to judge the result.",
    "benchmark-price-only": "Both lines use prices only. No dividend cash was recorded.",
    "all-in": "All capital goes into each position; no volatility sizing.",
    "quick": "Quick mode used fewer random comparisons to check the result.",
    "data-health-pass": "The data checks found no fault. The prices can still be wrong.",
    "data-health-warn": "A data check found a warning. Read the finding before using this result.",
    "data-health-fail": "A data check found a fault in the prices or their supporting records.",
    "data-health-unchecked": "At least one series has no current data health report.",
    "data-health-overridden": "The run records why it proceeded after a failed data check.",
    "dev-machine-data": "Run on the data stored on this development machine.",
    "source-defaulted": "The asset is in more than one data store; the first match was used.",
    "short-history": "The test covers less than three years of price history.",
    "repeat": (
        "An identical test was already recorded; the repeat adds a ledger entry but not "
        "another distinct try."
    ),
    "no-diagnostics": "The diagnostic pass was skipped for this run.",
    "error": "The test ended with an error; unavailable numbers stay empty.",
    "ad-hoc": "Run on its own, not as part of a predeclared set of checks.",
    "non-default-params": (
        "Run with a setting other than the default, or with another random seed."
    ),
    "reserved-period-seen": (
        f"The data reaches into the reserved period, which starts on {RESERVED_START}."
    ),
    "reserved-period-confirmation": (
        f"The owner's one confirmation of a frozen test on the reserved period ({RESERVED_START} "
        "on). It is recorded whatever it shows."
    ),
    "reserved-period-confirmed-in-family": (
        "This rule was already confirmed on this asset in the reserved period; this test "
        "is not independent of that result."
    ),
    "benchmark-is-same-asset": "The market used for comparison is the asset the rule traded.",
    "hindsight": "Part of this result uses the whole history, which was not knowable at the time.",
    "hindsight-disagrees": (
        "The hindsight split tells a different story from the split made at the time."
    ),
    "parameters-fit-in-sample": (
        "The model settings were fitted on the same history they describe."
    ),
    "reserved-period-held-back": (
        f"Data from {RESERVED_START} on was held back for the owner's confirmation and was "
        "not used."
    ),
    "class-default-costs": (
        "Costs came from the default for this kind of market, not from a setting you chose."
    ),
    "cost-class-assumed": (
        "The kind of market was not recorded, so the higher crypto cost assumption was used."
    ),
    "borrow-at-class-rate": (
        "Borrow or funding for a short is an assumed charge per day held, at the usual "
        "rate for this market."
    ),
    "short-borrow-not-charged": (
        "The cost of borrowing for a short is stated but not charged in the result."
    ),
    "costs-assumed-high": (
        "The market was not identified, so the higher crypto cost assumption was used."
    ),
    "short-costs-assumed": "Borrow or funding is an assumed charge per calendar day held.",
    "short-needs-perpetual": (
        "A crypto short needs a perpetual contract. Spot prices are only a stand-in."
    ),
    "fragile-to-price-noise": (
        "The result changes a lot when small random noise is added to prices."
    ),
    "halves-disagree": "The two halves of the history have average returns with opposite signs.",
    "many-skipped": (
        "More than a quarter of the occurrences were skipped because a trade was already open."
    ),
    "no-random-control": "The random-date comparison is not available; see the stored reason.",
    "no-time-exit": "No time exit was set, so the tool used its 250-bar limit.",
    "not-primary": "Also looked at, not tested as the main holding period.",
    "older-cost-rule": "Recorded under an earlier cost rule.",
    "outcomes-not-viewed": "This find recorded that outcomes had not been viewed yet.",
    "outcomes-viewed": "Outcomes have been viewed in a study or trade run.",
    "overlapping-outcomes": "Some outcome windows overlap, so the results are not independent.",
    "remeasured-new-cost-rule": "An earlier find measured again under a new cost rule.",
    "single-asset": "Only one asset was studied.",
    "too-few-occurrences": "Fewer than 30 complete occurrences or trades: too few to judge.",
}


def label_lines(labels: Iterable[str]) -> list[str]:
    """One line per label: its name and what it means; an unknown label has no meaning line."""
    return [
        f"  {name}: {LABEL_MEANING[name]}" if name in LABEL_MEANING else f"  {name}"
        for name in labels
    ]
