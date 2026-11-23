"""Settings checks: each setting moved alone, and the nearest settings."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from alpha_cli.toolbox.contract import Output, Result, ToolSpec, Value
from alpha_cli.toolbox.families import parameter_robustness_common as common

if TYPE_CHECKING:
    from numpy.random import Generator

    from alpha_cli.toolbox.inputs import Inputs

FACTORS = (0.5, 0.8, 1.2, 1.5)
NEAREST = (0.8, 1.2)
CAVEATS = (
    "Full-sample re-runs on the same bars, not walk-forward results.",
    "Each re-run is a try: it counts in the trial ledger and in later deflated Sharpe ratios.",
)


def _parameter_variants(inputs: Inputs, factors: tuple[float, ...]) -> list[common.Variant]:
    from alpha_cli.spine.diagnose import variant_specs

    idea, spec = common.inputs_of(inputs.run)
    return [
        common.Variant(label, changed)
        for label, kind, changed in variant_specs(idea, spec, factors=factors)
        if kind == "parameter"
    ]


def _spread(rows: list[dict[str, Any]], values: dict[str, Value], reasons: dict[str, str]) -> None:
    for metric, short in (("sharpe", "sharpe"), ("total_return", "return")):
        defined = [row[metric] for row in rows if row[metric] is not None]
        for suffix, bound in (("min", min), ("max", max)):
            key = f"{short}_{suffix}"
            values[key] = bound(defined) if defined else None
            if not defined:
                reasons[key] = f"No re-run had a defined {metric.replace('_', ' ')}."


def one_at_a_time(inputs: Inputs, params: dict[str, Any], rng: Generator | None) -> Result:
    keys = [o.key for o in ONE_AT_A_TIME.outputs]
    run = inputs.run
    if reason := common.too_little(run):
        return common.unavailable(keys, reason, engine_runs=0, tries_added=0)
    base = common.original(run)
    variants = _parameter_variants(inputs, FACTORS)
    if not variants:
        reason = "The rule has no setting that can move to 0.5, 0.8, 1.2 or 1.5 times its value."
        return common.unavailable(keys, reason, engine_runs=0, tries_added=0)
    rows, added = common.rerun(run, ONE_AT_A_TIME.id, variants)
    values: dict[str, Value] = {"engine_runs": len(rows), "tries_added": added}
    reasons: dict[str, str] = {}
    common.fill(values, reasons, "sharpe", base, "sharpe")
    _spread(rows, values, reasons)
    return Result(
        values, reasons, details={"as_tested": base, "variants": rows}, basis=common.BASIS
    )


def _nearest(
    inputs: Inputs, spec: ToolSpec
) -> Result | tuple[dict[str, Any], list[dict[str, Any]], int]:
    """The rule and its nearest settings re-run, or the reason nothing can be read."""
    keys, run = [o.key for o in spec.outputs], inputs.run
    reason = common.too_little(run)
    variants = _parameter_variants(inputs, NEAREST) if reason is None else []
    if reason is None and not variants:
        reason = "The rule has no setting that can move to 0.8 or 1.2 times its value."
    if reason is not None:
        return common.unavailable(keys, reason, engine_runs=0, tries_added=0)
    rows, added = common.rerun(run, spec.id, variants)
    return common.original(run), rows, added


def neighbour_stability(inputs: Inputs, params: dict[str, Any], rng: Generator | None) -> Result:
    found = _nearest(inputs, NEIGHBOUR_STABILITY)
    if isinstance(found, Result):
        return found
    base, rows, added = found
    values: dict[str, Value] = {
        "neighbours": len(rows),
        "engine_runs": len(rows),
        "tries_added": added,
    }
    reasons: dict[str, str] = {}
    if base["total_return"] == 0:
        values["same_sign_share"] = None
        reasons["same_sign_share"] = "The rule's own return is exactly zero, so it has no sign."
    else:
        same = [r for r in rows if r["total_return"] * base["total_return"] > 0]
        values["same_sign_share"] = len(same) / len(rows)
    values["total_return"] = base["total_return"]
    return Result(
        values, reasons, details={"as_tested": base, "neighbours": rows}, basis=common.BASIS
    )


def worst_neighbour(inputs: Inputs, params: dict[str, Any], rng: Generator | None) -> Result:
    found = _nearest(inputs, WORST_NEIGHBOUR)
    if isinstance(found, Result):
        return found
    base, rows, added = found
    worst = min(rows, key=lambda r: r["total_return"])
    values: dict[str, Value] = {
        "worst_setting": worst["name"],
        "worst_return": worst["total_return"],
        "total_return": base["total_return"],
        "engine_runs": len(rows),
        "tries_added": added,
    }
    reasons: dict[str, str] = {}
    common.fill(values, reasons, "worst_sharpe", worst, "sharpe")
    common.fill(values, reasons, "sharpe", base, "sharpe")
    return Result(
        values, reasons, details={"as_tested": base, "neighbours": rows}, basis=common.BASIS
    )


def _sharpe(key: str, label: str, gloss: str) -> Output:
    return Output(key, label, gloss, "ratio")


def settings_spec(**fields: Any) -> ToolSpec:
    return ToolSpec(
        family="parameters",
        needs=("run_rerun",),
        caveats=CAVEATS,
        cost="minutes",
        look="search",
        time_safety="hindsight",
        poison_test=common.POISON,
        situations=("parameter-sensitivity", "looks-too-good"),
        **fields,
    )


ONE_AT_A_TIME = settings_spec(
    id="parameters.one_at_a_time",
    question="How do the Sharpe ratio and return change when each setting moves alone?",
    answers=(
        "Does the result depend on the exact setting?",
        "How sensitive is the result to each parameter?",
    ),
    params=(),
    outputs=(
        _sharpe("sharpe", "Sharpe ratio as tested", "The rule's own full-sample Sharpe ratio."),
        _sharpe("sharpe_min", "Lowest Sharpe ratio", "Lowest Sharpe ratio of the re-runs."),
        _sharpe("sharpe_max", "Highest Sharpe ratio", "Highest Sharpe ratio of the re-runs."),
        Output("return_min", "Lowest return", "Lowest total return of the re-runs.", "fraction"),
        Output("return_max", "Highest return", "Highest total return of the re-runs.", "fraction"),
        common.RUNS,
        common.TRIES,
    ),
    reading=(
        "With each setting moved alone to half, four fifths, six fifths and one and a half "
        "times its value "
        "({engine_runs:.0f} re-runs), the Sharpe ratio ran from {sharpe_min:.2f} to "
        "{sharpe_max:.2f} (as tested {sharpe:.2f}) and the return from {return_min:.1%} to "
        "{return_max:.1%}."
    )
    + common.TRY_SENTENCE,
    reference=common.TESTS + "test_flat_rule_gives_a_flat_sensitivity",
    compute=one_at_a_time,
    evaluations=lambda params: 16,
)
NEIGHBOUR_STABILITY = settings_spec(
    id="parameters.neighbour_stability",
    question="Do the nearest settings make money in the same direction?",
    answers=(
        "Does a small change of setting flip the result?",
        "Are the neighbouring parameter settings stable?",
    ),
    params=(),
    outputs=(
        Output(
            "same_sign_share",
            "Share with the same sign",
            "Share of nearest settings (each setting at 0.8 and 1.2 times) whose total return "
            "has the same sign as the rule's own.",
            "fraction",
        ),
        Output("neighbours", "Nearest settings", "Nearest settings re-run.", "count"),
        Output(
            "total_return", "Return as tested", "The rule's own full-sample return.", "fraction"
        ),
        common.RUNS,
        common.TRIES,
    ),
    reading=(
        "{same_sign_share:.0%} of {neighbours:.0f} nearest settings had a return of the same "
        "sign as the rule's own {total_return:.1%}."
    )
    + common.TRY_SENTENCE,
    reference=common.TESTS + "test_neighbours_of_a_flat_rule_agree",
    compute=neighbour_stability,
    evaluations=lambda params: 8,
)
WORST_NEIGHBOUR = settings_spec(
    id="parameters.worst_neighbour",
    question="How weak is the weakest of the nearest settings?",
    answers=(
        "What if my setting is slightly off?",
        "How bad is the worst neighbouring parameter setting?",
    ),
    params=(),
    outputs=(
        Output(
            "worst_setting",
            "Weakest setting",
            "The nearest setting with the lowest return.",
            "text",
        ),
        Output("worst_return", "Its return", "Total return of the weakest setting.", "fraction"),
        _sharpe("worst_sharpe", "Its Sharpe ratio", "Sharpe ratio of the weakest setting."),
        Output(
            "total_return", "Return as tested", "The rule's own full-sample return.", "fraction"
        ),
        _sharpe("sharpe", "Sharpe ratio as tested", "The rule's own full-sample Sharpe ratio."),
        common.RUNS,
        common.TRIES,
    ),
    reading=(
        "The weakest nearest setting returned {worst_return:.1%} with a Sharpe "
        "ratio of {worst_sharpe:.2f}, against {total_return:.1%} and {sharpe:.2f} as tested."
    )
    + common.TRY_SENTENCE,
    reference=common.TESTS + "test_worst_neighbour_is_the_lowest_return",
    compute=worst_neighbour,
    evaluations=lambda params: 8,
)
CHECKS = (ONE_AT_A_TIME, NEIGHBOUR_STABILITY, WORST_NEIGHBOUR)
