"""Fail-closed empirical run-context validation at CLI and web boundaries."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from alpha_cli import run_context
from alpha_core import DataError
from alpha_web import run_authority


def test_cli_run_context_accepts_only_exact_standalone_and_governed_shapes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(run_context.RUN_CONTEXT_ENV, raising=False)
    assert run_context.run_context_from_environment() is None

    standalone = {
        "schema_version": 1,
        "kind": "standalone_sandbox",
        "watermark": run_context.STANDALONE_UNQUALIFIED,
    }
    monkeypatch.setenv(run_context.RUN_CONTEXT_ENV, json.dumps(standalone))
    assert run_context.run_context_from_environment() == standalone

    for gate_state, watermark in (
        ("passed", None),
        ("not_required", None),
        ("overridden", "EXPLORATORY"),
    ):
        governed = {
            "schema_version": 1,
            "kind": "governed_project",
            "project_id": "project-1",
            "research_gate_state": gate_state,
            "watermark": watermark,
        }
        monkeypatch.setenv(run_context.RUN_CONTEXT_ENV, json.dumps(governed))
        assert run_context.run_context_from_environment() == governed


@pytest.mark.parametrize(
    "raw",
    [
        "not-json",
        "[]",
        '{"schema_version":2,"kind":"standalone_sandbox"}',
        '{"schema_version":1,"kind":"standalone_sandbox","watermark":"wrong"}',
        '{"schema_version":1,"kind":"governed_project","project_id":"","research_gate_state":"passed"}',
        '{"schema_version":1,"kind":"governed_project","project_id":"p","research_gate_state":"open"}',
        '{"schema_version":1,"kind":"governed_project","project_id":"p","research_gate_state":"overridden"}',
        '{"schema_version":1,"kind":"unknown"}',
    ],
)
def test_cli_run_context_rejects_malformed_or_untrusted_shapes(
    monkeypatch: pytest.MonkeyPatch, raw: str
) -> None:
    monkeypatch.setenv(run_context.RUN_CONTEXT_ENV, raw)
    with pytest.raises(DataError, match="Workstation run context"):
        run_context.run_context_from_environment()


def test_web_resolver_labels_standalone(tmp_path: Path) -> None:
    assert run_authority.resolve_run_context(
        kind="standalone_sandbox", project_id=None, data_dir=tmp_path
    ) == {
        "schema_version": 1,
        "kind": "standalone_sandbox",
        "watermark": "STANDALONE_UNQUALIFIED",
    }


def test_web_resolver_fails_closed_before_launch(tmp_path: Path) -> None:
    with pytest.raises(run_authority.RunContextDenied, match="cannot name a project"):
        run_authority.resolve_run_context(
            kind="standalone_sandbox", project_id="project-1", data_dir=tmp_path
        )
    for project_id in (None, "project-1"):
        with pytest.raises(run_authority.RunContextDenied, match="no longer available") as caught:
            run_authority.resolve_run_context(
                kind="governed_project", project_id=project_id, data_dir=tmp_path
            )
        assert caught.value.status_code == 422
