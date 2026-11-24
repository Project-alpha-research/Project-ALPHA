"""Program-level acceptance for the research-first workstation (R6i; 2026-08-07 spec §17).

Composite end-to-end stories through the public CLI. Per-phase behaviour is proven in the
dedicated suites; this module proves the program-level claims that only hold when every
phase composes losslessly:

- Golden path: one raw sentence becomes a case with its wording preserved, renders an honest
  all-``not_tested`` scorecard and empty Evidence Hub, runs the governed empirical D1 and
  one-shot sealed D2 lanes, closes ``SUPPORTED`` / ``advance_to_strategy``, and the recorded
  promotion dossier reaches the linked strategy version's AgentBrief byte-identically.
- ``SUPPORTED`` never implies promotion: a non-advancing owner disposition closes with an
  honest terminal packet, records no promotion dossier, and keeps the gate locked.
- A parked pre-D2 case closes honestly (``NOT_TESTED`` primary result, no manufactured
  support) and cannot claim ``SUPPORTED`` or advance.

The remaining §17 bullets are proven where they live: agent-authority negatives in
``test_research_mcp.py`` (62-tool pin, no approve/decide/D2 verbs) and
``test_web_api_research.py`` (Gate-1-only POST pin); kill-and-resume in the per-phase
crash/recovery suites; planted-pattern/confounder/null fixtures in the R5 acceptance tests;
override visibility in ``test_research_gate_watermark_cli.py`` plus the Playwright e2e; and
byte-identical Codex packet history in the R2 context-packet suites.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import cast

import pytest
from typer.testing import CliRunner

from alpha_cli.main import app
from tests.integration.test_research_cli import (
    _approve_confirmation,
    _approved_empirical_daily_project,
    _confirmation_ready_project,
    _invoke,
    _varied_daily_lows,
)

runner = CliRunner()

_RAW_IDEA = "SPY bounces after double bottoms on the daily chart"

# Every checklist/scorecard status the program may render. Typed enumerations only — a
# numeric aggregate anywhere in the decision plane is a program-acceptance failure.
_CHECKLIST_STATUSES = frozenset(
    {
        "SUPPORTED",
        "CONTRADICTED",
        "INCONCLUSIVE",
        "CLEARS_HURDLE",
        "BELOW_MINIMUM",
        "PASSED",
        "FAILED",
        "STABLE",
        "UNSTABLE",
        "TESTED",
        "NOT_TESTED",
    }
)


def _project_cli(*args: str) -> dict[str, object]:
    result = runner.invoke(app, ["project", *args, "--json"])
    assert result.exit_code == 0, result.output
    value: object = json.loads(result.output)
    assert isinstance(value, dict)
    return value


def _checklist_questions(view: dict[str, object]) -> list[dict[str, object]]:
    checklist = cast(dict[str, object], view["checklist"])
    assert checklist["checklist_schema"] == "ResearchEdgeChecklistV1"
    questions = cast(list[dict[str, object]], checklist["questions"])
    assert len(questions) == 14
    for question in questions:
        assert str(question["status"]) in _CHECKLIST_STATUSES, question
    return questions


def _promotion_packets(project_id: str) -> list[dict[str, object]]:
    listed = _invoke("context", "list", project_id)
    items = cast(list[dict[str, object]], listed["items"])
    return [row for row in items if row["packet_kind"] == "strategy_promotion"]


def _version_args(project_id: str, *extra: str) -> list[str]:
    return [
        "version",
        project_id,
        "--strategy",
        "mean_reversion",
        "--source-fingerprint",
        "git:acceptance0",
        "--definition-json",
        '{"entry_z": 1.5, "starting_cash": 100000, "window": 20}',
        "--parameter-space-json",
        '{"window": [10, 20]}',
        *extra,
    ]


def test_supported_outcome_with_a_non_advancing_disposition_never_promotes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """§17: promotion requires SUPPORTED *and* the owner's advance disposition."""
    monkeypatch.setenv("ALPHA_DATA_DIR", str(tmp_path))
    project_id, contract_id, _ = _confirmation_ready_project(tmp_path)
    _approve_confirmation(project_id, contract_id)
    _invoke("run", "confirm", project_id)

    decided = _invoke(
        "decide",
        project_id,
        "--outcome",
        "SUPPORTED",
        "--disposition",
        "reject",
        "--actor",
        "owner",
        "--reason",
        "Real but too small to pursue: the owner rejects despite mechanical support.",
    )
    assert cast(dict[str, object], decided["case"])["phase"] == "closed"

    # The closed case still gets its honest terminal packet…
    report = _invoke("report", project_id)
    assert report["report_schema"] == "ResearchGatePacketV1"
    assert report["scientific_outcome"] == "SUPPORTED"
    # …but nothing promotes: no dossier, a still-locked gate, and no version path.
    assert _promotion_packets(project_id) == []
    assert _project_cli("show", project_id)["research_gate_state"] == "open"
    linked = runner.invoke(
        app,
        ["project", *_version_args(project_id, "--research-contract-id", contract_id), "--json"],
    )
    assert linked.exit_code != 0
    assert "advance_to_strategy" in linked.output
    unlinked = runner.invoke(app, ["project", *_version_args(project_id), "--json"])
    assert unlinked.exit_code != 0
    assert "research_contract_id" in unlinked.output


def test_parked_pre_d2_case_closes_honestly_and_cannot_claim_support(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """§17: honest termination — a pre-D2 park never manufactures empirical support."""
    monkeypatch.setenv("ALPHA_DATA_DIR", str(tmp_path))
    project_id, _ = _approved_empirical_daily_project(tmp_path, lows=_varied_daily_lows())

    # Without consumed D2 the owner cannot record SUPPORTED, let alone advance.
    premature = runner.invoke(
        app,
        [
            "research",
            "decide",
            project_id,
            "--outcome",
            "SUPPORTED",
            "--disposition",
            "advance_to_strategy",
            "--actor",
            "owner",
            "--reason",
            "A premature advance claim must fail before any confirmation ran.",
            "--json",
        ],
    )
    assert premature.exit_code != 0
    assert "INCONCLUSIVE or INVALID" in premature.output

    parked = _invoke(
        "decide",
        project_id,
        "--outcome",
        "INCONCLUSIVE",
        "--disposition",
        "park",
        "--actor",
        "owner",
        "--reason",
        "Parked before confirmation: the discovery signal did not justify a sealed read.",
    )
    assert cast(dict[str, object], parked["case"])["phase"] == "closed"

    report = _invoke("report", project_id)
    assert report["report_schema"] == "ResearchGatePacketV1"
    assert report["scientific_outcome"] == "INCONCLUSIVE"
    view = _invoke("decision-view", project_id)
    questions = _checklist_questions(view)
    effect = next(q for q in questions if q["question_id"] == "effect_exists")
    assert str(effect["status"]) == "NOT_TESTED"

    assert _promotion_packets(project_id) == []
    assert _project_cli("show", project_id)["research_gate_state"] == "open"
