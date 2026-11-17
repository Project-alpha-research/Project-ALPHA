"""Conservative inference for exploratory factors; these rules grant no authority."""

from __future__ import annotations

import math
from dataclasses import asdict
from typing import Any

import numpy as np

from alpha_core import DataError
from alpha_research._arrays import average_ranks
from alpha_validation.dsr import deflated_sharpe, expected_max_sharpe, probabilistic_sharpe_ratio
from alpha_validation.proportion import autocorrelation_effective_size as old_effective_size

FACTOR_DEFLATION_RULE = "family-looks-x2-floor-1"
SCREEN_RULE = "alpha-investing-simple-1"
SCREEN_ALPHA = 0.10
DEPENDENCE_RULE = "cgm-two-way-newey-west-1"
DECLARATION_RULE = "declared-sign-primary-clock-1"
# Measured 2026-11-17 on the frozen run-3 panel (141 coins): 6,000 seeded pure-noise factors
# (2,000 each of iid, AR(1) phi 0.985 and 189-day rolling-sum noise), each with a random declared
# sign and weekly/monthly clock, through these rules: 0 became CANDIDATE, even at the loosest
# cutoff (m = 1). The Wilson 95% upper bound 0.00064 is rounded up. Re-measure when rules change.
CHANCE_PASS_RATE_PER_FACTOR = 0.001
CHANCE_PASS_RATE_DATE = "2026-11-17"
CHANCE_PASS_RATE_NOTE = (
    "upper bound from 0 of 6,000 pure-noise factors; must be re-measured when the rules change"
)


def screen_cutoff(m: int, confirmed: int) -> float:
    """ALPHA design: earlier confirmed candidates alone earn screen credit."""
    if type(m) is not int or m < 1 or type(confirmed) is not int or confirmed < 0:
        raise DataError("screen counts must be non-negative integers with m >= 1")
    return SCREEN_ALPHA * (1 + confirmed) / m


def factor_deflation(returns: np.ndarray, sharpes: list[float], looks: int) -> dict[str, Any]:
    """Bailey & Lopez de Prado (2014), DSR via the public PSR/expected-max seam.

    N=2*looks and max(sample variance, 1/(T-1)) are ALPHA design, not literature claims.
    The public standalone result supplies the unchanged threshold and Sharpe conventions.
    """
    result = asdict(deflated_sharpe(returns))
    if looks < 1 or not sharpes or not np.isfinite(sharpes).all():
        raise DataError("factor deflation requires counted looks and finite replay Sharpes")
    sample = float(np.var(sharpes, ddof=1)) if len(sharpes) > 1 else 0.0
    floor = 1 / (len(returns) - 1)
    variance = max(sample, floor)
    benchmark = expected_max_sharpe(variance, 2 * looks)
    dsr = probabilistic_sharpe_ratio(returns, benchmark_sr=benchmark)
    result.update(
        dsr=dsr,
        expected_max_sharpe=benchmark,
        n_trials=2 * looks,
        passed=dsr >= result["threshold"],
        deflation_n=2 * looks,
        deflation_variance=variance,
        deflation_variance_term="sample_variance" if sample >= floor else "sampling_floor",
        deflation_rule=FACTOR_DEFLATION_RULE,
    )
    return result


def newey_west(values: np.ndarray) -> dict[str, Any]:
    """Newey & West (1987), Econometrica 55(3): Bartlett-weighted HAC long-run variance.

    Autocovariances use denominator n. The lag ceil(4*(n/100)**(2/9)) is ALPHA's fixed rule.
    Effective n is capped at n, so negative dependence never earns additional observations.
    """
    x = np.asarray(values, dtype=float)
    if x.ndim != 1 or x.size < 2 or not np.isfinite(x).all():
        raise DataError("Newey-West requires at least two finite observations")
    x = x - x.mean()
    gamma0 = float(x @ x) / len(x)
    if gamma0 <= 0:
        raise DataError("Newey-West requires varying observations")
    lag = math.ceil(4 * (len(x) / 100) ** (2 / 9))
    lrv = gamma0 + 2 * sum(
        (1 - k / (lag + 1)) * float(x[k:] @ x[:-k]) / len(x) for k in range(1, lag + 1)
    )
    if lrv <= 0 or not math.isfinite(lrv):
        raise DataError("Newey-West long-run variance is not positive")
    return {
        "lag": lag,
        "long_run_variance": lrv,
        "effective_n": min(float(len(x)), len(x) * gamma0 / lrv),
    }


def autocorrelation_effective_size(values: np.ndarray) -> float:
    """Effective size implied by the Newey-West long-run variance, capped at raw n."""
    return float(newey_west(values)["effective_n"])


def clustered_mean_variance(cells: np.ndarray) -> float:
    """Cameron, Gelbach & Miller (2011), JBES 29(2), two-way sandwich V_date+V_name-V_cell.

    Each date has equal weight; missing cells have zero influence. One-way components use
    G/(G-1) corrections. See `clustered_variance` for a nonpositive two-way sandwich.
    """
    return clustered_variance(cells)[0]


def clustered_variance(cells: np.ndarray) -> tuple[float, str]:
    """The CGM two-way variance and which term applied.

    The two-way sandwich can be nonpositive in finite samples. Cameron, Gelbach & Miller
    (2011, section 2.3) then use the larger one-way variance, which is never smaller than the
    date-clustered variance the plain screen uses, so the fallback cannot add significance.
    Only when that is nonpositive too does the screen fail loud.
    """
    finite = np.isfinite(cells)
    counts = finite.sum(axis=1)
    usable = counts > 0
    data = cells[usable]
    finite = finite[usable]
    counts = counts[usable]
    dates, names, total = len(data), int(finite.any(axis=0).sum()), int(finite.sum())
    if min(dates, names) < 2:
        raise DataError("clustered screen needs multiple dates and instruments")
    mean = float(np.mean(np.nansum(data, axis=1) / counts))
    influence = np.where(finite, data - mean, 0) / counts[:, None] / dates
    by_date = dates / (dates - 1) * float(np.square(influence.sum(axis=1)).sum())
    by_name = names / (names - 1) * float(np.square(influence.sum(axis=0)).sum())
    variance = by_date + by_name - total / (total - 1) * float(np.square(influence).sum())
    if not math.isfinite(variance):
        raise DataError("two-way clustered variance is not finite")
    if variance > 0:
        return variance, "two_way"
    if max(by_date, by_name) > 0:
        return max(by_date, by_name), "one_way_max_fallback"
    raise DataError("clustered variance is not positive")


def rank_cells(signal: np.ndarray, outcome: np.ndarray, min_names: int = 5) -> np.ndarray:
    """Spearman (1904): standardized average-rank products, with daily mean equal to IC."""
    cells = np.full(signal.shape, np.nan)
    for i, (scores, returns) in enumerate(zip(signal, outcome, strict=True)):
        mask = np.isfinite(scores) & np.isfinite(returns)
        n = int(mask.sum())
        if n < min_names:
            continue
        x, y = average_ranks(scores[mask]), average_ranks(returns[mask])
        x, y = x - x.mean(), y - y.mean()
        norm = float(np.linalg.norm(x) * np.linalg.norm(y))
        if norm > 0:
            cells[i, mask] = n * x * y / norm
    return cells


def screen_statistics(
    signal: np.ndarray, outcome: np.ndarray, daily: np.ndarray, direction: int | None
) -> dict[str, Any]:
    """Combine historical, NW and CGM p-values by maximum, never by choosing the best."""
    mean, sd = float(daily.mean()), float(daily.std(ddof=1))
    nw = newey_west(daily)
    old_n = old_effective_size(daily)
    effective = float(nw["effective_n"])
    old_z = mean / (sd / math.sqrt(old_n))
    z = mean / (sd / math.sqrt(effective))
    variance, term = clustered_variance(rank_cells(signal, outcome))
    cluster_z = mean / math.sqrt(variance)
    plain = math.erfc(abs(old_z) / math.sqrt(2))
    cluster = math.erfc(abs(cluster_z) / math.sqrt(2))
    conservative = max(plain, cluster, math.erfc(abs(z) / math.sqrt(2)))
    result: dict[str, Any] = {
        "plain_p": plain,
        "clustered_p": cluster,
        "two_sided_p": conservative,
        "old_z": old_z,
        "z": z,
        "effective_n": effective,
        "newey_west": nw,
        "clustered_variance": variance,
        "clustered_variance_term": term,
        "dependence_rule": DEPENDENCE_RULE,
    }
    if direction is None:
        result["p"] = conservative
    else:
        if type(direction) is not int or direction not in (-1, 1):
            raise DataError("declared_direction must be +1 or -1")
        signed = [
            0.5 * math.erfc(direction * score / math.sqrt(2)) for score in (old_z, z, cluster_z)
        ]
        opposite = [
            0.5 * math.erfc(-direction * score / math.sqrt(2)) for score in (old_z, z, cluster_z)
        ]
        result.update(
            p=max(signed),
            diagnostics={
                "opposite_direction_p": max(opposite),
                "label": "diagnostic only: cannot pass",
            },
        )
    return result


def chance_note(count: int) -> str:
    return (
        f"Expected chance passes: {count * CHANCE_PASS_RATE_PER_FACTOR:.4g} "
        f"({count} evaluable factors × {CHANCE_PASS_RATE_PER_FACTOR}; measured pure-noise rate "
        f"dated {CHANCE_PASS_RATE_DATE}; {CHANCE_PASS_RATE_NOTE})."
    )


def chance_fields(count: int) -> dict[str, Any]:
    return {
        "evaluable_factors": count,
        "chance_pass_rate": CHANCE_PASS_RATE_PER_FACTOR,
        "chance_pass_rate_date": CHANCE_PASS_RATE_DATE,
        "expected_chance_passes": count * CHANCE_PASS_RATE_PER_FACTOR,
        "chance_pass_message": chance_note(count),
    }
