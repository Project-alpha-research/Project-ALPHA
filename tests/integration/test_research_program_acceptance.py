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
from typing import cast

from typer.testing import CliRunner

from alpha_cli.main import app
from tests.integration.test_research_cli import (
    _invoke,
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
