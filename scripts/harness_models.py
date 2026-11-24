"""Pydantic schemas for harness JSON: doctor reports, the harness baseline,
review and quant-verification reports.

Review and quant reports are advisory output shapes for the reviewer agents; nothing records
or enforces them locally. Hooks never import this module; ``gate.py`` imports it lazily so the
stdlib-only commands keep working before ``uv sync`` has run.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, model_validator


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class QuantClaim(_Strict):
    claim: str
    source: str
    location: str
    verdict: Literal["VERIFIED", "DISCREPANCY", "UNVERIFIABLE"]


class DocstringCitations(_Strict):
    ok: bool
    missing: list[str]


class NumericSpotCheck(_Strict):
    description: str
    expected: float
    observed: float
    tolerance: float
    ok: bool


class QuantVerificationReport(_Strict):
    claims: list[QuantClaim]
    docstring_citations: DocstringCitations
    overall: Literal["PASS", "FAIL"]
    files_reviewed: list[str] = []
    oracles_present: bool | None = None
    numeric_spot_checks: list[NumericSpotCheck] = []

    @model_validator(mode="after")
    def _pass_requires_clean_evidence(self) -> QuantVerificationReport:
        if self.overall == "PASS":
            bad = [c for c in self.claims if c.verdict != "VERIFIED"]
            if bad:
                raise ValueError(
                    "overall=PASS but non-VERIFIED claims exist: " + "; ".join(c.claim for c in bad)
                )
            if not self.docstring_citations.ok or self.docstring_citations.missing:
                raise ValueError("overall=PASS but docstring citations are missing")
            if self.oracles_present is False:
                raise ValueError("overall=PASS but oracles_present is False")
            if any(not c.ok for c in self.numeric_spot_checks):
                raise ValueError("overall=PASS but a numeric spot check failed")
        return self


class ReviewFinding(_Strict):
    severity: Literal["high", "medium", "low"]
    file: str
    line: int
    summary: str


class SecondOpinionDisposition(_Strict):
    finding: str
    disposition: Literal["agree", "refute", "out_of_scope"]
    reason: str


class ReviewVerdict(_Strict):
    verdict: Literal["APPROVE", "BLOCK"]
    findings: list[ReviewFinding]
    plan_ref: str | None = None
    reviewed_diff_hash: str
    files_reviewed: list[str]
    reviewed_tree_hash: str | None = None
    tests_run: list[str] = []
    second_opinion: list[SecondOpinionDisposition] = []
    codex_unavailable: bool = False


class DoctorCheck(_Strict):
    name: str
    ok: bool
    detail: str


class DoctorReport(_Strict):
    created_at: str
    checks: list[DoctorCheck]
    ok: bool


class HarnessBaseline(_Strict):
    """Explicit safety configuration; actual tests enforce architecture and bias controls."""

    schema_version: Literal[2] = 2
    deny_rules: list[str]
    hook_events: list[str]
    coverage_fail_under: int
    strict_markers: bool
    quant_suppressions: int


class InvariantFinding(_Strict):
    family: Literal["look_ahead", "determinism", "architecture"]
    severity: Literal["high", "medium", "low"]
    file: str
    line: int
    summary: str


class InvariantFindings(_Strict):
    findings: list[InvariantFinding]


class Counterexample(_Strict):
    target: str
    input_description: str
    expected_failure: str
    proposed_test: str


class Counterexamples(_Strict):
    counterexamples: list[Counterexample]
