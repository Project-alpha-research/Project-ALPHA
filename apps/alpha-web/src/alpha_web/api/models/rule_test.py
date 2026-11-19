"""What a rule test (``alpha test``) recorded: the idea, labels and stored diagnostics."""

from __future__ import annotations

from typing import Literal

from ._base import StrictModel


class RuleTestFlag(StrictModel):
    flag: str
    detail: str


class RuleTestAuditItem(StrictModel):
    check: str
    status: str
    detail: str


class RuleTestPerformance(StrictModel):
    basis: str | None
    total_return: float | None
    cagr: float | None
    sharpe: float | None
    max_drawdown: float | None
    # metric name -> why the stored value is null
    reasons: dict[str, str]


class RuleTestFullSample(RuleTestPerformance):
    trades: int | None
    exposure: float | None


class RuleTestDifference(StrictModel):
    total_return: float | None
    cagr: float | None
    sharpe: float | None
    max_drawdown: float | None
    reasons: dict[str, str]


class RuleTestBenchmark(RuleTestPerformance):
    strategy_minus_benchmark: RuleTestDifference | None


class RuleTestVariant(RuleTestPerformance):
    name: str
    kind: str | None


class RuleTestSensitivity(StrictModel):
    basis: str | None
    variants: list[RuleTestVariant]


class RuleTestDelay(StrictModel):
    basis: str | None
    base_sharpe: float | None
    delayed_sharpe: float | None
    reasons: dict[str, str]


class RuleTestYear(StrictModel):
    year: int
    strategy_return: float | None
    benchmark_return: float | None


class RuleTestByYear(StrictModel):
    basis: str | None
    strategy_positive_years: int | None
    benchmark_positive_years: int | None
    years: list[RuleTestYear]


class RuleTestConcentration(StrictModel):
    basis: str | None
    top_1: float | None
    top_3: float | None
    reasons: dict[str, str]


class RuleTestTrials(StrictModel):
    basis: str | None
    total_trials: int | None
    available_sharpes: int | None
    dsr: float | None
    reasons: dict[str, str]


class RuleTestDrawdown(StrictModel):
    start: str | None
    trough: str | None
    recovery: str | None
    depth: float | None
    benchmark_return: float | None
    share_explained: float | None
    reasons: dict[str, str]


class RuleTestMacroSeries(StrictModel):
    series_id: str
    start_value: float | None
    trough_value: float | None
    change: float | None
    reason: str | None


class RuleTestMacroWindow(StrictModel):
    available: bool
    reason: str | None
    basis: str | None
    start: str | None
    trough: str | None
    as_of: str | None
    series: list[RuleTestMacroSeries]


class RuleTestDiagnostics(StrictModel):
    """``diagnostics.json`` as stored; a part the file does not carry is null."""

    full_sample: RuleTestFullSample | None
    benchmark: RuleTestBenchmark | None
    flags: list[RuleTestFlag]
    audit: list[RuleTestAuditItem]
    by_year: RuleTestByYear | None
    concentration: RuleTestConcentration | None
    sensitivity: RuleTestSensitivity | None
    delay: RuleTestDelay | None
    trials: RuleTestTrials | None
    worst_drawdown: RuleTestDrawdown | None
    macro_window: RuleTestMacroWindow | None
    variants_evaluated: int | None


class RuleTest(StrictModel):
    """Present on a run whose manifest has a ``spine`` key; null on every other run."""

    name: str | None
    idea: str | None
    rule_kind: str | None
    rule_params: dict[str, int]
    # the rule in one plain sentence; null for a rule kind this server cannot describe
    rule_sentence: str | None
    symbol: str | None
    source: str | None
    store: str | None
    labels: list[str]
    test_id: str | None
    first_ts: str | None
    last_ts: str | None
    n_bars: int | None
    fee_bps: float | None
    slippage_bps: float | None
    # ledger trial count when this run's diagnostic pass ran (diagnostics.json: trials)
    total_trials: int | None
    diagnostics: RuleTestDiagnostics | None
    # why `diagnostics` is null
    diagnostics_reason: str | None


class RuleTestCheck(StrictModel):
    """One stored toolbox result for a rule test, or one failed attempt."""

    tool: str
    outcome: Literal["ok", "error"]
    # the stored one-sentence reading; null for a failed attempt
    reading: str | None
    # the stored error code of a failed attempt
    error: str | None
    labels: list[str]
    recorded_at: str | None


class RuleTestChecks(StrictModel):
    """Checks stored for one rule test, oldest first; empty when none were run."""

    run_id: str
    checks: list[RuleTestCheck]
