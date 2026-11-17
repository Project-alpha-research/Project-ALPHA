"""Socket-free worker regressions; upstream classes are replaced only at import seams."""

from __future__ import annotations

import ast
import importlib
import json
import sys
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import Mock

import pytest

from tests.unit.test_rdagent_factor_judge import swing_parts

WORKER = Path(__file__).resolve().parents[2] / "workers/rdagent"
sys.path.insert(0, str(WORKER))
launch = importlib.import_module("factor_loop_launch")
memory = importlib.import_module("research_memory")
gateway = importlib.import_module("model_gateway")


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
    }
    exec(compile(ast.Module(body=nodes, type_ignores=[]), "coder-contract", "exec"), namespace)
    return namespace


@pytest.mark.parametrize("wrapped", [False, True])
def test_budget_refusal_is_not_a_memory_skip(tmp_path: Path, wrapped: bool) -> None:
    ns = coder_parts()
    cap = gateway.GatewayError(429, "budget_exhausted", "budget exhausted: run calls")
    error: Exception = RuntimeError("Failed to get chat completion") if wrapped else cap
    if wrapped:
        error.__cause__ = cap
    graph = SimpleNamespace(add_node=Mock(side_effect=error))
    record = tmp_path / "memory-skips.jsonl"
    with (
        pytest.raises(ns["BudgetExhausted"], match="budget exhausted"),
        ns["tolerant_embeddings"](graph, record),
    ):
        graph.add_node(SimpleNamespace(embedding=None))
    assert not record.exists()


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


def test_budget_refusal_behind_upstream_retries_stops_at_once(tmp_path: Path) -> None:
    """The real 2026-11-17 shape: the RuntimeError carries no cause, yet the cap is seen."""
    ns = coder_parts()
    _Backend.failures = [gateway.GatewayError(429, "budget_exhausted", "budget exhausted: run")]
    _Backend.calls = 0
    unpatched = _Backend._create_embedding_with_cache
    graph = _upstream_graph()
    record = tmp_path / "memory-skips.jsonl"
    with (
        pytest.raises(ns["BudgetExhausted"], match="budget exhausted"),
        ns["tolerant_embeddings"](graph, record, _Backend),
    ):
        graph.add_node(SimpleNamespace(embedding=None))
    assert _Backend.calls == 1  # no upstream retry after a budget refusal
    assert not record.exists()
    assert _Backend._create_embedding_with_cache is unpatched  # nothing of ALPHA's stays


def test_input_refusal_behind_upstream_retries_is_skipped_with_its_cause(tmp_path: Path) -> None:
    ns = coder_parts()
    _Backend.failures = [
        gateway.GatewayError(400, "embedding_input_refused", "local embedding input refused")
    ]
    graph = _upstream_graph()
    record = tmp_path / "memory-skips.jsonl"
    with ns["tolerant_embeddings"](graph, record, _Backend):
        graph.add_node(SimpleNamespace(embedding=None))
    assert "local embedding input refused" in json.loads(record.read_text())["error"]
    _Backend.failures = [RuntimeError("connection reset")]
    with (
        pytest.raises(RuntimeError, match="after 3 retries"),
        ns["tolerant_embeddings"](graph, record, _Backend),
    ):
        graph.add_node(SimpleNamespace(embedding=None))


def test_only_input_refusals_skip_and_log_the_real_cause(tmp_path: Path) -> None:
    ns = coder_parts()
    refusal = gateway.GatewayError(
        400, "embedding_input_refused", "embedding input exceeds context"
    )
    outer = RuntimeError("Failed to get chat completion")
    outer.__cause__ = refusal
    graph = SimpleNamespace(add_node=Mock(side_effect=outer))
    record = tmp_path / "memory-skips.jsonl"
    with ns["tolerant_embeddings"](graph, record):
        graph.add_node(SimpleNamespace(embedding=None))
    assert "embedding input exceeds context" in json.loads(record.read_text())["error"]
    graph.add_node = Mock(side_effect=RuntimeError("unrelated failure"))
    with (
        pytest.raises(RuntimeError, match="unrelated"),
        ns["tolerant_embeddings"](graph, record),
    ):
        graph.add_node(SimpleNamespace(embedding=None))


# Abridged from the real 2026-11-17 proposal `ml_ridge_composite_28d` (run
# 2026-11-17-rdagent-spread-check, rounds.jsonl iteration 0): its own words and variables.
REAL_COMPOSITE: dict[str, Any] = {
    "name": "ml_ridge_composite_28d",
    "description": "[Machine Learning based Factor] Walk-forward cross-sectional ridge "
    "composite of slow OHLCV features, trained to predict the cross-sectional rank of the next "
    "28-day open-to-open return.",
    "formulation": "m20_{i,t}=ln(C_t/C_{t-20}), vol60_{i,t}=sqrt(...), hp120_{i,t}=C/max H-1, "
    "skew60_{i,t}=..., mdd120_{i,t}=..., ac60_{i,t}=...; f_{i,t}=x_{i,t}^T beta",
    "variables": {
        "ac60_{i,t}": "Lag-1 autocorrelation of the trailing 60 daily log returns.",
        "hp120_{i,t}": "120-day high proximity: close divided by trailing 120-day high minus one.",
        "m20_{i,t}": "20-day log momentum feature.",
        "mdd120_{i,t}": "Maximum peak-to-trough drawdown of close over the trailing 120 days.",
        "skew60_{i,t}": "Adjusted sample skewness of the trailing 60 daily log returns.",
        "vol60_{i,t}": "60-day realized volatility of daily log returns.",
        "vt60_{i,t}": "60-day volume trend: log ratio of 20-day to 60-day mean volume.",
    },
}


def _family(ns: dict[str, Any], row: dict[str, Any]) -> set[str]:
    args = (row["name"], row.get("description", ""), row.get("formulation", ""))
    return set(ns["idea_family"](*args, row.get("variables")).split("; "))


def test_ridge_composite_inherits_every_input_family() -> None:
    ns = swing_parts()
    families = _family(ns, REAL_COMPOSITE)
    assert {
        "volatility and beta",
        "drawdown",
        "skewness and lottery returns",
        "past return (momentum or reversal)",
    } <= families
    # Before the fix this composite was filed as "other: ml" and escaped every family.
    assert not any(family.startswith("other") for family in families)
    # Three failed volatility tries close that family; the composite is named in it, so the
    # proposer is told to leave composites that use it too.
    volatility = {"schema": "AlphaRdagentFactorTrialV2", "status": "SCREEN_FAIL", "screen": {}}
    rows = [{**volatility, "name": f"volatility_{n}d"} for n in (20, 40)]
    rows.append({**REAL_COMPOSITE, "schema": "AlphaRdagentFactorTrialV2", "status": "SCREEN_FAIL"})
    rows[-1]["screen"] = {}
    summary = ns["family_summary"](rows, 3)
    closed = summary.split("no candidate: ")[1]
    assert "volatility and beta" in closed and "composites using ANY" in summary
    assert "- drawdown: 1 try" in summary


def test_composite_family_cannot_be_dodged_by_renaming() -> None:
    ns = swing_parts()
    renamed = {**REAL_COMPOSITE, "name": "signal_alpha_x"}
    assert _family(ns, renamed) == _family(ns, REAL_COMPOSITE)
    plain: dict[str, Any] = {
        "name": "factor_a",
        "description": "Weighted sum of volatility and skewness ranks",
    }
    # Prose may say it is a mix but never supplies families: with no listed input names it
    # is its own "composite: unknown inputs" family, never silently an open "other: ...".
    assert _family(ns, plain) == {"composite: unknown inputs"}
    plain["variables"] = {"volatility": "rank", "skewness": "rank"}
    assert _family(ns, plain) == {"volatility and beta", "skewness and lottery returns"}
    unknown = {"name": "ml_ridge_composite_7d"}  # the real ledger rows carry no description
    assert _family(ns, unknown) == {"composite: unknown inputs"}


def test_single_family_factor_keeps_its_family() -> None:
    ns = swing_parts()
    cases = {
        "amihud_illiquidity_20d": "Mean absolute return per dollar volume over 20 days.",
        "vol_adjusted_momentum_28d": "28-day momentum divided by 60-day volatility.",
        "range_compression_10d": "High-low range over its 60-day mean; a strange arrangement.",
    }
    families = {
        name: _family(ns, {"name": name, "description": text}) for name, text in cases.items()
    }
    assert families == {
        "amihud_illiquidity_20d": {"illiquidity"},
        "vol_adjusted_momentum_28d": {"past return (momentum or reversal)"},
        "range_compression_10d": {"range and compression"},
    }


def test_resume_ignores_partial_checkpoint_and_records_abandonment(tmp_path: Path) -> None:
    old = tmp_path / "old/work/log/__session__"
    for folder, name in (("0", "4_record"), ("1", "1_coding")):
        (old / folder).mkdir(parents=True)
        (old / folder / name).write_bytes(b"checkpoint")
    current = tmp_path / "new"
    current.mkdir()
    plan = memory.prepare(
        tmp_path / "memory",
        run_id="new",
        run_dir=current,
        source_sha256="pin",
        judge_sha256="judge",
    )
    loaded = SimpleNamespace(trace=SimpleNamespace(hist=["completed-round"], scen="scene"))
    cls = Mock(return_value=SimpleNamespace(trace=SimpleNamespace(hist=[], scen="scene")))
    cls.load.return_value = loaded
    env = {
        **plan.env,
        "ALPHA_RDAGENT_CONTINUE_SESSION": str(old),
        "ALPHA_RDAGENT_CONTINUE_LOOPS": "1",
        "LOG_TRACE_PATH": str(current / "log"),
    }
    loop, total = memory.open_factor_loop(cls, SimpleNamespace(), 2, env)
    assert cls.load.call_args.args[0] == old / "0/4_record"
    assert loop.trace.hist == ["completed-round"]
    assert total == 2  # fresh scheduler, shared completed history
    abandoned = json.loads((tmp_path / "old/rounds.jsonl").read_text())
    assert abandoned["status"] == "abandoned_at_cap" and abandoned["loop"] == 1
    assert not (tmp_path / "old/evaluations.jsonl").exists()


def test_call_split_counts_only_reserved_timeout_retries() -> None:
    calls = [
        {
            "endpoint": "/v1/chat/completions",
            "attempts": 2,
            "status": 429,
            "provider_errors": ["provider_timeout", "provider_timeout"],
            "error_code": "budget_exhausted",
        },
        {"endpoint": "/v1/embeddings", "route": "ollama", "attempts": 2, "status": 200},
    ]
    split = launch.call_split(calls)
    assert split["timeout_retry_attempts"] == 1
    assert split["local_embedding"]["attempts"] == 2
    assert split["counted_toward_call_cap"] == 4


def test_reasoning_limit_unconfirmed_default_is_unset() -> None:
    args = launch.parser().parse_args(
        [
            "run",
            "--data-dir",
            "/data",
            "--run-dir",
            "/run",
            "--gateway-data-dir",
            "/gateway",
            "--trial-ledger",
            "/ledger",
            "--run-id",
            "id",
        ]
    )
    assert args.coding_reasoning_tokens is None
    assert gateway.Settings(data_dir=Path("/data"), run_id="id").coding_reasoning_tokens is None


def test_gateway_counts_timeout_retry_only_after_reservation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Three tries allowed, two calls left: the timeout retry that was reserved counts once."""
    monkeypatch.setenv("ALPHA_GATEWAY_API_KEY", "sk-test-not-real")
    monkeypatch.setenv("ALPHA_GATEWAY_API_BASE", "https://example.com/api/v1")

    def timed_out(*args: Any) -> dict[str, Any]:
        raise gateway.GatewayError(504, "provider_timeout", "provider read timed out")

    monkeypatch.setattr(gateway, "_post_json", timed_out)
    # The gateway refuses a data dir inside any git checkout, so this test uses /tmp directly.
    with tempfile.TemporaryDirectory(prefix="gateway-unit-", dir="/tmp") as directory:
        settings = gateway.Settings(
            data_dir=Path(directory),
            run_id="id",
            chat_route="api",
            embedding_route="fake",
            api_model="deepseek/test-model",
            api_price_in_per_mtok=1,
            api_price_out_per_mtok=2,
            api_openrouter=True,
            provider_retries=2,
            run_max_calls=2,
        )
        model = gateway.Gateway(settings)
        with pytest.raises(gateway.GatewayError, match="budget exhausted"):
            model.chat({"model": "alpha-chat", "messages": [{"role": "user", "content": "x"}]})
        row = json.loads(model.log_path.read_text().splitlines()[-1])
        assert row["attempts"] == 2 and row["timeout_retry_attempts"] == 1
        assert row["provider_errors"] == ["provider_timeout", "provider_timeout"]


def test_completed_rounds_add_to_inherited_count(tmp_path: Path) -> None:
    root = tmp_path / "memory"
    old = tmp_path / "old"
    old_session = old / "work/log/__session__/0"
    old_session.mkdir(parents=True)
    (old_session / "4_record").touch()
    plan = memory.prepare(
        root, run_id="old", run_dir=old, source_sha256="pin", judge_sha256="judge"
    )
    memory.record(plan, run_id="old", run_dir=old, started_at="start", ended_at="end", secrets=())
    new = tmp_path / "new"
    own = new / "work/log/__session__/0"
    own.mkdir(parents=True)
    (own / "4_record").touch()
    plan = memory.prepare(
        root, run_id="new", run_dir=new, source_sha256="pin", judge_sha256="judge"
    )
    result = memory.record(
        plan, run_id="new", run_dir=new, started_at="start", ended_at="end", secrets=()
    )
    assert result["loops_before"] == 1 and result["loops_after"] == 2
    # A half-finished round in this run's own session is recorded as abandoned, not counted.
    (new / "work/log/__session__/1").mkdir()
    (new / "work/log/__session__/1/0_direct_exp_gen").touch()
    newer = tmp_path / "newer"
    (newer / "work/log/__session__/0").mkdir(parents=True)
    (newer / "work/log/__session__/0/4_record").touch()
    plan = memory.prepare(
        root, run_id="newer", run_dir=newer, source_sha256="pin", judge_sha256="judge"
    )
    assert plan.loops_before == 2
    # The previous session could not be loaded: the run started a new lineage of its own.
    event = {
        "schema": "AlphaRdagentMemoryEventV1",
        "code": "session-unloadable",
        "message": "The previous session could not be loaded.",
        "ts": "now",
    }
    (newer / "memory-events.jsonl").write_text(json.dumps(event) + "\n")
    result = memory.record(
        plan, run_id="newer", run_dir=newer, started_at="start", ended_at="end", secrets=()
    )
    assert result["loops_after"] == 1
    for _ in range(2):  # recording an abandoned round twice writes it once
        memory.close_unfinished_rounds(new / "work/log/__session__")
    abandoned = [json.loads(line) for line in (new / "rounds.jsonl").read_text().splitlines()]
    assert [(row["schema"], row["loop"]) for row in abandoned] == [
        ("AlphaRdagentRoundAbandonedV1", 1)
    ]


@pytest.mark.parametrize(
    "feedback,expected",
    [
        (
            SimpleNamespace(
                execution_feedback="ValueError: bad input\ntrace", final_decision=False
            ),
            "exception",
        ),
        (
            SimpleNamespace(execution_feedback="call cap reached", final_decision=False),
            "cap_reached",
        ),
        (
            SimpleNamespace(
                execution_feedback='Traceback (most recent call last):\n  File "factor.py", '
                "line 3\nKeyError: 'close'",
                final_decision=False,
            ),
            "exception",
        ),
        (
            SimpleNamespace(
                execution_feedback="Code ran; the output looks wrong.", final_decision=False
            ),
            "critic_rejected",
        ),
    ],
)
def test_runner_keeps_execution_reason_before_critic(feedback: Any, expected: str) -> None:
    from tests.unit.test_rdagent_factor_judge import judge_parts

    class Feedback:
        execution_feedback = feedback.execution_feedback

        def __bool__(self) -> bool:
            return False

    cls = judge_parts("AlphaFactorRunner")["AlphaFactorRunner"]
    values, reason, detail = cls.execute_factor(Mock(), Feedback())
    assert values is None and reason == expected
    assert "\n" not in detail and not detail.startswith("Traceback")
    if "Traceback" in feedback.execution_feedback:
        assert detail == "KeyError: 'close'"


def test_runner_records_exception_and_bad_shape() -> None:
    import pandas as pd

    from tests.unit.test_rdagent_factor_judge import judge_parts

    cls = judge_parts("AlphaFactorRunner")["AlphaFactorRunner"]
    workspace = Mock()
    workspace.execute.side_effect = ValueError("broken first line\nsecond line")
    assert cls.execute_factor(workspace, True) == (
        None,
        "exception",
        "ValueError: broken first line",
    )
    workspace.execute.side_effect = None
    workspace.execute.return_value = ("ran", pd.DataFrame({"a": [1], "b": [2]}))
    assert cls.execute_factor(workspace, True)[1] == "bad_output"
    assert cls.execute_factor(workspace, False)[1] == "critic_rejected"


def test_invalid_embedding_model_is_not_an_input_refusal() -> None:
    # Only validation/error translation is exercised: no budget, storage, socket or backend.
    model = Mock()
    model.record.return_value = {"refused": []}
    model.check_model.side_effect = gateway.GatewayError(
        400, "model_not_served", "wrong model", "model"
    )
    with pytest.raises(gateway.GatewayError) as caught:
        gateway.Gateway.embeddings(model, {"model": "wrong"})
    assert caught.value.code == "model_not_served"
    model.budget.reserve.assert_not_called()


def test_bad_factor_format_is_recorded_before_prefix_check() -> None:
    import pandas as pd

    from tests.unit.test_rdagent_factor_judge import judge_parts

    frame = pd.DataFrame(
        {"factor": ["not numeric"]}, index=pd.MultiIndex.from_tuples([("bad date", "A")])
    )
    workspace = Mock()
    workspace.execute.return_value = ("ran", frame)
    runner = judge_parts("AlphaFactorRunner")["AlphaFactorRunner"]
    assert runner.execute_factor(workspace, True)[1] == "bad_output"
