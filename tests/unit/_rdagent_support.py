"""Shared synthetic inputs and isolated worker definitions for RD-Agent unit tests."""

from __future__ import annotations

import ast
import asyncio
import hashlib
import importlib
import json
import os
import re
import subprocess
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import Mock

import pandas as pd
import pytest

from tests.unit.test_rdagent_factor_judge import WORKER, data


def clock_rows(dsr: float) -> dict[str, Any]:
    return {
        c: {
            "status": "PASS" if c == "weekly" else "SCREEN_FAIL",
            "p": p,
            "q": p,
            "screen": {"mean_ic": p},
            "spread": {"status": "PASS", "horizon_days": 7, "decision_days": 50},
            "replay": {"deflated_sharpe": {"dsr": dsr, "threshold": 0.95, "n_trials": 42}}
            if c == "weekly"
            else {},
        }
        for c, p in (("daily", 0.5), ("weekly", 0.04), ("monthly", 0.7))
    }


def coder_parts() -> dict[str, Any]:
    tree = ast.parse((WORKER / "alpha_factor_coder.py").read_text())
    selected = {"BudgetExhausted", "embedding_failure", "_record_skip", "tolerant_embeddings"}
    nodes: list[ast.stmt] = [
        n
        for n in tree.body
        if isinstance(n, (ast.FunctionDef, ast.ClassDef)) and n.name in selected
    ]
    namespace: dict[str, Any] = {
        "Any": Any,
        "Path": Path,
        "Iterator": Iterator,
        "contextmanager": contextmanager,
        "datetime": datetime,
        "UTC": UTC,
        "json": json,
        "hashlib": importlib.import_module("hashlib"),
        "RESERVED_START": "2024-01-01",
    }
    exec(compile(ast.Module(body=nodes, type_ignores=[]), "coder-contract", "exec"), namespace)
    return namespace


class _Backend:
    """Upstream's shape (pin 484776c, oai/backend/base.py): retries swallow the real error."""

    failures: list[Exception] = []
    calls = 0

    def _create_embedding_with_cache(self, input_content_list: list[str]) -> list[list[float]]:
        type(self).calls += 1
        raise type(self).failures[0]

    def create_embedding(self, content: str) -> list[float]:
        for _ in range(3):
            try:
                return self._create_embedding_with_cache([content])[0]
            except Exception:  # upstream retries every failure, then forgets it
                continue
        raise RuntimeError("Failed to create chat completion after 3 retries.")


class _Graph:
    def add_node(self, node: Any, neighbor: Any = None) -> None:
        node.embedding = _Backend().create_embedding("text")


def _upstream_graph() -> _Graph:
    return _Graph()


def judge_namespace() -> dict[str, Any]:
    """Run ALPHA definitions with inert upstream boundaries; never import a model backend."""

    class Base:
        def prepare_context(self, trace: Any) -> tuple[dict[str, Any], bool]:
            return {"hypothesis_and_feedback": "Old scenario description"}, True

    ns: dict[str, Any] = {
        "Any": Any,
        "Path": Path,
        "os": os,
        "json": json,
        "re": re,
        "hashlib": hashlib,
        "subprocess": subprocess,
        "sys": sys,
        "pd": pd,
        "Developer": object,
        "FactorEmptyError": ValueError,
        "Experiment2Feedback": object,
        "QlibFactorScenario": object,
        "QlibQuantScenario": type("Scenario", (), {}),
        "QlibFactorHypothesisGen": Base,
        "HypothesisFeedback": SimpleNamespace,
        "convert2bool": bool,
    }
    for name in ("current_universe", "check_prefix_invariance"):
        if hasattr(data, name):
            ns[name] = getattr(data, name)
    tree = ast.parse((WORKER / "alpha_factor_judge.py").read_text())
    nodes: list[ast.stmt] = [
        node
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.ClassDef, ast.Assign, ast.AnnAssign))
    ]
    exec(compile(ast.Module(body=nodes, type_ignores=[]), "<loop-fixups>", "exec"), ns)
    return ns


def universe_run(root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (root / "panel").mkdir(parents=True)
    receipt = {"instruments": {f"C{i}": {"last_day": "2023-12-31"} for i in range(141)}}
    (root / "panel/panel-receipt.json").write_text(json.dumps(receipt))
    (root / "panel/universe.json").write_text(
        json.dumps({"survivorship": "141 instruments, 66 later delisted; not survivorship-free"})
    )
    monkeypatch.setenv("ALPHA_FACTOR_RUN_DIR", str(root))
    monkeypatch.delenv("ALPHA_FACTOR_UNIVERSE_TEXT", raising=False)


def closed_volatility_ledger(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    ledger = tmp_path / "ledger"
    rows = [
        {
            "name": f"volatility_{i}",
            "status": "SCREEN_FAIL",
            "code_sha256": str(i),
            "schema": "AlphaRdagentFactorTrialV2",
            "screen": {},
        }
        for i in range(3)
    ]
    ledger.write_text("".join(json.dumps(row) + "\n" for row in rows))
    monkeypatch.setenv("ALPHA_FACTOR_RUN_DIR", str(tmp_path))
    monkeypatch.setenv("ALPHA_FACTOR_TRIAL_LEDGER", str(ledger))
    return ledger


def proposal(name: str, description: str) -> SimpleNamespace:
    task = SimpleNamespace(
        factor_name=name,
        description=description
        + ("\ndeclared_direction: +1; primary_clock: weekly; direction_reason: Demand persists."),
        factor_formulation="",
        variables={},
    )
    return SimpleNamespace(
        sub_tasks=[task], hypothesis=SimpleNamespace(hypothesis=name), based_experiments=[]
    )


class ProposingLoop:
    """The two upstream calls the guard may repeat; records what the proposer was shown."""

    def __init__(self, ns: dict[str, Any], proposals: list[SimpleNamespace]) -> None:
        self.ns = ns
        self.proposals = proposals
        self.shown: list[list[str]] = []
        self.plan = {"features": ["f"], "feature_codes": {"f.py": "code"}}

    def _propose(self) -> str:
        self.shown.append(list(self.ns["FAMILY_REFUSALS"]))
        return "hypothesis"

    def _exp_gen(self, hypothesis: str) -> SimpleNamespace:
        return self.proposals.pop(0)


# The real proposals of runs/2026-11-17-rdagent-wide-universe-2, as RD-Agent listed them: the
# variable names are the proposer's own (math symbols, hyperparameters and features alike).
WIDE_RUN_CLOSED = {
    "composite: unknown inputs",
    "illiquidity",
    "past return (momentum or reversal)",
    "price near its high / range position",
    "range and compression",
    "return-volume relation",
    "intraday return and gaps",
    "skewness and lottery returns",
    "volatility and beta",
    "volume level and trend",
}


def upstream_class(path: str, name: str, methods: set[str], namespace: dict[str, Any]) -> Any:
    source = os.environ.get("ALPHA_RDAGENT_SOURCE")
    if not source:
        pytest.skip("read-only pinned RD-Agent source is not configured")
    tree = ast.parse((Path(source) / "rdagent" / path).read_text())
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == name)
    cls.bases, cls.keywords, cls.decorator_list = [], [], []
    cls.body = [
        n
        for n in cls.body
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name in methods
    ]
    future = ast.ImportFrom(module="__future__", names=[ast.alias(name="annotations")], level=0)
    tree = ast.fix_missing_locations(ast.Module(body=[future, cls], type_ignores=[]))
    exec(compile(tree, path, "exec"), namespace)
    return namespace[name]


def failed_call(calls: Path, code: str = "provider_timeout") -> None:
    with calls.open("a") as stream:
        stream.write(
            json.dumps(
                {
                    "run_id": "test",
                    "endpoint": "/v1/chat/completions",
                    "error_code": code,
                    "attempts": 2,
                    "latency_ms": 360000,
                }
            )
            + "\n"
        )
    raise RuntimeError("Failed to create chat completion after 2 retries.")


@pytest.fixture
def unfinished_session(tmp_path: Path) -> Path:
    session = tmp_path / "work/log/__session__"
    (session / "0").mkdir(parents=True)
    (session / "0/0_direct_exp_gen").touch()
    (tmp_path / "steps.jsonl").write_text(
        json.dumps({"loop": 0, "event": "end", "status": "error"}) + "\n"
    )
    return session


def pinned_loop(tmp_path: Path, ns: dict[str, Any], skip_error: type[Exception]) -> Any:
    cls = upstream_class(
        "components/workflow/rd_loop.py",
        "RDLoop",
        {"direct_exp_gen", "coding", "running", "feedback", "record"},
        ns,
    )
    base = upstream_class("utils/workflow/loop.py", "LoopBase", {"_run_step"}, ns)
    loop = cls()
    loop._run_step = base._run_step.__get__(loop)
    loop.steps = ["direct_exp_gen", "coding", "running", "feedback", "record"]
    loop.step_idx, loop.loop_prev_out, loop.loop_trace = (
        {0: 0, 1: 0},
        {0: {}, 1: {}},
        {0: [], 1: []},
    )
    loop.EXCEPTION_KEY, loop.LOOP_IDX_KEY = "exception", "loop"
    loop.skip_loop_error, loop.skip_loop_error_stepname = skip_error, "feedback"
    loop.withdraw_loop_error = ()
    loop.get_semaphore = lambda _: asyncio.Semaphore(1)
    loop.tracker, loop.pbar = (
        SimpleNamespace(log_workflow_state=Mock()),
        SimpleNamespace(set_postfix=Mock()),
    )
    loop.dump, loop._check_exit_conditions_on_step = Mock(), Mock()
    loop.session_folder = tmp_path
    loop.get_unfinished_loop_cnt = lambda _: 0
    loop.plan = {"features": [], "feature_codes": {}}
    loop.trace = SimpleNamespace(sync_dag_parent_and_hist=Mock())
    return loop
