"""A small grid of nearby settings, and random re-runs: entries skipped, noise in prices."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from alpha_cli.toolbox.contract import Output, Param, Result, ToolSpec, Value
from alpha_cli.toolbox.families import parameter_robustness_common as common
from alpha_cli.toolbox.families import parameter_robustness_signals as signals
from alpha_cli.toolbox.families.parameter_robustness_a import settings_spec
from alpha_cli.toolbox.families.parameter_robustness_b import CAVEATS
from alpha_cli.toolbox.families.parameter_robustness_grid import grid

if TYPE_CHECKING:
    from numpy.random import Generator

    from alpha_cli.toolbox.inputs import Inputs

SKIPS = (0.1, 0.2, 0.3)
GRIDS = {"quick": (0.8, 1.0, 1.2), "full": (0.6, 0.8, 1.0, 1.2, 1.4)}
# Within this share of the rule's own Sharpe ratio counts as "near the chosen result".
NEAR = 0.2


def _guarded(spec: ToolSpec, inputs: Inputs) -> Result | None:
    if reason := common.too_little(inputs.run):
        keys = [o.key for o in spec.outputs]
        return common.unavailable(keys, reason, engine_runs=0, tries_added=0)
    return None


def plateau(inputs: Inputs, params: dict[str, Any], rng: Generator | None) -> Result:
    keys = [o.key for o in PLATEAU.outputs]
    run = inputs.run
    if reason := common.too_little(run):
        return common.unavailable(keys, reason, engine_runs=0, tries_added=0)
    base = common.original(run)
    moved, points = grid(run, GRIDS[params["grid"]])
    variants = [common.Variant(label, spec) for label, spec in points if spec is not None]
    left_out = [label for label, spec in points if spec is None]
    if base["sharpe"] is None or base["sharpe"] == 0 or not variants:
        reason = (
            "The rule's own Sharpe ratio is not defined or is zero, so 'within 20%' has no meaning."
            if variants
            else "The rule has no setting that the grid can move."
        )
        return common.unavailable(keys, reason, engine_runs=0, tries_added=0)
    rows, added = common.rerun(run, PLATEAU.id, variants)
    chosen = base["sharpe"]
    near = [
        r
        for r in rows
        if r["sharpe"] is not None and abs(r["sharpe"] - chosen) <= NEAR * abs(chosen)
    ]
    values: dict[str, Value] = {
        "within_share": len(near) / len(rows),
        "grid_points": len(rows),
        "sharpe": chosen,
        "engine_runs": len(rows),
        "tries_added": added,
    }
    reasons: dict[str, str] = {}
    defined = [r["sharpe"] for r in rows if r["sharpe"] is not None]
    values["sharpe_min"] = min(defined) if defined else None
    if not defined:
        reasons["sharpe_min"] = "No grid point had a defined Sharpe ratio."
    details = {"settings_moved": moved, "left_out": left_out, "as_tested": base, "grid": rows}
    return Result(values, reasons, details=details, basis=common.BASIS)


def skip_entries(inputs: Inputs, params: dict[str, Any], rng: Generator | None) -> Result:
    if early := _guarded(SKIP_ENTRIES, inputs):
        return early
    if rng is None:
        raise ValueError("Skipping entries at random needs the seeded generator")
    _, spec = common.inputs_of(inputs.run)
    copies = params["copies"]
    variants = [
        common.Variant(
            f"skip {share:.0%} copy {copy}",
            spec,
            change=signals.SkipEntries(share, int(rng.integers(2**63 - 1))),
        )
        for share in SKIPS
        for copy in range(copies)
    ]
    run = inputs.run
    base = common.original(run)
    rows, added = common.rerun(run, SKIP_ENTRIES.id, variants)
    values: dict[str, Value] = {"engine_runs": len(rows), "tries_added": added}
    reasons: dict[str, str] = {}
    common.fill(values, reasons, "sharpe", base, "sharpe")
    for share in SKIPS:
        tag = f"{share * 100:.0f}"
        group = [r["sharpe"] for r in rows if r["name"].startswith(f"skip {share:.0%} ")]
        defined = [value for value in group if value is not None]
        for suffix, bound in (("low", min), ("high", max)):
            key = f"sharpe_{suffix}_{tag}"
            # Every copy must have a Sharpe ratio: a range over a subset could hide a flat copy.
            values[key] = bound(defined) if len(defined) == len(group) else None
            if values[key] is None:
                reasons[key] = f"{len(group) - len(defined)} copies have no defined Sharpe ratio."
    return Result(values, reasons, details={"as_tested": base, "runs": rows}, basis=common.BASIS)


def price_noise(inputs: Inputs, params: dict[str, Any], rng: Generator | None) -> Result:
    from alpha_cli.spine.price_noise import NOISE_SEEDS, noise_summary, noisy_bars

    if early := _guarded(PRICE_NOISE, inputs):
        return early
    run = inputs.run
    _, spec = common.inputs_of(run)
    name = f"{run.run_id}:{inputs.seed}"
    variants = [
        common.Variant(
            f"noise copy {copy}",
            spec,
            bars=tuple(noisy_bars(list(run.bars), name, copy)),
            data_key=f"price-noise:{name}:{copy}",
        )
        for copy in range(NOISE_SEEDS)
    ]
    base = common.original(run)
    rows, added = common.rerun(run, PRICE_NOISE.id, variants)
    summary = noise_summary(rows, base["sharpe"])
    values: dict[str, Value] = {"engine_runs": len(rows), "tries_added": added}
    reasons: dict[str, str] = {}
    for key in ("median_sharpe", "p05_sharpe", "p95_sharpe", "sign_flip_share"):
        values[key] = summary[key]
        if summary[key] is None:
            reasons[key] = summary["reasons"][key]
    common.fill(values, reasons, "sharpe", base, "sharpe")
    details = {"as_tested": base, "sigma": summary["sigma"], "runs": rows}
    return Result(values, reasons, details=details, basis=common.BASIS)


def _sharpe(key: str, label: str, gloss: str) -> Output:
    return Output(key, label, gloss, "ratio")


PLATEAU = settings_spec(
    id="parameters.plateau",
    question="How much of a small grid of nearby settings stays near the chosen result?",
    answers=(
        "Is the chosen setting on a plateau or a lonely peak?",
        "Is there a parameter plateau around my settings?",
    ),
    params=(
        Param(
            "grid",
            str,
            "quick",
            tuple(GRIDS),
            "quick: 3 x 3 grid at 0.8, 1 and 1.2 times (8 re-runs); full: 5 x 5 at 0.6 to 1.4 "
            "times (24 re-runs). The first two settings of the rule move.",
        ),
    ),
    outputs=(
        Output(
            "within_share",
            "Share near the chosen result",
            "Share of grid points whose Sharpe ratio is within 20% of the rule's own.",
            "fraction",
        ),
        Output("grid_points", "Grid points run", "Grid points re-run, the rule left out.", "count"),
        _sharpe("sharpe", "Sharpe ratio as tested", "The rule's own full-sample Sharpe ratio."),
        _sharpe("sharpe_min", "Lowest Sharpe ratio", "Lowest Sharpe ratio on the grid."),
        common.RUNS,
        common.TRIES,
    ),
    reading=(
        "{within_share:.0%} of {grid_points:.0f} nearby grid settings had a Sharpe ratio within "
        "a fifth of the rule's own {sharpe:.2f}; the lowest was {sharpe_min:.2f}."
    )
    + common.TRY_SENTENCE,
    reference=common.TESTS + "test_plateau_of_a_flat_rule_is_whole",
    compute=plateau,
    evaluations=lambda params: 24 if params.get("grid") == "full" else 8,
)
SKIP_ENTRIES = ToolSpec(
    id="parameters.skip_entries",
    family="parameters",
    question="How far do results move if 10%, 20% or 30% of entries are skipped at random?",
    answers=(
        "Does the result hang on a few lucky entries?",
        "What if I miss some trades at random?",
    ),
    situations=("lucky-trades", "few-trades"),
    needs=("run_rerun",),
    params=(
        Param("copies", int, 10, range(2, 51), "Seeded re-runs at each skip share (2 to 50)."),
    ),
    outputs=(
        _sharpe("sharpe", "Sharpe ratio as tested", "The rule's own full-sample Sharpe ratio."),
        *(
            _sharpe(
                f"sharpe_{side}_{share}",
                f"{word} Sharpe ratio, {share}% skipped",
                f"{word} Sharpe ratio of the copies with {share}% of entries skipped.",
            )
            for share in (10, 20, 30)
            for side, word in (("low", "Lowest"), ("high", "Highest"))
        ),
        common.RUNS,
        common.TRIES,
    ),
    reading=(
        "With entries skipped at random, the Sharpe ratio ran from {sharpe_low_10:.2f} to "
        "{sharpe_high_10:.2f} with a tenth skipped, {sharpe_low_20:.2f} to {sharpe_high_20:.2f} "
        "with a fifth "
        "and {sharpe_low_30:.2f} to {sharpe_high_30:.2f} with three tenths "
        "({engine_runs:.0f} re-runs; "
        "as tested {sharpe:.2f})."
    )
    + common.TRY_SENTENCE,
    caveats=(*CAVEATS, "A skipped entry stays out until the rule's next entry."),
    reference=common.TESTS + "test_skipping_no_entry_reproduces_the_rule",
    compute=skip_entries,
    cost="minutes",
    seeded=True,
    time_safety="hindsight",
    poison_test=common.POISON,
)
PRICE_NOISE = ToolSpec(
    id="parameters.price_noise",
    family="parameters",
    question="How much do results spread when every price gets a small random nudge?",
    answers=(
        "Would a slightly different data feed change the answer?",
        "What if the prices had small errors or noise?",
    ),
    situations=("data-doubt",),
    needs=("run_rerun",),
    params=(),
    outputs=(
        _sharpe("sharpe", "Sharpe ratio as tested", "The rule's own full-sample Sharpe ratio."),
        _sharpe("median_sharpe", "Median Sharpe ratio", "Median Sharpe ratio of 50 noisy copies."),
        _sharpe("p05_sharpe", "5th percentile Sharpe ratio", "5th percentile of the copies."),
        _sharpe("p95_sharpe", "95th percentile Sharpe ratio", "95th percentile of the copies."),
        Output(
            "sign_flip_share",
            "Share with the sign flipped",
            "Share of copies whose Sharpe ratio has the opposite sign of the rule's own.",
            "fraction",
        ),
        common.RUNS,
        common.TRIES,
    ),
    reading=(
        "With every price nudged at random by about a tenth of a percent, the Sharpe ratio ran "
        "from {p05_sharpe:.2f} to {p95_sharpe:.2f} across the middle nine tenths of "
        "{engine_runs:.0f} "
        "copies (median {median_sharpe:.2f}, as tested {sharpe:.2f}); the sign flipped in "
        "{sign_flip_share:.0%}."
    )
    + common.TRY_SENTENCE,
    caveats=(*CAVEATS, "The noise is independent from bar to bar; real data errors may not be."),
    reference=common.TESTS + "test_price_noise_spreads_around_the_rule",
    compute=price_noise,
    cost="minutes",
    seeded=True,
    time_safety="hindsight",
    poison_test=common.POISON,
)
CHECKS = (PLATEAU, SKIP_ENTRIES, PRICE_NOISE)
