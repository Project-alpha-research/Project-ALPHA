"""Reproduce the family-deflated probability with the ledger snapshot frozen at publication."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from alpha_cli.toolbox.contract import Output, Result, ToolSpec, Value

if TYPE_CHECKING:
    from numpy.random import Generator

    from alpha_cli.toolbox.inputs import Inputs

TESTS = "tests/unit/test_toolbox_resampling_checks.py::"
BASIS = "After-cost scored returns and the run manifest's recorded family of trials."


def deflated(inputs: Inputs, params: dict[str, Any], rng: Generator | None) -> Result:
    from alpha_cli.spine.deflation import TrialFamily, family_deflation

    run = inputs.stored
    returns = run.scored_returns()
    snapshot = run.manifest.get("dsr") or {}
    values: dict[str, Value] = dict.fromkeys(("trials", "dsr", "benchmark"))
    if snapshot.get("family_id") is None:
        return Result(
            values,
            dict.fromkeys(values, "No ledger family of ideas was recorded with this run."),
            basis=BASIS,
        )
    count = snapshot["n_trials"]
    if type(count) is not int or count < 1:
        raise ValueError("The recorded n_trials must be a positive integer")
    family = TrialFamily(
        snapshot["family_id"],
        snapshot["family_count"],
        count,
        snapshot["comparable_trials"],
        snapshot["repeats"],
    )
    values["trials"] = family.count
    if len(returns) < 2:
        reason = "Deflated Sharpe needs at least 2 varying scored bar returns."
        return Result(values, dict.fromkeys(("dsr", "benchmark"), reason), basis=BASIS)
    counted = family_deflation(returns, snapshot["prior_sharpes"], family)
    values.update(
        dsr=counted["dsr"],
        benchmark=counted["expected_max_sharpe"],
        trials=counted["n_trials_used"],
    )
    reasons = {key: counted["reasons"]["dsr"] for key, value in values.items() if value is None}
    return Result(values, reasons, basis=BASIS)


DEFLATED_SHARPE = ToolSpec(
    id="overfit.deflated_sharpe",
    answers=(
        "Is this overfit after counting every try in its family?",
        "Does the result still look too good once every try is counted?",
    ),
    situations=("many-tries", "looks-too-good"),
    family="overfit",
    kind="test",
    look="test",
    question="Does the Sharpe ratio still stand out once the tries in its family are counted?",
    needs=("stored_equity",),
    params=(),
    outputs=(
        Output(
            "dsr",
            "Deflated Sharpe probability",
            "Chance the Sharpe ratio beats the best-of-family luck benchmark.",
            "fraction",
        ),
        Output(
            "trials",
            "Tries counted",
            "Tries in the run's rule family when it was recorded: past rule tests, their setting"
            " variants and this run.",
            "count",
        ),
        Output(
            "benchmark",
            "Luck benchmark",
            "Best per-bar Sharpe ratio expected by luck across the counted tries.",
            "ratio",
        ),
    ),
    reading=(
        "Deflated Sharpe probability: {dsr:.1%}. That is the chance this run's Sharpe ratio beats"
        " the best that luck alone would give across the {trials} tries recorded in its family"
        " when the run was made. It uses the run's after-cost scored returns and the same count"
        ' and formula as the test, so it can be high while the test reads "not clear of chance":'
        " this is one check, and the test's reading also needs the whole Sharpe interval to be positive and"
        " every null test to hold."
    ),
    caveats=(
        "It uses the count frozen when the run was recorded. Tries made later, or never recorded"
        " in the ledger, are not counted; a new rule test counts the current ledger.",
    ),
    time_safety="hindsight",
    poison_test=TESTS + "test_future_input_rejected",
    reference=TESTS + "test_public_function_parity",
    compute=deflated,
)
