"""RD-Agent's own factor coder, with one upstream counter restarted per experiment.

Selected through RD-Agent's setting ``QLIB_FACTOR_CODER``; RD-Agent's files stay unmodified.

Upstream defect (pinned 484776c, ``rdagent/components/coder/CoSTEER/knowledge_management.py``,
``CoSTEERRAGStrategyV2``): ``current_generated_trace_count`` remembers how many evolve steps were
already turned into knowledge, but every ``CoSTEER.develop`` call starts a new, empty evolving
trace while the counter keeps the previous experiment's length. ``generate_knowledge`` then skips
the first steps of every later experiment, so in one run usually only the first experiment's
coding attempts reach the persistent knowledge base (seen 2026-11-15: two rounds, seven factors
coded, four recorded). Restarting the counter before each experiment records every attempt.
Proposed upstream patch: reset the counter in ``CoSTEER.develop`` (or key it by trace identity).

A second upstream behaviour (same pin, ``knowledge_management/graph.py``,
``UndirectedGraph.add_node``): a node's embedding is created while it is added to the
coding-memory graph, and a refused embedding ends the whole coding step and so the run
(2026-11-16: run 2 ended after local Ollama refused one input three times). While RD-Agent turns
an evolve step into knowledge, ALPHA's strategy leaves out a node whose embedding input the
service refused; each skip is written, with that true cause, to the run's ``memory-skips.jsonl``
and counted on the receipt. A budget refusal is never a skip: it stops the worker at once as
``BudgetExhausted`` (2026-11-17: cap refusals were logged as skips and the run died a step
later). Proposed upstream
patch: catch the embedding failure in ``add_node`` and leave the node out with a warning.
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager, nullcontext
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any

from filelock import FileLock
from rdagent.components.coder.CoSTEER.knowledge_management import CoSTEERRAGStrategyV2
from rdagent.components.coder.factor_coder import FactorCoSTEER
from rdagent.core.serialization import dump, load

if TYPE_CHECKING:
    from .loop_guard import CriticEvaluator, ProviderGuard
    from .research_memory import EmbeddingMemory, gateway_embedding
else:
    from loop_guard import CriticEvaluator, ProviderGuard
    from research_memory import EmbeddingMemory, gateway_embedding


def _code_sha256(unit: Any) -> str | None:
    code = (getattr(unit.implementation, "file_dict", None) or {}).get("factor.py")
    return hashlib.sha256(code.encode()).hexdigest() if isinstance(code, str) else None


def demote(
    knowledge: Any,
    task_informations: Sequence[str],
    code_sha256s: Sequence[str | None] | None = None,
) -> list[str]:
    """Retain rejected code and its history, removing both successful retrieval paths.

    With ``code_sha256s`` (aligned with ``task_informations``) only the implementation with that
    exact code is demoted, so an earlier accepted implementation of the same task stays offered.
    """
    digests = list(code_sha256s) if code_sha256s is not None else [None] * len(task_informations)
    demoted = []
    for information, digest in dict.fromkeys(zip(task_informations, digests, strict=True)):
        changed = False
        current = knowledge.success_task_to_knowledge_dict.get(information)
        if current is not None and (digest is None or _code_sha256(current) == digest):
            knowledge.success_task_to_knowledge_dict.pop(information)
            changed = True
        for node_id, unit in knowledge.node_to_implementation_knowledge_dict.items():
            if unit.target_task.get_task_information() != information:
                continue
            if digest is not None and _code_sha256(unit) != digest:
                continue
            node = knowledge.graph.nodes.get(node_id)  # absent when its embedding was skipped
            if node is not None and node.label == "task_success_implement":
                node.label = "alpha_rejected_implement"
                changed = True
        if changed:
            demoted.append(information)
    return demoted


def demote_in_file(
    environ: Mapping[str, str],
    task_informations: Sequence[str],
    code_sha256s: Sequence[str | None] | None = None,
) -> tuple[list[str], str | None]:
    """A memory failure is advisory; report it without stopping the research run."""
    try:
        name = environ.get("FACTOR_CoSTEER_new_knowledge_base_path")
        if not name or not Path(name).exists():
            return [], "no persistent coding memory"
        path = Path(name)
        lock = (
            FileLock(environ["FACTOR_CoSTEER_filelock_path"])
            if environ.get("FACTOR_CoSTEER_enable_filelock", "False").lower() == "true"
            else nullcontext()
        )
        with lock:
            with path.open("rb") as stream:
                knowledge = load(stream)
            demoted = demote(knowledge, task_informations, code_sha256s)
            descriptor, temporary = tempfile.mkstemp(prefix=".coder-verdict-", dir=path.parent)
            try:
                with os.fdopen(descriptor, "wb") as stream:
                    dump(knowledge, stream)
                    stream.flush()
                    os.fsync(stream.fileno())
                os.replace(temporary, path)
            finally:
                Path(temporary).unlink(missing_ok=True)
        return demoted, None
    except Exception as error:  # Memory demotion must never abort the runner.
        return [], f"{type(error).__name__}: {error}"


def _record_skip(record: Path | None, node: Any, error: BaseException) -> None:
    if record is None:
        return
    content = str(getattr(node, "content", ""))
    line = {
        "schema": "AlphaMemorySkipV1",
        "ts": datetime.now(UTC).isoformat(),
        "label": getattr(node, "label", None),
        "content_sha256": hashlib.sha256(content.encode()).hexdigest(),
        "content_chars": len(content),
        "error": f"{type(error).__name__}: {error}"[:300],
    }
    with record.open("a") as stream:
        stream.write(json.dumps(line, sort_keys=True) + "\n")


class BudgetExhausted(SystemExit):
    """Stop the worker cleanly; upstream's model retries must not catch this refusal."""


def embedding_failure(error: BaseException) -> BaseException | None:
    """Find the transport cause without mistaking a missing vector for an input refusal."""
    seen: set[int] = set()
    refusal = None
    cause: BaseException | None = error
    while cause is not None and id(cause) not in seen:
        seen.add(id(cause))
        text = str(cause).lower()
        if getattr(cause, "code", None) == "budget_exhausted" or any(
            token in text for token in ("budget exhausted", "call cap reached", "budget_exhausted")
        ):
            raise BudgetExhausted(str(cause)) from cause
        if (
            getattr(cause, "code", None) == "embedding_input_refused"
            or "embedding_input_refused" in text
        ):
            refusal = cause
        cause = cause.__cause__ or cause.__context__
    return refusal


@contextmanager
def tolerant_embeddings(graph: Any, record: Path | None, backend: Any = None) -> Iterator[None]:
    """Within the block, a graph node whose embedding input was refused is left out and recorded.

    Upstream's retry wrapper (``_try_create_chat_completion_or_embedding``) retries every failure
    and then raises a fresh ``RuntimeError`` with no cause, so the real error is lost. With
    ``backend`` (RD-Agent's ``APIBackend`` class) each embedding request's own failure is seen
    first: a budget refusal stops the worker at once as ``BudgetExhausted``, before upstream's
    retries, and an input refusal is kept as the true cause of the skip. Only a failure that
    leaves the node (or its neighbour) without an embedding and whose cause is an input refusal
    is skipped; any other error is raised. Both wrappers are removed on exit, so nothing of
    ALPHA's is pickled with the knowledge base.
    """
    original = graph.add_node
    causes: list[BaseException] = []
    embed: Any = getattr(backend, "_create_embedding_with_cache", None) if backend else None

    def create_embedding(self: Any, *args: Any, **kwargs: Any) -> Any:
        try:
            return embed(self, *args, **kwargs)
        except Exception as error:
            embedding_failure(error)  # a budget refusal leaves here as BudgetExhausted
            causes.append(error)
            raise

    def add_node(node: Any, neighbor: Any = None, *args: Any, **kwargs: Any) -> Any:
        causes.clear()
        try:
            return original(node, neighbor, *args, **kwargs)
        except Exception as error:
            refusal = embedding_failure(error)
            for cause in reversed(causes):
                refusal = refusal or embedding_failure(cause)
            missing = [
                item
                for item in (node, neighbor)
                if item is not None and getattr(item, "embedding", None) is None
            ]
            if not missing or refusal is None:
                raise
            _record_skip(record, missing[0], refusal)
            return None

    graph.add_node = add_node
    if embed is not None:
        backend._create_embedding_with_cache = create_embedding
    try:
        yield
    finally:
        del graph.add_node
        if embed is not None:
            backend._create_embedding_with_cache = embed


class AlphaRAGStrategyV2(CoSTEERRAGStrategyV2):
    def generate_knowledge(self, evolving_trace: Any, *, return_knowledge: bool = False) -> Any:
        from rdagent.oai.backend.base import APIBackend

        run = os.environ.get("ALPHA_FACTOR_RUN_DIR")
        record = Path(run) / "memory-skips.jsonl" if run else None
        with tolerant_embeddings(self.knowledgebase.graph, record, APIBackend):
            return super().generate_knowledge(evolving_trace, return_knowledge=return_knowledge)


class AlphaFactorCoSTEER(FactorCoSTEER):
    def develop(self, exp: Any) -> Any:
        if type(self.rag) is CoSTEERRAGStrategyV2:
            self.rag.__class__ = AlphaRAGStrategyV2  # only the knowledge step changes (above)
        if self.rag.dump_knowledge_base_path is not None:
            lock = (
                FileLock(self.settings.filelock_path)
                if self.settings.enable_filelock
                else nullcontext()
            )
            with lock:
                self.rag.load_dumped_knowledge_base()
        self.rag.current_generated_trace_count = 0
        run = os.environ.get("ALPHA_FACTOR_RUN_DIR")
        if not run:
            return super().develop(exp)
        if not hasattr(self, "_alpha_embedding_memory"):
            root = Path(os.environ.get("ALPHA_RDAGENT_MEMORY_DIR", run))
            self._alpha_embedding_memory = EmbeddingMemory(
                root / "embedding-models.json",
                Path(run) / "memory-reembedded.jsonl",
                os.environ.get("ALPHA_EMBEDDING_MODEL", "nomic-embed-text"),
                gateway_embedding,
            )
        with (
            compatible_embeddings(self.rag, self._alpha_embedding_memory, Path(run)),
            tolerant_critic(self.evaluator, Path(run), exp),
        ):
            return super().develop(exp)


class FactorCritic(CriticEvaluator):
    """Attach the outcome of this attempt to the feedback used to judge this implementation."""

    def evaluate(self, target_task: Any, implementation: Any, *args: Any, **kwargs: Any) -> Any:
        skipped, unavailable = len(self.skipped), len(self.unavailable)
        result = super().evaluate(target_task, implementation, *args, **kwargs)
        status = None
        if len(self.skipped) > skipped:
            status = "skipped"
        elif len(self.unavailable) > unavailable:
            status = "unavailable"
        if status:
            result.alpha_critic_status = status
            if self.exp is not None and getattr(result, "value_generated_flag", False):
                self.exp.alpha_completed_coding[target_task.factor_name][
                    1
                ].alpha_critic_status = status
        return result


@contextmanager
def tolerant_critic(evaluator: Any, run: Path, exp: Any = None) -> Iterator[None]:
    """Wrap the pinned CoSTEER single evaluator for this round, leaving its code path intact."""
    calls = os.environ.get("ALPHA_GATEWAY_CALLS")
    if not calls:
        yield
        return
    original = evaluator.single_evaluator
    guard = ProviderGuard(
        None,
        SimpleNamespace(loop_idx=0),
        "coding",
        run,
        Path(calls),
        os.environ["ALPHA_GATEWAY_RUN_ID"],
        RuntimeError,
        None,
    )
    if exp is not None:
        exp.alpha_completed_coding = {}
    wrapped = FactorCritic(original, guard, exp)
    evaluator.single_evaluator = wrapped
    try:
        yield
    finally:
        evaluator.single_evaluator = original
        wrapped.record()


@contextmanager
def compatible_embeddings(rag: Any, memory: EmbeddingMemory, run: Path) -> Iterator[None]:
    """Keep upstream vectors in one model space, including queries and cached new nodes."""
    from rdagent.oai.backend.base import APIBackend

    graph = rag.knowledgebase.graph
    original = APIBackend._create_embedding_with_cache

    def skip(node: Any, error: Exception) -> None:
        embedding_failure(error)
        _record_skip(run / "memory-skips.jsonl", node, error)

    def embed(
        self: Any, input_content_list: list[str], *args: Any, **kwargs: Any
    ) -> list[list[float]]:
        try:
            return [memory.vector(text) for text in input_content_list]
        except Exception as error:
            embedding_failure(error)
            raise

    removed = memory.prepare(graph, skip)
    APIBackend._create_embedding_with_cache = embed
    try:
        yield
    finally:
        APIBackend._create_embedding_with_cache = original
        for node_id, node in graph.nodes.items():
            if node.embedding is not None:
                memory.remember(node_id, node)
        memory.save()
        graph.nodes.update(removed)
        memory.rebuild(graph)
        if rag.dump_knowledge_base_path is not None:
            restore_skipped_nodes(Path(rag.dump_knowledge_base_path), removed, memory)


def restore_skipped_nodes(path: Path, removed: dict[str, Any], memory: EmbeddingMemory) -> None:
    """Upstream dumps while failed nodes are hidden. Retain their text for the next run."""
    with FileLock(str(path.with_suffix(".lock"))):
        if not path.exists():
            return
        with path.open("rb") as stream:
            knowledge = load(stream)
        for node_id, node in removed.items():
            knowledge.graph.nodes.setdefault(node_id, node)
        memory.restore_vectors(knowledge.graph)
        descriptor, temporary = tempfile.mkstemp(prefix=".coder-embeddings-", dir=path.parent)
        try:
            with os.fdopen(descriptor, "wb") as stream:
                dump(knowledge, stream)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, path)
        finally:
            Path(temporary).unlink(missing_ok=True)
