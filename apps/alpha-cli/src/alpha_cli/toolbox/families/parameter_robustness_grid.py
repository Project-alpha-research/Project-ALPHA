"""A small grid of nearby settings: every pair of factors on the first two settings of a rule."""

from __future__ import annotations

from typing import TYPE_CHECKING

from alpha_cli.toolbox.families.parameter_robustness_common import inputs_of

if TYPE_CHECKING:
    from alpha_cli import _runner
    from alpha_cli.toolbox.inputs import RunSeries


def grid(
    run: RunSeries, factors: tuple[float, ...]
) -> tuple[int, list[tuple[str, _runner.RunSpec | None]]]:
    """Every pair of ``factors`` on the first two settings of the rule, the rule itself left out.

    Returns how many settings move and one (label, run spec) per distinct point; the run spec is
    None where the rule refuses the point or rounding gives the rule back. Factors that round to
    the same whole-bar setting give one point, never the same setting twice.
    """
    from dataclasses import replace

    from alpha_cli.spine.diagnose import classic_variant
    from alpha_cli.spine.owner_rule import OwnerRule
    from alpha_cli.spine.owner_variants import owner_grid

    idea, spec = inputs_of(run)
    if isinstance(idea.rule, OwnerRule):
        moved, found = owner_grid(idea.rule.spec, factors)
        return moved, _distinct(
            [
                (
                    label,
                    None
                    if changed is None
                    else replace(spec, rules_spec=OwnerRule(kind="owner", spec=changed).rules_json),
                )
                for label, changed in found
            ]
        )
    params = dict(list(idea.rule.params.items())[:2])
    combos: list[tuple[float, ...]] = [()]
    for _ in params:
        combos = [(*combo, factor) for combo in combos for factor in factors]
    points: list[tuple[str, _runner.RunSpec | None]] = []
    for combo in combos:
        if all(factor == 1.0 for factor in combo):
            continue
        changes = {
            key: round(value * factor)
            for (key, value), factor in zip(params.items(), combo, strict=True)
        }
        label = ", ".join(f"{key}={value}" for key, value in changes.items())
        points.append((label, None if changes == params else classic_variant(idea, spec, changes)))
    return len(params), _distinct(points)


def _distinct(
    points: list[tuple[str, _runner.RunSpec | None]],
) -> list[tuple[str, _runner.RunSpec | None]]:
    """The first of each run spec; refused points are kept so the reading can name them."""
    seen: set[_runner.RunSpec] = set()
    kept: list[tuple[str, _runner.RunSpec | None]] = []
    for label, spec in points:
        if spec is not None and spec in seen:
            continue
        if spec is not None:
            seen.add(spec)
        kept.append((label, spec))
    return kept
