"""Coder recovery, embedding memory and the recorded outcomes of partial rounds."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import Mock

import numpy as np
import pandas as pd
import pytest

from tests.unit._rdagent_support import _Backend, _upstream_graph, coder_parts, pinned_loop
from workers.rdagent import model_gateway as gateway
from workers.rdagent import research_memory as memory
from workers.rdagent.loop_guard import ProviderGuard, RoundRecord


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


def test_paid_memory_reembeds_in_one_batch_and_keeps_good_nodes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ALPHA_EMBEDDING_ROUTE", "provider")
    graph = SimpleNamespace(
        nodes={str(i): SimpleNamespace(content=str(i), embedding=[9.0]) for i in range(3)}
    )
    calls: list[list[str]] = []

    def embed_many(texts: list[str]) -> tuple[str, list[Any]]:
        calls.append(texts)
        return "model-a", [
            [1.0],
            memory.MemoryEmbeddingError("embedding_input_refused", "bad input"),
            [3.0],
        ]

    monkeypatch.setattr(memory, "gateway_embedding_batch", embed_many, raising=False)
    monkeypatch.setattr(
        memory, "gateway_embedding", Mock(side_effect=AssertionError("singleton transport used"))
    )
    cache = memory.EmbeddingMemory(
        tmp_path / "sidecar", tmp_path / "events", "model-a", memory.gateway_embedding
    )
    skipped: list[str] = []
    removed = cache.prepare(graph, lambda node, error: skipped.append(node.content))
    assert calls == [["0", "1", "2"]]
    assert skipped == ["1"] and set(removed) == {"1"}
    assert graph.nodes["0"].embedding == [1.0] and graph.nodes["2"].embedding == [3.0]
    cache.prepare(graph, lambda node, error: pytest.fail(str(error)))
    assert len(calls) == 1


def test_single_paid_memory_input_refusal_uses_skip_policy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ALPHA_EMBEDDING_ROUTE", "provider")
    error = memory.MemoryEmbeddingError("embedding_input_refused", "bad input")
    single = Mock(side_effect=error)
    batch = Mock(side_effect=AssertionError("one input needs the existing skip policy"))
    monkeypatch.setattr(memory, "gateway_embedding", single)
    monkeypatch.setattr(memory, "gateway_embedding_batch", batch)
    graph = SimpleNamespace(nodes={"bad": SimpleNamespace(content="bad", embedding=[9.0])})
    cache = memory.EmbeddingMemory(tmp_path / "sidecar", tmp_path / "events", "model-a", single)
    skipped: list[str] = []
    removed = cache.prepare(graph, lambda node, exc: skipped.append(str(exc)))
    assert skipped == ["bad input"] and set(removed) == {"bad"} and not graph.nodes
    batch.assert_not_called()


def test_failed_paid_memory_batch_goes_through_skip_policy_without_resending(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ALPHA_EMBEDDING_ROUTE", "provider")
    stop = memory.MemoryEmbeddingError("budget_exhausted", "budget exhausted: run_max_usd")
    batch = Mock(side_effect=stop)
    single = Mock(side_effect=AssertionError("a failed batch is not re-sent per input"))
    monkeypatch.setattr(memory, "gateway_embedding_batch", batch)
    monkeypatch.setattr(memory, "gateway_embedding", single)
    graph = SimpleNamespace(
        nodes={str(i): SimpleNamespace(content=str(i), embedding=None) for i in range(3)}
    )
    cache = memory.EmbeddingMemory(tmp_path / "sidecar", tmp_path / "events", "model-a", single)
    seen: list[BaseException] = []

    def skip(node: Any, error: Exception) -> None:
        seen.append(error)  # the coder's skip raises BudgetExhausted for this code
        raise SystemExit(str(error))

    with pytest.raises(SystemExit, match="budget exhausted"):
        cache.prepare(graph, skip)
    assert seen == [stop] and batch.call_count == 1


def mixed_graph() -> Any:
    nodes = {
        str(i): SimpleNamespace(
            id=str(i), label="error", content=str(i), embedding=[1.0] * (768 if i < 88 else 4096)
        )
        for i in range(107)
    }
    return SimpleNamespace(
        nodes=nodes,
        vector_base=SimpleNamespace(
            vector_df=pd.DataFrame(
                [
                    {"id": n.id, "label": n.label, "content": n.content, "embedding": n.embedding}
                    for n in nodes.values()
                ]
            )
        ),
    )


@pytest.mark.parametrize("refused", [False, True])
def test_prepare_rebuilds_mixed_search_table(tmp_path: Path, refused: bool) -> None:
    graph = mixed_graph()
    calls: list[str] = []

    def embed(text: str) -> tuple[str, list[float]]:
        calls.append(text)
        if refused and text == "0":
            raise ValueError("input refused")
        return "current", [1.0] * 4096

    cache = memory.EmbeddingMemory(tmp_path / "sidecar", tmp_path / "events", "current", embed)
    removed = cache.prepare(graph, lambda node, error: None)
    table = graph.vector_base.vector_df
    assert set(table.embedding.map(len)) == {4096}
    assert len(table) == 107 - int(refused)
    assert len(calls) == 107
    assert set(removed) == ({"0"} if refused else set())
    assert all(np.dot(v, [1.0] * 4096) == 4096 for v in table.embedding)
    stats = json.loads((tmp_path / "knowledge-vectors.json").read_text())
    assert stats == {
        "knowledge_vectors": 107 - int(refused),
        "knowledge_vectors_reembedded": 107 - int(refused),
        "knowledge_vectors_left_out": int(refused),
        "knowledge_vectors_left_out_nodes": [{"id": "0", "reason": "embedding refused"}]
        if refused
        else [],
        "knowledge_vector_dimension": 4096,
    }
    # A second prepare repairs a stale table from cached current-model nodes without new calls.
    graph.vector_base.vector_df = mixed_graph().vector_base.vector_df
    cache.prepare(graph, lambda node, error: pytest.fail(str(error)))
    assert set(graph.vector_base.vector_df.embedding.map(len)) == {4096}
    assert len(calls) == 107


def test_coding_failure_judges_completed_factors_then_stops_after_second_round(
    tmp_path: Path,
) -> None:
    loop = SimpleNamespace(loop_idx=0)
    judged: list[list[str]] = []

    def judge(exp: Any) -> Any:
        names = [t.factor_name for t in exp.sub_tasks]
        judged.append(names)
        exp.alpha_evaluation = {"factors": [{"name": name} for name in names]}
        return exp

    def broken(exp: Any) -> Any:
        raise ValueError("bad vectors\nsecond line")

    loop.runner = SimpleNamespace(develop=judge)
    guard = ProviderGuard(
        SimpleNamespace(develop=broken),
        loop,
        "coding",
        tmp_path,
        tmp_path / "calls",
        "run",
        RuntimeError,
        SimpleNamespace,
    )
    record = RoundRecord(lambda previous: None, tmp_path)
    for iteration in range(2):
        loop.loop_idx = iteration
        exp = SimpleNamespace(
            sub_tasks=[SimpleNamespace(factor_name=f"f{i}") for i in range(3)],
            sub_workspace_list=[object(), object(), None],
            prop_dev_feedback=[
                SimpleNamespace(value_generated_flag=True),
                SimpleNamespace(value_generated_flag=True),
                None,
            ],
        )
        recovered = guard.develop(exp)
        loop.runner.develop(recovered)
        if iteration == 0:
            record({"running": recovered})
        else:
            with pytest.raises(SystemExit, match="Two consecutive rounds.*internal coding"):
                record({"running": recovered})
    assert judged == [["f0", "f1"], ["f0", "f1"]]
    rows = [json.loads(line) for line in (tmp_path / "rounds.jsonl").read_text().splitlines()]
    assert len(rows) == 2
    for row in rows:
        assert row["status"] == "coding_failed_internal_error"
        assert row["exception_type"] == "ValueError" and row["message"] == "bad vectors second line"
        assert [f["trial_created"] for f in row["factors"]] == [True, True, False]
        assert row["factors"][2]["status"] == "not_coded"


@pytest.mark.parametrize("step", ["running", "feedback"])
def test_errors_outside_coding_propagate(tmp_path: Path, step: str) -> None:
    bug = ValueError("outside coding")
    component = SimpleNamespace(
        develop=Mock(side_effect=bug), generate_feedback=Mock(side_effect=bug)
    )
    guard = ProviderGuard(
        component,
        SimpleNamespace(loop_idx=0),
        step,
        tmp_path,
        tmp_path / "calls",
        "run",
        RuntimeError,
        SimpleNamespace,
    )
    with pytest.raises(ValueError, match="outside coding"):
        if step == "feedback":
            guard.generate_feedback(SimpleNamespace(), None)
        else:
            guard.develop(SimpleNamespace())
    assert not (tmp_path / "rounds.jsonl").exists()


@pytest.mark.parametrize("error", [SystemExit("budget"), KeyboardInterrupt()])
def test_coding_exit_signals_propagate(tmp_path: Path, error: BaseException) -> None:
    guard = ProviderGuard(
        SimpleNamespace(develop=Mock(side_effect=error)),
        SimpleNamespace(loop_idx=0),
        "coding",
        tmp_path,
        tmp_path / "calls",
        "run",
        RuntimeError,
        SimpleNamespace,
    )
    with pytest.raises(type(error)):
        guard.develop(SimpleNamespace(sub_tasks=[]))
    assert not (tmp_path / "rounds.jsonl").exists()


def test_real_graph_search_repairs_saved_mixed_vectors(tmp_path: Path) -> None:
    import os
    import subprocess

    source, python = os.environ.get("ALPHA_RDAGENT_SOURCE"), os.environ.get("ALPHA_FACTOR_PYTHON")
    if not source or not python:
        pytest.skip("requires read-only RD-Agent source and factor runtime")
    script = r"""
import json, sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
sys.path[:0] = [sys.argv[1], sys.argv[2]]
from rdagent.components.knowledge_management.graph import UndirectedGraph, UndirectedNode
from rdagent.components.knowledge_management.vector_base import KnowledgeMetaData
from rdagent.core.serialization import dump, load
from research_memory import EmbeddingMemory
from alpha_factor_coder import compatible_embeddings
root = Path(sys.argv[3])
graph = UndirectedGraph()
for i in range(107):
    graph.add_node(UndirectedNode(str(i), "error", [1.] * (768 if i < 88 else 4096)))
path = root / "knowledge.pkl"
with path.open("wb") as stream:
    dump(SimpleNamespace(graph=graph), stream)
with path.open("rb") as stream:
    knowledge = load(stream)
# Both the stale table and the independently serialised node vectors must be repaired.
cache = EmbeddingMemory(root / "sidecar", root / "events", "current",
                        lambda text: ("current", [1.] * 4096))
rag = SimpleNamespace(knowledgebase=knowledge, dump_knowledge_base_path=path)
with compatible_embeddings(rag, cache, root):
    with patch.object(KnowledgeMetaData, "create_embedding",
                      lambda node: setattr(node, "embedding", cache.vector(node.content))):
        found = knowledge.graph.semantic_search("query", constraint_labels=["error"], topk_k=5)
    assert len(found) == 5
    with path.open("wb") as stream:
        dump(knowledge, stream)
with path.open("rb") as stream:
    saved = load(stream)
assert set(saved.graph.vector_base.vector_df.embedding.map(len)) == {4096}
for row in saved.graph.vector_base.vector_df.itertuples():
    assert row.embedding == saved.graph.nodes[row.id].embedding
print(json.dumps({"vectors": len(saved.graph.vector_base.vector_df)}))
"""
    result = subprocess.run(
        [python, "-I", "-B", "-c", script, source, str(memory.WORKER), str(tmp_path)],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=120,
        check=True,
        env={
            "PATH": os.environ.get("PATH", ""),
            "ARTIFACT_SIGNING_KEY_PATH": str(tmp_path / "artifact-signing.key"),
            "LITELLM_LOCAL_MODEL_COST_MAP": "True",
            "LOG_TRACE_PATH": str(tmp_path / "log"),
        },
    )
    assert json.loads(result.stdout.strip().splitlines()[-1]) == {"vectors": 107}


def test_pinned_search_reads_rebuilt_table(tmp_path: Path) -> None:
    from scipy.spatial.distance import cosine

    from tests.unit._rdagent_support import upstream_class

    class Document:
        def __init__(self, content: str = "") -> None:
            self.content = content
            self.embedding: list[float] = []

        def create_embedding(self) -> None:
            self.embedding = [1.0] * 4096

        def from_dict(self, data: dict[str, Any]) -> Any:
            return SimpleNamespace(**data)

    cls = upstream_class(
        "components/knowledge_management/vector_base.py",
        "PDVectorBase",
        {"search"},
        {"Document": Document, "cosine": cosine},
    )
    graph = mixed_graph()
    table = cls()
    table.vector_df = graph.vector_base.vector_df
    graph.vector_base = table
    cache = memory.EmbeddingMemory(
        tmp_path / "sidecar", tmp_path / "events", "current", lambda text: ("current", [1.0] * 4096)
    )
    cache.prepare(graph, lambda node, error: pytest.fail(str(error)))
    docs, scores = table.search("query", topk_k=5, constraint_labels=["error"])
    assert len(docs) == len(scores) == 5
    assert all(score == pytest.approx(1.0) for score in scores)


def test_pinned_loop_recovers_partial_evaluator_then_stops(tmp_path: Path) -> None:
    import asyncio
    import re
    from collections.abc import Callable
    from contextlib import nullcontext
    from datetime import datetime, timezone
    from typing import cast

    from tests.unit._rdagent_support import upstream_class
    from workers.rdagent.loop_guard import CriticEvaluator, RoundFeedback

    ns: dict[str, Any] = {
        "asyncio": asyncio,
        "cast": cast,
        "Callable": Callable,
        "Any": Any,
        "datetime": datetime,
        "timezone": timezone,
        "re": re,
        "FactorSingleFeedback": SimpleNamespace,
        "logger": SimpleNamespace(
            info=Mock(), warning=Mock(), log_object=Mock(), tag=lambda _: nullcontext()
        ),
        "LoopTrace": Mock(),
        "HypothesisFeedback": SimpleNamespace,
        "RD_AGENT_SETTINGS": SimpleNamespace(get_max_parallel=lambda: 1),
    }
    loop = pinned_loop(tmp_path, ns, RuntimeError)
    single = upstream_class(
        "components/coder/factor_coder/evaluators.py", "FactorEvaluatorForCoder", {"evaluate"}, ns
    )()
    proposed: list[int] = []
    judged: list[list[str]] = []

    def propose() -> str:
        proposed.append(loop.loop_idx)
        return "hypothesis"

    def experiment(hypothesis: str) -> Any:
        return SimpleNamespace(
            based_experiments=[],
            sub_workspace_list=[],
            sub_tasks=[
                SimpleNamespace(
                    factor_name=name, version=1, get_task_information=lambda name=name: name
                )
                for name in ("one", "two", "three")
            ],
        )

    def code(exp: Any) -> Any:
        exp.alpha_completed_coding = {}
        single.code_evaluator = SimpleNamespace(evaluate=lambda **kwargs: ("fine", None))
        single.value_evaluator = SimpleNamespace(evaluate=lambda **kwargs: ("value checked", True))
        single.final_decision_evaluator = SimpleNamespace(evaluate=Mock())
        wrapped = CriticEvaluator(single, loop.coder, exp)
        for task in exp.sub_tasks:
            if task.factor_name == "three":
                raise ValueError("mixed dimensions")
            wrapped.evaluate(task, SimpleNamespace(execute=lambda: ("ran", [1])))
        raise AssertionError("third factor must fail")

    def judge(exp: Any) -> Any:
        names = [t.factor_name for t in exp.sub_tasks]
        judged.append(names)
        assert len(exp.sub_workspace_list) == len(exp.prop_dev_feedback) == 2
        exp.alpha_evaluation = {"factors": [{"name": name} for name in names]}
        return exp

    loop._propose, loop._exp_gen, loop._interact_feedback = propose, experiment, lambda value: value
    loop.coder = ProviderGuard(
        SimpleNamespace(develop=code),
        loop,
        "coding",
        tmp_path,
        tmp_path / "calls",
        "test",
        RuntimeError,
        SimpleNamespace,
    )
    loop.runner = SimpleNamespace(develop=judge)
    loop.summarizer = SimpleNamespace(
        generate_feedback=lambda exp, trace: SimpleNamespace(reason="judged")
    )
    loop.feedback = RoundFeedback(loop.feedback)

    async def run() -> None:
        for iteration in range(2):
            loop.loop_idx = iteration
            while loop.step_idx[iteration] < len(loop.steps):
                await loop._run_step(iteration)

    with pytest.raises(SystemExit, match="Two consecutive rounds"):
        asyncio.run(run())
    assert proposed == [0, 1] and judged == [["one", "two"], ["one", "two"]]
    rows = [json.loads(line) for line in (tmp_path / "rounds.jsonl").read_text().splitlines()]
    assert len(rows) == 2
    assert all([f["trial_created"] for f in r["factors"]] == [True, True, False] for r in rows)


def test_executed_values_survive_error_before_critic_feedback(tmp_path: Path) -> None:
    import re

    from tests.unit._rdagent_support import upstream_class
    from workers.rdagent.loop_guard import CriticEvaluator

    cls = upstream_class(
        "components/coder/factor_coder/evaluators.py",
        "FactorEvaluatorForCoder",
        {"evaluate"},
        {"re": re, "FactorSingleFeedback": SimpleNamespace},
    )
    evaluator = cls()
    evaluator.code_evaluator = SimpleNamespace(evaluate=Mock(side_effect=ValueError("critic bug")))
    evaluator.value_evaluator = SimpleNamespace(evaluate=lambda **kwargs: ("checked", None))
    evaluator.final_decision_evaluator = SimpleNamespace(evaluate=Mock())
    exp = SimpleNamespace(alpha_completed_coding={})
    guard = ProviderGuard(
        None,
        SimpleNamespace(loop_idx=0),
        "coding",
        tmp_path,
        tmp_path / "calls",
        "test",
        RuntimeError,
        SimpleNamespace,
    )
    workspace = SimpleNamespace(execute=Mock(return_value=("values produced", [1])))
    task = SimpleNamespace(factor_name="one", version=1, get_task_information=lambda: "one")
    wrapped = CriticEvaluator(evaluator, guard, exp)
    with pytest.raises(ValueError, match="critic bug"):
        wrapped.evaluate(task, workspace)
    saved, feedback = exp.alpha_completed_coding["one"]
    assert saved is not workspace and bool(feedback)
    assert feedback.execution_feedback == "values produced"
    assert feedback.value_generated_flag is True
    workspace.execute.assert_called_once()


def test_saving_after_early_coding_failure_repairs_original_pickle(tmp_path: Path) -> None:
    import ast
    import os
    import pickle
    import tempfile

    from filelock import FileLock

    graph = mixed_graph()
    path = tmp_path / "knowledge.pkl"
    path.write_bytes(pickle.dumps(SimpleNamespace(graph=graph)))

    def embed(text: str) -> tuple[str, list[float]]:
        if text == "0":
            raise ValueError("refused")
        return "current", [1.0] * 4096

    cache = memory.EmbeddingMemory(tmp_path / "sidecar", tmp_path / "events", "current", embed)
    removed = cache.prepare(graph, lambda node, error: None)
    source = memory.WORKER / "alpha_factor_coder.py"
    nodes: list[ast.stmt] = [
        node
        for node in ast.parse(source.read_text()).body
        if isinstance(node, ast.FunctionDef) and node.name == "restore_skipped_nodes"
    ]
    ns: dict[str, Any] = {
        "Path": Path,
        "Any": Any,
        "EmbeddingMemory": memory.EmbeddingMemory,
        "FileLock": FileLock,
        "load": pickle.load,
        "dump": pickle.dump,
        "tempfile": tempfile,
        "os": os,
    }
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(source), "exec"), ns)
    ns["restore_skipped_nodes"](path, removed, cache)
    saved = pickle.loads(path.read_bytes()).graph
    assert len(saved.nodes) == 107 and saved.nodes["0"].embedding is None
    assert len(saved.vector_base.vector_df) == 106
    for row in saved.vector_base.vector_df.itertuples():
        assert len(row.embedding) == 4096 and row.embedding == saved.nodes[row.id].embedding


def test_workstation_projects_internal_coding_failure(tmp_path: Path) -> None:
    from alpha_web import _rdagent_runs as reader

    run = tmp_path / "run"
    run.mkdir()
    (run / "receipt.json").write_text(
        json.dumps(
            {
                "schema": "AlphaRdagentFactorRunReceiptV1",
                "run_id": "run",
            }
        )
    )
    (run / "rounds.jsonl").write_text(
        json.dumps(
            {
                "status": "coding_failed_internal_error",
                "trial_created": True,
            }
        )
        + "\n"
    )
    detail = reader.read_run(tmp_path, tmp_path / "absent-ledger", "run")
    assert len(detail.refusals) == 1
    assert "internal coding error" in str(detail.refusals[0]["sentence"].value).lower()


class StandInCoderError(Exception):
    """Upstream's own round-ending coder error (RD-Agent's CoderError in the real loop)."""


def test_upstream_round_ending_errors_keep_their_skip_path(tmp_path: Path) -> None:
    # "All tasks failed" is upstream's normal end of a coding round: it must reach the loop's
    # own skip handling unchanged, never be judged as a partial round or count toward the stop.
    loop = SimpleNamespace(loop_idx=0, skip_loop_error=(StandInCoderError,))

    def develop(exp: Any) -> Any:
        exp.alpha_completed_coding = {"f0": (object(), SimpleNamespace(value_generated_flag=True))}
        raise StandInCoderError("All tasks are failed")

    guard = ProviderGuard(
        SimpleNamespace(develop=develop),
        loop,
        "coding",
        tmp_path,
        tmp_path / "calls",
        "run",
        RuntimeError,
        SimpleNamespace,
    )
    exp = SimpleNamespace(sub_tasks=[SimpleNamespace(factor_name="f0")])
    with pytest.raises(StandInCoderError):
        guard.develop(exp)
    assert not hasattr(exp, "alpha_internal_coding")
    assert not (tmp_path / "rounds.jsonl").exists()


def test_alpha_code_error_inside_a_library_call_propagates(tmp_path: Path) -> None:
    # The deepest frame is the json library, but the defect is in ALPHA's own worker code.
    (tmp_path / "sidecar").write_text("{not json")

    def develop(exp: Any) -> Any:
        memory.EmbeddingMemory(tmp_path / "sidecar", tmp_path / "events", "m", Mock())
        return exp

    guard = ProviderGuard(
        SimpleNamespace(develop=develop),
        SimpleNamespace(loop_idx=0),
        "coding",
        tmp_path,
        tmp_path / "calls",
        "run",
        RuntimeError,
        SimpleNamespace,
    )
    exp = SimpleNamespace(
        sub_tasks=[SimpleNamespace(factor_name="f0")],
        alpha_completed_coding={"f0": (object(), SimpleNamespace(value_generated_flag=True))},
    )
    with pytest.raises(json.JSONDecodeError):
        guard.develop(exp)
    assert not (tmp_path / "rounds.jsonl").exists()


def test_upstream_search_failing_inside_numpy_is_recovered(tmp_path: Path) -> None:
    import importlib.util

    # Shaped like run 5: RD-Agent's vector search calls numpy, which raises the ValueError.
    source = tmp_path / "rdagent" / "vector_base.py"
    source.parent.mkdir()
    source.write_text(
        "import numpy\n\ndef search():\n    return numpy.dot([1.0] * 768, [1.0] * 4096)\n"
    )
    spec = importlib.util.spec_from_file_location("stand_in_vector_base", source)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    def develop(exp: Any) -> Any:
        module.search()
        return exp

    guard = ProviderGuard(
        SimpleNamespace(develop=develop),
        SimpleNamespace(loop_idx=0),
        "coding",
        tmp_path,
        tmp_path / "calls",
        "run",
        RuntimeError,
        SimpleNamespace,
    )
    exp = SimpleNamespace(
        sub_tasks=[SimpleNamespace(factor_name="f0"), SimpleNamespace(factor_name="f1")],
        alpha_completed_coding={"f0": (object(), SimpleNamespace(value_generated_flag=True))},
    )
    recovered = guard.develop(exp)
    assert [t.factor_name for t in recovered.sub_tasks] == ["f0"]
    assert exp.alpha_internal_coding["exception_type"] == "ValueError"


def test_rebuild_receipt_explains_each_vectorless_node(tmp_path: Path) -> None:
    def embed(text: str) -> tuple[str, list[float]]:
        raise memory.MemoryEmbeddingError("embedding_input_refused", "input too long")

    graph = SimpleNamespace(
        nodes={
            "long": SimpleNamespace(content="long", embedding=None),
            "blank": SimpleNamespace(content="  ", embedding=None),
        }
    )
    cache = memory.EmbeddingMemory(tmp_path / "sidecar", tmp_path / "events", "current", embed)
    removed = cache.prepare(graph, lambda node, error: None)
    graph.nodes.update(removed)
    graph.nodes["new"] = SimpleNamespace(content="new", embedding=None)
    cache.rebuild(graph)
    receipt = json.loads((tmp_path / "knowledge-vectors.json").read_text())
    assert receipt["knowledge_vectors_left_out"] == 3
    assert receipt["knowledge_vectors_left_out_nodes"] == [
        {"id": "blank", "reason": "empty text"},
        {"id": "long", "reason": "over length"},
        {"id": "new", "reason": "no current vector"},
    ]
