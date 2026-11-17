"""Plain comparisons for ratios of two falls."""

import math


def fall_comparison(ratio: float) -> str:
    if not math.isfinite(ratio) or ratio < 0:
        raise ValueError("fall ratio must be finite and nonnegative")
    percent = round(abs(ratio - 1) * 100)
    # A difference that rounds to 0% reads "about as much"; "fell 0% less" would contradict itself.
    if percent == 0:
        return "fell about as much as"
    return f"fell {percent}% {'less' if ratio < 1 else 'more'} than"
