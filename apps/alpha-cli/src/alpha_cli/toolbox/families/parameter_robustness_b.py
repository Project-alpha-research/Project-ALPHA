"""Timing, cost, start-date and opposite-rule checks, each a short ladder of engine re-runs."""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING, Any

from alpha_cli.toolbox.contract import Output, Result, ToolSpec, Value
from alpha_cli.toolbox.families import parameter_robustness_common as common
from alpha_cli.toolbox.families import parameter_robustness_signals as signals

if TYPE_CHECKING:
    from numpy.random import Generator

    from alpha_cli.toolbox.inputs import Inputs

DELAYS = (1, 2, 3)
COSTS = (2, 3, 5)
MONTHS = (3, 6, 12)
# Bars a later start must still leave after the rule's warm-up, as alpha test needs.
AFTER_WARMUP = 60
CAVEATS = (
    "Full-sample re-runs on the same bars, not walk-forward results.",
    "Each re-run is a try: it counts in the trial ledger and in later deflated Sharpe ratios.",
)


def _ladder(
    inputs: Inputs,
    spec: ToolSpec,
    steps: tuple[Any, ...],
    variants: list[common.Variant | None],
    skipped: str = "",
    execute: Any = None,
) -> Result:
    """One Sharpe ratio and one return per step; a step with no variant is unavailable."""
    run = inputs.run
    base = common.original(run)
    ready = [v for v in variants if v is not None]
    rows, added = common.rerun(run, spec.id, ready, execute) if ready else ([], 0)
    by_label = {row["name"]: row for row in rows}
    values: dict[str, Value] = {"engine_runs": len(rows), "tries_added": added}
    reasons: dict[str, str] = {}
    common.fill(values, reasons, "sharpe", base, "sharpe")
    for step, variant in zip(steps, variants, strict=True):
        row = by_label[variant.label] if variant is not None else {"reason": skipped}
        common.fill(values, reasons, f"sharpe_{step}", row, "sharpe")
        common.fill(values, reasons, f"return_{step}", row, "total_return")
    return Result(values, reasons, details={"as_tested": base, "runs": rows}, basis=common.BASIS)


def _guarded(spec: ToolSpec, inputs: Inputs) -> Result | None:
    if reason := common.too_little(inputs.run):
        keys = [o.key for o in spec.outputs]
        return common.unavailable(keys, reason, engine_runs=0, tries_added=0)
    return None


def entry_delay(inputs: Inputs, params: dict[str, Any], rng: Generator | None) -> Result:
    if early := _guarded(ENTRY_DELAY, inputs):
        return early
    _, spec = common.inputs_of(inputs.run)
    variants = [
        common.Variant(f"enter {n} later", spec, change=signals.EntryDelay(n)) for n in DELAYS
    ]
    return _ladder(inputs, ENTRY_DELAY, DELAYS, list(variants))


def exit_delay(inputs: Inputs, params: dict[str, Any], rng: Generator | None) -> Result:
    if early := _guarded(EXIT_DELAY, inputs):
        return early
    _, spec = common.inputs_of(inputs.run)
    variants = [
        common.Variant(f"leave {n} later", spec, change=signals.ExitDelay(n)) for n in DELAYS
    ]
    return _ladder(inputs, EXIT_DELAY, DELAYS, list(variants))


def cost_ladder(inputs: Inputs, params: dict[str, Any], rng: Generator | None) -> Result:
    if early := _guarded(COST_LADDER, inputs):
        return early
    _, spec = common.inputs_of(inputs.run)
    if spec.fee_bps == 0 and spec.slippage_bps == 0:
        keys = [o.key for o in COST_LADDER.outputs]
        reason = "This run charged no fees or slippage. There is nothing to multiply."
        return common.unavailable(keys, reason, engine_runs=0, tries_added=0)
    variants = [
        common.Variant(
            f"costs x{m}",
            replace(spec, fee_bps=spec.fee_bps * m, slippage_bps=spec.slippage_bps * m),
        )
        for m in COSTS
    ]
    return _ladder(inputs, COST_LADDER, COSTS, list(variants))


def start_date(inputs: Inputs, params: dict[str, Any], rng: Generator | None) -> Result:
    from bisect import bisect_left

    from alpha_cli.toolbox.families.robustness import shift_months

    if early := _guarded(START_DATE, inputs):
        return early
    run = inputs.run
    _, spec = common.inputs_of(run)
    variants: list[common.Variant | None] = []
    for months in MONTHS:
        start = bisect_left(run.dates, shift_months(run.dates[0], months))
        enough = len(run.bars) - start >= spec.min_train + AFTER_WARMUP
        variants.append(
            common.Variant(f"start {months} months later", spec, start=start) if enough else None
        )
    skipped = (
        f"A later start leaves fewer than the rule's warm-up of {spec.min_train} bars "
        f"plus {AFTER_WARMUP} bars."
    )
    return _ladder(inputs, START_DATE, MONTHS, variants, skipped)


def inversion(inputs: Inputs, params: dict[str, Any], rng: Generator | None) -> Result:
    from alpha_cli.spine.controls import run_inverted_backtest

    if early := _guarded(INVERSION, inputs):
        return early
    run = inputs.run
    _, spec = common.inputs_of(run)

    def opposite(variant: common.Variant) -> tuple[Any, int]:
        result = run_inverted_backtest(list(run.bars), spec, run.full, dividends=run.dividends)
        return [value for _, value in result.equity_curve], len(result.trades)

    variant = common.Variant("opposite rule", spec, identity={"control": "inverted"})
    return _ladder(inputs, INVERSION, ("opposite",), [variant], execute=opposite)


def _ladder_spec(
    tool: str, steps: tuple[Any, ...], names: dict[Any, str], reading: str, **fields: Any
) -> ToolSpec:
    outputs = [
        Output(
            "sharpe", "Sharpe ratio as tested", "The rule's own full-sample Sharpe ratio.", "ratio"
        )
    ]
    for step in steps:
        outputs.append(
            Output(
                f"sharpe_{step}",
                f"Sharpe ratio, {names[step]}",
                f"Sharpe ratio {names[step]}.",
                "ratio",
            )
        )
        outputs.append(
            Output(
                f"return_{step}",
                f"Return, {names[step]}",
                f"Total return {names[step]}.",
                "fraction",
            )
        )
    return ToolSpec(
        id=f"parameters.{tool}",
        family="parameters",
        needs=("run_rerun",),
        params=(),
        outputs=(*outputs, common.RUNS, common.TRIES),
        reading=reading + " This check added {tries_added:.0f} tries to the count.",
        caveats=CAVEATS,
        cost="minutes",
        time_safety="hindsight",
        poison_test=common.POISON,
        **fields,
    )


WORDS = {1: "one", 2: "two", 3: "three", 5: "five", 6: "six", 12: "twelve"}


def _three(steps: tuple[Any, ...], what: str) -> str:
    return ", ".join(
        f"{{sharpe_{step}:.2f}} ({what.format(WORDS[step])}, return {{return_{step}:.1%}})"
        for step in steps
    )


ENTRY_DELAY = _ladder_spec(
    "entry_delay",
    DELAYS,
    {n: f"entering {n} bars later" for n in DELAYS},
    "Entering one, two and three bars later than the rule says gave Sharpe ratios of "
    + _three(DELAYS, "{} later")
    + ", against {sharpe:.2f} as tested.",
    question="What if each entry came 1, 2 or 3 bars later than the rule says?",
    answers=("Does the result need perfect entry timing?", "What if I enter a bar or two late?"),
    situations=("timing-sensitivity",),
    reference=common.TESTS + "test_entry_delay_enters_later_and_leaves_on_time",
    compute=entry_delay,
)
EXIT_DELAY = _ladder_spec(
    "exit_delay",
    DELAYS,
    {n: f"leaving {n} bars later" for n in DELAYS},
    "Leaving one, two and three bars later than the rule says gave Sharpe ratios of "
    + _three(DELAYS, "{} later")
    + ", against {sharpe:.2f} as tested.",
    question="What if each exit came 1, 2 or 3 bars later than the rule says?",
    answers=("Does the result need perfect exit timing?", "What if I exit a bar or two late?"),
    situations=("timing-sensitivity",),
    reference=common.TESTS + "test_exit_delay_leaves_later",
    compute=exit_delay,
)
COST_LADDER = _ladder_spec(
    "cost_ladder",
    COSTS,
    {m: f"at {m} times the fees and slippage" for m in COSTS},
    "Re-filled by the engine at two, three and five times the fees and slippage, "
    "the Sharpe ratio was "
    + _three(COSTS, "{} times")
    + ", against {sharpe:.2f} at today's costs.",
    question="What is left at 2, 3 and 5 times the fees and slippage, re-filled by the engine?",
    answers=("How much cost can this rule carry?", "Does it survive much higher costs?"),
    situations=("cost-fragile",),
    reference=common.TESTS + "test_cost_ladder_lowers_the_return",
    compute=cost_ladder,
)
START_DATE = _ladder_spec(
    "start_date",
    MONTHS,
    {m: f"starting {m} months later" for m in MONTHS},
    "Starting the test three, six and twelve months later gave Sharpe ratios of "
    + _three(MONTHS, "{} months")
    + ", against {sharpe:.2f} as tested.",
    question="What if the test had started 3, 6 or 12 months later?",
    answers=(
        "Does the result hang on the first months?",
        "What if I had started trading it later?",
    ),
    situations=("works-only-sometimes",),
    reference=common.TESTS + "test_start_date_starts_later",
    compute=start_date,
)
INVERSION = _ladder_spec(
    "inversion",
    ("opposite",),
    {"opposite": "of the opposite rule"},
    "The opposite rule (short when the rule is long) had a Sharpe ratio of {sharpe_opposite:.2f} "
    "and a return of {return_opposite:.1%}, against {sharpe:.2f} for the rule. If both look good, "
    "the result may come from the market's drift, the data or the costs, not the rule.",
    question="Does the opposite rule also look good?",
    answers=("Is the rule better than its opposite?", "Does the inverted rule also make money?"),
    situations=("just-the-market", "looks-too-good"),
    kind="control",
    reference=common.TESTS + "test_inversion_matches_the_stored_control",
    compute=inversion,
)
CHECKS = (ENTRY_DELAY, EXIT_DELAY, COST_LADDER, START_DATE, INVERSION)
