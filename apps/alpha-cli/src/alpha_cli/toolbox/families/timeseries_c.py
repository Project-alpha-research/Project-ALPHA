"""Irregularity of the return series: sample entropy, compressibility and ordering."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from alpha_cli.toolbox.contract import Output, Param, Result
from alpha_cli.toolbox.families.timeseries_common import (
    finished,
    flat,
    make,
    too_little,
    unavailable,
)

if TYPE_CHECKING:
    from numpy.random import Generator

    from alpha_cli.toolbox.inputs import Inputs
    from alpha_validation import FloatArray

FLAT = "The scored returns do not vary."
# The pair search grows with the square of the length; above this the check says so, not waits.
MAX_BARS = 10_000


def sample_entropy(x: FloatArray, m: int, r_frac: float) -> float | None:
    """-ln(A/B) over the first n-m templates, within r_frac * sd (Richman & Moorman 2000)."""
    import numpy as np
    from numpy.lib.stride_tricks import sliding_window_view

    tol = r_frac * float(np.std(x))
    templates = sliding_window_view(x, m + 1)[: len(x) - m]
    near_m = near_m1 = 0
    for i in range(len(templates) - 1):
        d = np.abs(templates[i + 1 :, :m] - templates[i, :m]).max(axis=1)
        d1 = np.maximum(d, np.abs(templates[i + 1 :, m] - templates[i, m]))
        near_m += int((d <= tol).sum())
        near_m1 += int((d1 <= tol).sum())
    if near_m == 0 or near_m1 == 0:
        return None
    return float(-np.log(near_m1 / near_m))


def _sample_entropy(inputs: Inputs, params: dict[str, Any], rng: Generator | None) -> Result:
    keys = ("sample_entropy", "m", "tolerance")
    r = inputs.stored.scored_returns()
    if r.size < 100:
        return too_little(keys, 100, r.size)
    if r.size > MAX_BARS:
        reason = (
            f"Sample entropy compares every pair of patterns, so it is read up to {MAX_BARS} "
            f"scored bar returns; this run has {r.size}."
        )
        return unavailable(keys, reason, r.size)
    if flat(r):
        return unavailable(keys, FLAT, r.size)
    value = sample_entropy(r, params["m"], params["r_frac"])
    return finished(
        {"sample_entropy": value, "m": params["m"], "tolerance": params["r_frac"]},
        "No pair of patterns matched within the tolerance.",
    )


def lz_complexity(bits: list[int]) -> int:
    """Number of parts in the Lempel-Ziv (1976) parse, by the Kaspar-Schuster (1987) algorithm."""
    n = len(bits)
    if n < 2:
        return n
    i, k, size, parts, longest = 0, 1, 1, 1, 1
    while True:
        if bits[i + k - 1] == bits[size + k - 1]:
            k += 1
            if size + k > n:
                return parts + 1
        else:
            longest = max(k, longest)
            i += 1
            if i == size:
                parts += 1
                size += longest
                if size + 1 > n:
                    return parts
                i, k, longest = 0, 1, 1
            else:
                k = 1


def lz_reading(r: FloatArray) -> dict[str, float]:
    import math

    bits = [int(v > 0) for v in r]
    n = len(bits)
    parts = lz_complexity(bits)
    return {
        "complexity": parts,
        "normalised": parts * math.log2(n) / n,
        "up_share": sum(bits) / n,
    }


def _lz(inputs: Inputs, params: dict[str, Any], rng: Generator | None) -> Result:
    keys = ("complexity", "normalised", "up_share")
    r = inputs.stored.scored_returns()
    if r.size < 64:
        return too_little(keys, 64, r.size)
    return finished(lz_reading(r), "Undefined.")


def permutation_entropy_of(x: FloatArray, order: int) -> float:
    """Bandt & Pompe (2002) permutation entropy, scaled by log2(order!) to lie in 0 to 1."""
    import math

    import numpy as np

    from alpha_patterns.entropy import ordinal_patterns

    codes = ordinal_patterns(x, order)[order - 1 :].astype(np.intp)
    p = np.bincount(codes, minlength=math.factorial(order)) / len(codes)
    p = p[p > 0]
    return float(-(p * np.log2(p)).sum() / math.log2(math.factorial(order)))


def _permutation(inputs: Inputs, params: dict[str, Any], rng: Generator | None) -> Result:
    import math

    keys, order = ("entropy", "order"), params["order"]
    need = max(30, 5 * math.factorial(order))
    r = inputs.stored.scored_returns()
    if r.size < need:
        return too_little(keys, need, r.size)
    return finished({"entropy": permutation_entropy_of(r, order), "order": order}, "Undefined.")


def _out(key: str, label: str, gloss: str, unit: Any = "ratio") -> Output:
    return Output(key, label, gloss, unit)


CHECKS = (
    make(
        "sample_entropy",
        "How irregular is the return series?",
        (
            Param("m", int, 2, (1, 2, 3), "Length of the patterns compared, in bars."),
            Param(
                "r_frac",
                float,
                0.2,
                (0.1, 0.15, 0.2, 0.25, 0.3),
                "Match tolerance as a share of the return spread.",
            ),
        ),
        (
            _out("sample_entropy", "Sample entropy", "Higher means less repeating structure."),
            _out("m", "Pattern length", "Days per pattern.", "count"),
            _out(
                "tolerance",
                "Tolerance",
                "Match tolerance as a share of the return spread.",
                "fraction",
            ),
        ),
        "The sample entropy is {sample_entropy:.3f} for patterns of {m:.0f} bars at a tolerance of"
        " {tolerance:.0%} of the return spread. Higher means patterns repeated less often than"
        " lower; random noise of a similar shape gives a high value.",
        "Richman & Moorman (2000). It has no fixed level and no p-value; read it next to the other"
        " checks. Its size depends on the tolerance and pattern length. It is read up to"
        " 10,000 bars.",
        _sample_entropy,
        "test_known_sample_entropy",
        situations=("behaviour-change",),
    ),
    make(
        "compressibility",
        "How compressible are the up and down bars?",
        (),
        (
            _out(
                "complexity",
                "Parts",
                "Parts in the Lempel-Ziv parse of the up/down sequence.",
                "count",
            ),
            _out(
                "normalised",
                "Relative complexity",
                "Parts scaled so a fair random sequence reads about 1.",
            ),
            _out("up_share", "Up share", "Share of bars with a positive return.", "fraction"),
        ),
        "The up and down bars parse into {complexity:.0f} parts, a relative complexity of"
        " {normalised:.2f}. A fair random sequence reads about one; lower means more repetition,"
        " though a lopsided share of up bars ({up_share:.0%} here) also lowers it.",
        "Lempel & Ziv (1976). Direction only; it does not give a p-value and cannot say whether"
        " the repetition can be used.",
        _lz,
        "test_known_compressibility",
        situations=("trade-streaks",),
    ),
    make(
        "permutation_entropy",
        "How ordered is the sequence of returns?",
        (Param("order", int, 3, (3, 4, 5), "Number of bars in each ordering pattern."),),
        (
            _out(
                "entropy",
                "Permutation entropy",
                "0 for a fully ordered series, 1 when every ordering is equally common.",
            ),
            _out("order", "Pattern length", "Days per ordering pattern.", "count"),
        ),
        "The permutation entropy over patterns of {order:.0f} bars is {entropy:.3f}. A value of"
        " one means every ordering of up and down moves was equally common; lower means some"
        " orderings were favoured.",
        "Bandt & Pompe (2002). It needs many more bars than orderings; it describes order, not"
        " whether the order can be used.",
        _permutation,
        "test_known_permutation_entropy",
        situations=("behaviour-change",),
    ),
)
