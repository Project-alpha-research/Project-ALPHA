"""Tear-sheet report schema (``alpha_validation.tearsheet``).

Grows across the Phase-5 steps; this first slice pins the report dataclasses and their public
export. Manifest serialization and HTML rendering are exercised once those helpers land.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
import math

import pytest

from alpha_core import ValidationOutcome
from alpha_validation import (
    CISummary,
    CPCVSummary,
    DSRSummary,
    FoldSummary,
    GauntletReport,
    NullSummary,
    RunMetadata,
    VerdictSummary,
    build_outcomes,
    report_to_manifest,
    tearsheet,
)


def _report() -> GauntletReport:
    meta = RunMetadata(
        run_id="abc123",
        symbol="SPY",
        snapshot_id=None,
        seed=7,
        periods_per_year=252,
        fee_bps=1.0,
        slippage_bps=2.0,
        starting_cash=1_000_000.0,
        lookback=252,
        skip=21,
        vol_window=63,
        target_vol=0.15,
        rebalance_every=21,
        max_leverage=1.0,
        allow_short=True,
        train_size=300,
        test_size=60,
        embargo=5,
        anchored=False,
        n_bars=800,
        first_ts="2018-01-02T00:00:00+00:00",
        last_ts="2021-03-01T00:00:00+00:00",
        quantstats_version="1.1.5",
    )
    return GauntletReport(
        metadata=meta,
        oos_metrics={"sharpe": 0.8, "cagr": 0.12},
        folds=(FoldSummary(0, 0, 300, 300, 360, 60, 0.02, 0.5, 0.09),),
        nulls=(NullSummary("returns_level", 0.8, 0.97, 0.03, 0.95, True, 1000),),
        cis=(CISummary("sharpe", 0.8, 0.1, 1.4, 0.95),),
        outcomes=(ValidationOutcome(name="walk_forward_oos", passed=True, detail={"sharpe": 0.8}),),
        passed=True,
    )


def test_report_assembles_and_holds_core_outcomes() -> None:
    report = _report()
    assert report.passed is True
    assert report.outcomes[0].name == "walk_forward_oos"
    assert isinstance(report.outcomes[0], ValidationOutcome)
    assert report.nulls[0].tier == "returns_level"


def test_report_pieces_are_frozen() -> None:
    report = _report()
    with pytest.raises(dataclasses.FrozenInstanceError):
        report.metadata.seed = 9  # type: ignore[misc]


def test_manifest_is_strict_json_with_nan_as_null() -> None:
    # a flat fold has an undefined (NaN) Sharpe; the manifest must still be valid JSON
    report = dataclasses.replace(
        _report(),
        folds=(FoldSummary(0, 0, 300, 300, 360, 60, 0.0, math.nan, math.nan),),
    )
    manifest = report_to_manifest(report)
    assert set(manifest) >= {
        "schema_version",
        "run_id",
        "metadata",
        "oos_metrics",
        "folds",
        "passed",
    }
    assert manifest["folds"][0]["oos_sharpe"] is None  # NaN -> null, not the JSON token NaN
    text = json.dumps(manifest, allow_nan=False, sort_keys=True)  # raises if any NaN survived
    assert json.loads(text)["run_id"] == "abc123"


def test_manifest_is_deterministic() -> None:
    a = json.dumps(report_to_manifest(_report()), sort_keys=True)
    b = json.dumps(report_to_manifest(_report()), sort_keys=True)
    assert a == b  # byte-identical for identical runs (spec §11.4)


def test_manifest_verdict_is_null_when_absent() -> None:
    # The Verdict is an optional, back-compat field; absent it serializes as `verdict: null`.
    manifest = report_to_manifest(_report())
    assert manifest["verdict"] is None


def test_manifest_serializes_the_verdict_block() -> None:
    verdict = VerdictSummary(
        edge="B",
        robustness="A",
        risk="C",
        sample="A",
        overall="B",
        detail={"edge_sharpe": 1.2, "risk_of_ruin": 0.04, "overall_gpa": 2.75},
    )
    manifest = report_to_manifest(dataclasses.replace(_report(), verdict=verdict))
    assert manifest["verdict"]["overall"] == "B"
    assert manifest["verdict"]["edge"] == "B"
    assert manifest["verdict"]["detail"]["risk_of_ruin"] == pytest.approx(0.04)
    json.dumps(manifest, allow_nan=False, sort_keys=True)  # raises if a NaN leaked into the block


def test_build_outcomes_gate_pass_logic() -> None:
    metrics = {"sharpe": 0.8, "cagr": 0.1}
    both_pass = [
        NullSummary("returns_level", 0.8, 0.97, 0.03, 0.95, True, 1000),
        NullSummary("full_engine", 0.8, 0.98, 0.02, 0.95, True, 64),
    ]
    edge_ci = [CISummary("sharpe", 0.8, 0.2, 1.4, 0.95)]  # lower clears zero
    outcomes = build_outcomes(oos_metrics=metrics, nulls=both_pass, cis=edge_ci)
    by_name = {o.name: o for o in outcomes}
    assert {"walk_forward_oos", "randomized_price_null", "bootstrap_ci"} == set(by_name)
    assert all(o.passed for o in outcomes)

    # any failing tier fails the null gate (conservative)
    one_fails = [both_pass[0], dataclasses.replace(both_pass[1], passed=False)]
    assert not _named(
        build_outcomes(oos_metrics=metrics, nulls=one_fails, cis=edge_ci), "randomized_price_null"
    ).passed

    # a Sharpe CI straddling zero fails the bootstrap gate
    zero_ci = [CISummary("sharpe", 0.4, -0.1, 1.0, 0.95)]
    assert not _named(
        build_outcomes(oos_metrics=metrics, nulls=both_pass, cis=zero_ci), "bootstrap_ci"
    ).passed


def _named(outcomes: tuple[ValidationOutcome, ...], name: str) -> ValidationOutcome:
    return next(o for o in outcomes if o.name == name)


def _full_report(*, met: bool) -> GauntletReport:
    """A report with every optional block, with each check on one chosen side of its old level."""
    nan = float("nan")
    return dataclasses.replace(
        _report(),
        oos_metrics={
            "sharpe": 0.8,
            "value_at_risk": 0.018,
            "risk_of_ruin": nan,
            "max_drawdown": -0.08,
        },
        nulls=(
            NullSummary("returns_level", 0.8, 0.97, 0.03, 0.95, met, 1000),
            NullSummary("full<engine>", 0.8, 0.5, 0.5, 0.95, not met, 64),
        ),
        verdict=VerdictSummary(
            edge="B", robustness="A", risk="C", sample="A", overall="B", detail={}
        ),
        dsr=DSRSummary(0.05, 0.91, 0.62, 0.11, 12, 0.95, met),
        cpcv=CPCVSummary(15, 0.4, 0.3, 0.8, met),
    )


@pytest.mark.parametrize(
    ("met", "digest"),
    [
        (True, "b8c5a05544bd592fae560fe79ed7700dd240d1e3d8aa5acd02a70fb62fb0c1e6"),
        (False, "48cda142cb7d522a02508efc99ab9932d19e4662134f2349bdd91db684898b1b"),
    ],
)
def test_gauntlet_section_html_is_pinned_and_gives_readings(met: bool, digest: str) -> None:
    section = tearsheet._validation_section_html(_full_report(met=met))

    # readings, not verdicts: a side of the old level, never a pass/fail word or an overall verdict
    for word in ("PASS", "FAIL", "Overall verdict", "passed", "failed"):
        assert word not in section, word
    first, second = ("at or above", "below") if met else ("below", "at or above")
    assert f"<td>0.9500</td><td>{first}</td><td>1000</td>" in section
    assert f"<td>0.9500</td><td>{second}</td><td>64</td>" in section
    assert f"<td>0.9500</td><td>{first}</td></tr></table>" in section  # the Deflated Sharpe row
    assert f"<td>0.8000</td><td>{'above' if met else 'at or below'}</td></tr></table>" in section
    assert "full&lt;engine&gt;" in section  # text from the run is escaped
    assert "<td>Risk of Ruin</td><td>n/a</td>" in section  # a non-finite number is not printed
    assert "Old grade (kept for old records)" in section
    # every other byte of the section: a changed word, tag or number format changes this digest
    assert hashlib.sha256(section.encode("utf-8")).hexdigest() == digest


def test_gauntlet_section_omits_the_blocks_that_were_not_computed() -> None:
    section = tearsheet._validation_section_html(_report())

    for heading in (
        "Old grade",
        "Risk Metrics",
        "Deflated / Probabilistic Sharpe",
        "Combinatorial",
    ):
        assert heading not in section, heading
    assert "This page gives numbers, not a verdict." in section
