"""RD-Agent's own persistent knowledge and sessions; ALPHA's ledger remains authoritative."""

from __future__ import annotations

import argparse
import hashlib
import importlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from contextlib import redirect_stdout
from copy import copy
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from . import research_memory_store as store
else:
    # Run as a script under ``python -I`` (the memory view), the worker folder is not on sys.path.
    if not __package__:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
    store = importlib.import_module(
        f"{__package__}.research_memory_store" if __package__ else "research_memory_store"
    )

KNOWLEDGE = store.KNOWLEDGE
_fields = store._fields
_fresh = store._fresh
_hash = store._hash
_json = store._json
_load_knowledge = store._load_knowledge
_lock = store._lock
_quarantine = store._quarantine
_read = store._read
_warning = store._warning
_write = store._write
completed_loops = store.completed_loops

WORKER = Path(__file__).resolve().parent
RESTORED_ROUNDS_FULL = 4
HISTORY_CHAR_BUDGET = 84_000


def _families() -> Any:
    return importlib.import_module(
        f"{__package__}.idea_families" if __package__ else "idea_families"
    )


def _closed_for_prompt() -> set[str]:
    if not os.environ.get("ALPHA_FACTOR_TRIAL_LEDGER"):
        return set()
    return set(importlib.import_module("alpha_factor_judge").closed_families())


class ProposalHistory:
    """Project restored history into prompt text, retaining the authoritative trace untouched."""

    def __init__(
        self,
        original: Any,
        restored: int,
        panel_sha256: str,
        *,
        receipt: Path | None = None,
        component: str = "hypothesis",
        closed_families: Callable[[], set[str]] = _closed_for_prompt,
    ) -> None:
        self.receipt, self.component, self.closed_families = receipt, component, closed_families
        self.original, self.restored, self.panel_sha256 = original, restored, panel_sha256

    def _panel(self, exp: Any) -> str | None:
        evaluation = getattr(exp, "alpha_evaluation", None) or {}
        panel = (evaluation.get("inputs") or {}).get("panel_sha256")
        if panel:
            return str(panel)
        run = getattr(exp, "alpha_run_dir", None)
        workspace = getattr(getattr(exp, "experiment_workspace", None), "workspace_path", None)
        if not run and workspace:
            path = Path(workspace)
            # Pinned QlibFactorExperiment allocates this workspace before any coding or judge.
            # Its absolute path survives inherited checkpoints and identifies the original run.
            if path.is_absolute() and path.parts[-4:-1] == (
                "work",
                "git_ignore_folder",
                "RD-Agent_workspace",
            ):
                run = str(path.parents[3])
        if run:
            for name in ("receipt.json", "panel/panel-receipt.json"):
                path = Path(run) / name
                if path.exists() and (panel := json.loads(path.read_text()).get("panel_sha256")):
                    return str(panel)
        return getattr(exp, "alpha_panel_sha256", None)

    def _full(self, trace: Any) -> set[int]:
        same = [
            i
            for i, (exp, _) in enumerate(trace.hist[: self.restored])
            if self._panel(exp) == self.panel_sha256
        ]
        return set(same[-RESTORED_ROUNDS_FULL:])

    def counts(self, trace: Any) -> dict[str, int]:
        full = len(self._full(trace))
        return {"history_rounds_full": full, "history_rounds_summarised": self.restored - full}

    def _summary(self, exp: Any, feedback: Any) -> str:
        families = _families()
        tasks = {task.factor_name: task for task in getattr(exp, "sub_tasks", [])}
        rows = {
            f["name"]: f for f in (getattr(exp, "alpha_evaluation", None) or {}).get("factors", [])
        }
        refusal = getattr(exp, "alpha_family_refusal", None) or {}
        reason = str(getattr(feedback, "reason", "")).partition(":")[0]
        fallback = refusal.get(
            "status",
            reason
            if reason.startswith(("coding_failed_provider_", "proposal_failed_provider_"))
            else "status not recorded",
        )
        panel = self._panel(exp)
        suffix = "; different coin panel" if panel and panel != self.panel_sha256 else ""
        if panel is None:
            suffix = "; coin panel not recorded (panel unknown)"
        lines = []
        for name in dict.fromkeys([*tasks, *rows]) or ["no factors recorded"]:
            task, row = tasks.get(name), rows.get(name, {})
            family = row.get("family") or (
                families.idea_family(
                    name,
                    getattr(task, "description", "") or "",
                    getattr(task, "factor_formulation", "") or "",
                    getattr(task, "variables", None),
                )
                if task or row
                else "family not recorded"
            )
            status = families.recorded_status(row) if row else fallback
            # The evaluator's stored reason names the stage the factor stopped at.
            stage = row.get("reason") or row.get("failure_reason") or "stage not recorded"
            lines.append(
                " ".join(f"Restored round: {name}; {family}; {status}{suffix}; {stage}".split())
            )
        return "\n".join(lines)

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        trace = kwargs["trace"] if "trace" in kwargs else args[-1]
        families = _families()
        source = families.universe_source(os.environ.get("ALPHA_FACTOR_RUN_DIR"))
        hidden, closed = families.hidden_families(source), self.closed_families()
        view = copy(trace)
        pairs = []
        for exp, feedback in trace.hist:
            suggestion = getattr(feedback, "new_hypothesis", None)
            if suggestion and (note := families.suggestion_reason(suggestion, closed, hidden)):
                feedback = copy(feedback)
                feedback.new_hypothesis = note
                if families.suggestion_reason(str(getattr(feedback, "reason", "")), closed, hidden):
                    feedback.reason = ""
            pairs.append((exp, feedback))

        def render(indices: set[int]) -> Any:
            view.hist = [pair for i, pair in enumerate(pairs) if i in indices]
            if "trace" in kwargs:
                return self.original(*args, **{**kwargs, "trace": view})
            return self.original(*args[:-1], view, **kwargs)

        all_indices = set(range(len(pairs)))
        context, flag = render(all_indices)
        full = self._full(trace) | set(range(self.restored, len(pairs)))
        summaries: dict[int, str] = {}
        omitted = 0  # oldest one-line ideas left out once every round is already one line each
        while True:
            compact = context if full == all_indices else render(full)[0]
            for i in sorted(all_indices - full - summaries.keys()):
                summaries[i] = families.filter_history(self._summary(*pairs[i]), hidden, closed)
            lines = [line for i in sorted(summaries) for line in summaries[i].split("\n")]
            note = [f"{omitted} older ideas omitted from this summary (kept on disk)"]
            history = "\n".join(
                [*(note if omitted else []), *lines[omitted:], compact["hypothesis_and_feedback"]]
            )
            fields = {"hypothesis_and_feedback": families.filter_history(history, hidden, closed)}
            if "last_hypothesis_and_feedback" in compact:
                last = len(pairs) - 1
                fields["last_hypothesis_and_feedback"] = summaries.get(
                    last
                ) or families.filter_history(
                    compact["last_hypothesis_and_feedback"], hidden, closed
                )
            chars = sum(len(value) for value in fields.values())
            if chars <= HISTORY_CHAR_BUDGET or (not full and omitted >= len(lines)):
                break
            if full:
                full.remove(min(full))
                continue
            # Never raise: leave out the oldest whole lines (plus room for the note line).
            # Each pass removes at least one line, so the loop ends by len(lines) at the latest.
            excess = max(1, chars - HISTORY_CHAR_BUDGET + len(note[0]) + 8)
            while excess > 0 and omitted < len(lines):
                excess -= len(lines[omitted]) + 1
                omitted += 1

        context.update(fields)
        if self.component == "experiment" and os.environ.get("ALPHA_FACTOR_DISCUSS") == "1":
            discussion = importlib.import_module(
                f"{__package__}.discussion" if __package__ else "discussion"
            )
            context["hypothesis_and_feedback"] += discussion.run_choices(
                Path(os.environ["ALPHA_FACTOR_RUN_DIR"])
            )
        if self.receipt is not None:
            counts = {
                "history_rounds_full": len(full),
                "history_rounds_summarised": len(summaries),
                "history_ideas_omitted": omitted,
            }
            record = json.loads(self.receipt.read_bytes())
            record.setdefault("history_prompts", []).append(
                {"component": self.component, "history_chars": chars, **counts}
            )
            if self.component == "hypothesis":
                record.update(counts)
            temporary = self.receipt.with_suffix(".tmp")
            temporary.write_text(_json(record) + "\n")
            temporary.replace(self.receipt)
        return context, flag


def limit_restored_history(loop: Any, environ: Mapping[str, str]) -> None:
    if not environ.get("ALPHA_FACTOR_RUN_DIR"):
        return
    run = Path(environ["ALPHA_FACTOR_RUN_DIR"])
    panel = json.loads((run / "panel/panel-receipt.json").read_text())["panel_sha256"]
    restored = len(loop.trace.hist)
    path = run / "history-context.json"
    for name, component in (
        ("hypothesis", loop.hypothesis_gen),
        ("experiment", loop.hypothesis2experiment),
    ):
        upstream = getattr(component, "upstream_history", None)
        wrapper = ProposalHistory(
            upstream or component.prepare_context, restored, panel, receipt=path, component=name
        )
        if upstream is None:
            component.prepare_context = wrapper
        else:
            # Append the current universe, refusal and ledger instructions after budgeting.
            component.bounded_history = wrapper
        if name == "hypothesis":
            path.write_text(_json(wrapper.counts(loop.trace)) + "\n")


def restored_run_provenance(previous: Any, session: Path) -> None:
    """Old checkpoints retain this run's experiments in loop_prev_out, even without judging.

    Match by object identity in the deserialised trace: inherited rounds must not acquire
    the latest run's panel. Future checkpoints retain alpha_run_dir on each recorded round.
    """
    current = []
    for output in getattr(previous, "loop_prev_out", {}).values():
        proposal = output.get("direct_exp_gen") or {}
        exp = output.get("running") or output.get("coding") or proposal.get("exp_gen")
        if exp is not None:
            current.append(exp)
    if not current:
        return
    for exp, _ in previous.trace.hist:
        if not getattr(exp, "alpha_run_dir", None) and any(exp is item for item in current):
            exp.alpha_run_dir = str(session.parents[2])


def _now() -> str:
    return datetime.now(UTC).isoformat()


def judge_sha256() -> str:
    names = (
        "alpha_factor_judge.py",
        "alpha_factor_hypothesis.py",
        "discussion.py",
        "alpha_factor_data.py",
        "factor_loop_entry.py",
        "idea_families.py",
        "loop_guard.py",
    )
    return hashlib.sha256(
        _json({name: _hash(WORKER / name) for name in names}).encode()
    ).hexdigest()


@dataclass
class MemoryPlan:
    memory_dir: Path
    env: dict[str, str]
    continue_from: dict[str, Any] | None
    loops_before: int
    knowledge_sha256_before: str | None
    warnings: list[dict[str, Any]]
    judge_sha256: str


def close_unfinished_rounds(session: Path, *, exit_reason: str = "") -> None:
    """Append an idempotent abandonment record beside the previous session, never a trial."""
    if not session.is_dir():
        return
    record = session.parents[2] / "rounds.jsonl"
    existing = (
        [json.loads(line) for line in record.read_text().splitlines()] if record.exists() else []
    )
    closed = {
        r["loop"]
        for r in existing
        if r.get("status") in {"abandoned_at_cap", "abandoned_after_error"}
    }
    receipt = record.parent / "receipt.json"
    reason = exit_reason or (
        json.loads(receipt.read_text()).get("loop_reason", "") if receipt.exists() else ""
    )
    if reason == "awaiting-discussion":
        return  # An intentional discussion stop has its own round record.
    steps = record.parent / "steps.jsonl"
    failed = {
        r["loop"]
        for line in (steps.read_text().splitlines() if steps.exists() else [])
        if (r := json.loads(line)).get("event") == "end" and r.get("status") == "error"
    }
    cap = any(word in reason for word in ("cap", "limit", "budget"))
    pending = [
        folder
        for folder in session.iterdir()
        if folder.is_dir()
        and folder.name.isdecimal()
        and int(folder.name) not in closed
        and any(p.is_file() for p in folder.glob("*_*"))
        and not any(p.is_file() for p in folder.glob("*_record"))
    ]
    if pending:
        with record.open("a") as stream:
            for folder in sorted(pending, key=lambda p: int(p.name)):
                stream.write(
                    _json(
                        {
                            "schema": "AlphaRdagentRoundAbandonedV1",
                            "loop": int(folder.name),
                            "status": "abandoned_after_error"
                            if int(folder.name) in failed and not cap
                            else "abandoned_at_cap",
                            "recorded_at": _now(),
                            "session_dir": str(session),
                            "trial_created": False,
                        }
                    )
                    + "\n"
                )
            stream.flush()
            os.fsync(stream.fileno())


def prepare(
    memory_dir: Path, *, run_id: str, run_dir: Path, source_sha256: str, judge_sha256: str
) -> MemoryPlan:
    """Prepare compatible upstream paths, retaining diagnostics when memory cannot be reused."""
    memory_dir.mkdir(parents=True, exist_ok=True)
    warnings: list[dict[str, Any]] = []
    with _lock(memory_dir):
        try:
            manifest = _read(memory_dir)
        except FileNotFoundError:
            manifest = _fresh(source_sha256)
        except (OSError, ValueError, TypeError):
            warning = _warning(
                "memory-unreadable", "The memory manifest could not be read; starting fresh."
            )
            warnings.append(warning)
            _quarantine(memory_dir, [memory_dir / "memory.json", memory_dir / "costeer"], warning)
            manifest = _fresh(source_sha256)
        if manifest["rdagent_source_sha256"] != source_sha256:
            warning = _warning(
                "rdagent-version-changed",
                "RD-Agent changed; starting fresh coding knowledge and research history.",
            )
            warnings.append(warning)
            _quarantine(memory_dir, [memory_dir / "costeer"], warning)
            manifest.update(rdagent_source_sha256=source_sha256, latest_session=None)
        previous = manifest["latest_session"]
        if previous and not completed_loops(Path(previous["session_dir"])):
            warnings.append(
                _warning(
                    "previous-session-missing",
                    "The previous session is missing or has no completed research round; "
                    "keeping coding knowledge.",
                )
            )
            previous = None
        previous_run = manifest["runs"][-1] if manifest["runs"] else previous
        if previous_run and previous_run["judge_sha256"] != judge_sha256:
            warnings.append(
                _warning(
                    "judge-version-changed",
                    "This memory was made under an earlier version of ALPHA's judge; "
                    "continuing with the current judge.",
                )
            )
        for name in ("costeer", "signing"):
            (memory_dir / name).mkdir(exist_ok=True)
        _write(memory_dir, manifest)
        knowledge = memory_dir / KNOWLEDGE
        env = {
            "FACTOR_CoSTEER_knowledge_base_path": str(knowledge),
            "FACTOR_CoSTEER_new_knowledge_base_path": str(knowledge),
            "FACTOR_CoSTEER_enable_filelock": "True",
            "FACTOR_CoSTEER_filelock_path": str(memory_dir / "costeer/factor-knowledge.lock"),
            "ARTIFACT_SIGNING_KEY_PATH": str(memory_dir / "signing/artifact_signing.key"),
            "ALPHA_RDAGENT_MEMORY_DIR": str(memory_dir),
            "ALPHA_RDAGENT_MEMORY_EVENTS": str(run_dir / "memory-events.jsonl"),
        }
        if previous:
            env.update(
                ALPHA_RDAGENT_CONTINUE_SESSION=previous["session_dir"],
                ALPHA_RDAGENT_CONTINUE_LOOPS=str(previous["completed_loops"]),
            )
        return MemoryPlan(
            memory_dir,
            env,
            previous,
            previous["completed_loops"] if previous else 0,
            _hash(knowledge),
            warnings,
            judge_sha256,
        )


def _event(environ: Mapping[str, str], code: str, message: str) -> None:
    path = Path(environ["ALPHA_RDAGENT_MEMORY_EVENTS"])
    with path.open("a") as stream:
        stream.write(
            _json(
                {
                    "schema": "AlphaRdagentMemoryEventV1",
                    "code": code,
                    "message": message,
                    "ts": _now(),
                }
            )
            + "\n"
        )


def _new_factor_loop(loop_cls: Any, settings: Any, environ: Mapping[str, str]) -> Any:
    if environ.get("ALPHA_FACTOR_RUN_DIR"):
        # A sibling entry module that imports RD-Agent; loaded only inside the factor runtime.
        judge = importlib.import_module("alpha_factor_judge")

        # Refuse before any model call, with one plain line at the entry-point boundary.
        try:
            judge.current_universe()
        except ValueError as error:
            raise SystemExit(str(error)) from error
        loop = loop_cls(settings)
        guards = importlib.import_module("loop_guard")
        if environ.get("ALPHA_GATEWAY_CALLS"):
            loop.feedback = guards.RoundFeedback(loop.feedback)
            for attribute, step in (
                ("coder", "coding"),
                ("runner", "running"),
                ("summarizer", "feedback"),
            ):
                setattr(
                    loop,
                    attribute,
                    guards.ProviderGuard(
                        getattr(loop, attribute),
                        loop,
                        step,
                        Path(environ["ALPHA_FACTOR_RUN_DIR"]),
                        Path(environ["ALPHA_GATEWAY_CALLS"]),
                        environ["ALPHA_GATEWAY_RUN_ID"],
                        judge.FactorEmptyError,
                        judge.HypothesisFeedback,
                    ),
                )
        loop.coder = judge.FamilyGuard(loop.coder, loop)
        return loop
    return loop_cls(settings)


def open_factor_loop(
    loop_cls: Any, settings: Any, loop_n: int, environ: Mapping[str, str]
) -> tuple[Any, int]:
    """Load signed upstream artifacts, falling back with explicit, secret-free events."""
    if not environ.get("ALPHA_RDAGENT_MEMORY_DIR"):
        return _new_factor_loop(loop_cls, settings, environ), loop_n
    root = Path(environ["ALPHA_RDAGENT_MEMORY_DIR"])
    knowledge = Path(environ["FACTOR_CoSTEER_knowledge_base_path"])
    if knowledge.exists():
        try:
            _load_knowledge(knowledge)
        except ImportError:
            pass  # a broken runtime is not a broken knowledge file: never quarantine for it
        except Exception as error:  # corrupt upstream artifacts must not stop a run
            warning = _warning(
                "knowledge-unloadable",
                f"Coding knowledge could not be loaded ({type(error).__name__}); starting empty.",
            )
            try:
                with _lock(root):
                    _quarantine(root, [knowledge], warning)
            except OSError:
                warning["message"] += " It could not be set aside either."
            _safe_event(environ, **warning)
    session = environ.get("ALPHA_RDAGENT_CONTINUE_SESSION")
    if session:
        # A fresh scheduler receives only completed research history; no paid half-round is
        # resumed. Shared CoSTEER knowledge is loaded by the current coder's normal settings.
        try:
            close_unfinished_rounds(Path(session))
        except (OSError, ValueError) as error:  # a record problem never stops the new run
            _safe_event(
                environ,
                "abandoned-round-unrecorded",
                f"The previous session's unfinished round could not be recorded "
                f"({type(error).__name__}).",
            )
        dumps = sorted(
            (
                p
                for p in Path(session).glob("*/*_record")
                if p.is_file() and p.parent.name.isdecimal()
            ),
            key=lambda p: int(p.parent.name),
            reverse=True,
        )[:3]
        error_type = "no completed round dump"
        for dump in dumps:
            try:
                previous = loop_cls.load(dump, checkout=Path(environ["LOG_TRACE_PATH"]))
                if getattr(previous, "trace", None) is None:
                    raise ValueError("completed checkpoint has no research trace")
                restored_run_provenance(previous, Path(session))
                loop = _new_factor_loop(loop_cls, settings, environ)
                loop.trace = previous.trace
            except Exception as error:
                error_type = type(error).__name__
                _safe_event(
                    environ,
                    "checkpoint-unloadable",
                    f"Completed checkpoint {dump.name}: {error_type}",
                )
                continue
            limit_restored_history(loop, environ)
            _safe_event(
                environ,
                "continued",
                f"Restored completed history from {session}/{dump.parent.name}/{dump.name}; "
                f"starting {loop_n} new rounds at a fresh scheduler boundary.",
            )
            return loop, loop_n
        _safe_event(
            environ,
            "session-unloadable",
            f"The previous session could not be loaded ({error_type}); starting a fresh loop.",
        )
    return _new_factor_loop(loop_cls, settings, environ), loop_n


def _safe_event(environ: Mapping[str, str], code: str, message: str) -> None:
    try:
        _event(environ, code, message)
    except OSError:
        print(f"research memory: {code}: {message}", file=sys.stderr)


def _redact(value: Any, secrets: Sequence[str]) -> Any:
    if isinstance(value, str):
        for secret in secrets:
            if secret:
                value = value.replace(secret, "[redacted]")
        return value
    if isinstance(value, list):
        return [_redact(v, secrets) for v in value]
    if isinstance(value, dict):
        return {_redact(k, secrets): _redact(v, secrets) for k, v in value.items()}
    return value


def _record(
    plan: MemoryPlan,
    run_id: str,
    run_dir: Path,
    started_at: str,
    ended_at: str,
    secrets: Sequence[str],
    result: dict[str, Any],
    exit_reason: str,
) -> None:
    root = plan.memory_dir
    knowledge = root / KNOWLEDGE
    session = run_dir / "work/log/__session__"
    with _lock(root):
        manifest = _read(root)
        files = ([knowledge] if knowledge.exists() else []) + sorted(
            p for p in session.rglob("*") if p.is_file()
        )
        found = []
        for path in files:
            raw = path.read_bytes()
            if any(secret.encode() in raw for secret in secrets if secret):
                found.append(str(path.relative_to(root if path == knowledge else run_dir)))
        if found:
            warning = _redact(
                _warning(
                    "secret-found",
                    "Secret found in "
                    + ", ".join(found)
                    + "; coding knowledge deleted; session excluded. "
                    "Run session files remain for the owner to delete.",
                ),
                secrets,
            )
            result["warnings"].append(warning)
            _quarantine(root, [knowledge], warning, delete=True)
        last_completed = completed_loops(session)
        result["knowledge_sha256_after"] = _hash(knowledge)
        events = run_dir / "memory-events.jsonl"
        codes = set()
        if events.exists():
            for line in events.read_text(errors="replace").splitlines():
                try:
                    event = json.loads(line)
                except ValueError:
                    event = None
                if (
                    not _fields(event, {"schema": str, "code": str, "message": str, "ts": str})
                    or event["schema"] != "AlphaRdagentMemoryEventV1"
                ):
                    # The child may die mid-write; one bad line must not lose the whole record.
                    result["warnings"].append(
                        _warning("memory-event-corrupt", "A memory event line was unreadable.")
                    )
                    continue
                codes.add(event["code"])
                result["warnings"].append(event)
        # New schedulers number their own rounds from zero. Count completed record files,
        # not the highest session index (old sessions can still have inherited numbering).
        completed = (
            sum(
                folder.is_dir()
                and folder.name.isdecimal()
                and any(p.is_file() for p in folder.glob("*_record"))
                for folder in session.iterdir()
            )
            if last_completed
            else 0
        )
        result["rounds_completed"] = completed
        # A run whose previous session could not be loaded started a new lineage: it inherits
        # no completed rounds, so it counts only its own.
        inherited = 0 if "session-unloadable" in codes else plan.loops_before
        result["loops_after"] = inherited + completed
        progressed = completed > 0
        close_unfinished_rounds(session, exit_reason=exit_reason)
        if not found and progressed:
            manifest["latest_session"] = {
                "run_id": run_id,
                "run_dir": str(run_dir),
                "session_dir": str(session),
                "completed_loops": result["loops_after"],
                "judge_sha256": plan.judge_sha256,
                "recorded_at": ended_at,
            }
        manifest["runs"].append(
            {
                "run_id": run_id,
                "run_dir": str(run_dir),
                "started_at": started_at,
                "ended_at": ended_at,
                "judge_sha256": plan.judge_sha256,
                **{k: v for k, v in result.items() if k not in {"enabled", "memory_dir"}},
            }
        )
        _write(root, _redact(manifest, secrets))


def record(
    plan: MemoryPlan,
    *,
    run_id: str,
    run_dir: Path,
    started_at: str,
    ended_at: str,
    secrets: Sequence[str],
    exit_reason: str = "",
) -> dict[str, Any]:
    """Best-effort receipt after children stop; never expose exception text or secret values."""
    result: dict[str, Any] = {
        "enabled": True,
        "memory_dir": str(plan.memory_dir),
        "continued_from_run_id": plan.continue_from["run_id"] if plan.continue_from else None,
        "loops_before": plan.loops_before,
        "loops_after": 0,
        "knowledge_sha256_before": plan.knowledge_sha256_before,
        "knowledge_sha256_after": None,
        "warnings": list(plan.warnings),
    }
    try:
        _record(plan, run_id, run_dir, started_at, ended_at, secrets, result, exit_reason)
    except Exception as error:  # finishing always returns a diagnostic receipt
        result["warnings"].append(
            _warning(
                "memory-record-failed", f"Memory could not be recorded ({type(error).__name__})."
            )
        )
    return dict(_redact(result, secrets))


def _knowledge_view(knowledge: Any) -> dict[str, Any]:
    nodes = list(knowledge.graph.nodes.values())
    errors = {
        str(getattr(error, "content", error))
        for attempts in knowledge.working_trace_error_analysis.values()
        for analysis in attempts
        for error in analysis
    }
    errors.update(node.content for node in nodes if node.label == "error")
    return {
        "working_factors": sorted(knowledge.success_task_to_knowledge_dict),
        "alpha_rejected": sorted(
            {
                knowledge.node_to_implementation_knowledge_dict[node_id].target_task.factor_name
                for node_id, node in knowledge.graph.nodes.items()
                if node.label == "alpha_rejected_implement"
            }
        ),
        "attempts_per_task": {
            task: len(attempts) for task, attempts in knowledge.working_trace_knowledge.items()
        },
        "error_kinds": sorted(errors),
        "nodes_by_label": dict(Counter(node.label for node in nodes)),
        "nodes_with_embeddings": sum(node.embedding is not None for node in nodes),
    }


def _runtime_view(source: Path, root: Path) -> dict[str, Any]:
    # Install the same verified source finder as the entry; no RD-Agent imports in the launcher.
    if str(WORKER) not in sys.path:
        sys.path.insert(0, str(WORKER))
    entry = importlib.import_module("factor_loop_entry")
    entry.install_source(source)
    serialization = importlib.import_module("rdagent.core.serialization")

    manifest = _read(root)
    result: dict[str, Any] = {"schema": "AlphaRdagentMemoryViewV1", "rounds": [], "knowledge": None}
    if (root / KNOWLEDGE).exists():
        result["knowledge"] = _knowledge_view(_load_knowledge(root / KNOWLEDGE))
    latest = manifest["latest_session"]
    if latest:
        files = [
            p
            for p in Path(latest["session_dir"]).glob("*/*_*")
            if p.is_file() and p.parent.name.isdecimal() and p.name.split("_")[0].isdecimal()
        ]
        if files:
            newest = max(files, key=lambda p: (int(p.parent.name), int(p.name.split("_")[0])))
            with newest.open("rb") as stream:
                loop = serialization.load(stream)
            for experiment, feedback in loop.trace.hist:
                result["rounds"].append(
                    {
                        "hypothesis": experiment.hypothesis.hypothesis,
                        "factor_names": [task.factor_name for task in experiment.sub_tasks],
                        "decision": feedback.decision,
                        "reason": str(feedback.reason or "")[:300],
                        "observation": str(getattr(feedback, "observations", "") or ""),
                        "refused_before_coding": getattr(
                            experiment, "alpha_refused_before_coding", []
                        ),
                    }
                )
    return result


def _inspect_runtime(root: Path, environ: Mapping[str, str]) -> dict[str, Any]:
    if not environ.get("ALPHA_FACTOR_PYTHON") or not environ.get("ALPHA_RDAGENT_SOURCE"):
        return {
            "message": "The factor runtime is unavailable; set ALPHA_FACTOR_PYTHON and "
            "ALPHA_RDAGENT_SOURCE to inspect coding knowledge and research rounds."
        }
    with tempfile.TemporaryDirectory(prefix="alpha-memory-view-") as temporary:
        home = Path(temporary)
        key = root / "signing/artifact_signing.key"
        if key.exists():
            shutil.copyfile(key, home / "artifact_signing.key")
            (home / "artifact_signing.key").chmod(0o600)
        environment = {k: environ[k] for k in ("PATH", "LANG") if k in environ}
        environment.update(
            HOME=temporary,
            ARTIFACT_SIGNING_KEY_PATH=str(home / "artifact_signing.key"),
            LOG_TRACE_PATH=str(home / "log"),
            LITELLM_LOCAL_MODEL_COST_MAP="True",
        )
        process = subprocess.run(
            [
                environ["ALPHA_FACTOR_PYTHON"],
                "-I",
                "-B",
                str(Path(__file__).resolve()),
                "view",
                environ["ALPHA_RDAGENT_SOURCE"],
                str(root),
            ],
            cwd=home,
            env=environment,
            text=True,
            capture_output=True,
            check=False,
            timeout=60,
        )
        if process.returncode:
            return {
                "message": f"The factor runtime could not read memory (exit {process.returncode})."
            }
        return dict(json.loads(process.stdout))


def show(root: Path, *, ledger: Path | None = None) -> dict[str, Any]:
    result: dict[str, Any] = {
        "schema": "AlphaRdagentMemoryViewV1",
        "memory_dir": str(root),
        "manifest": None,
        "rounds": [],
        "knowledge": None,
    }
    with _lock(root, shared=True):
        if not (root / "memory.json").exists():
            return {**result, "message": "RD-Agent has no memory yet."}
        try:
            result["manifest"] = _read(root)
            result.update(_inspect_runtime(root, os.environ))
        except (OSError, ValueError, subprocess.SubprocessError) as error:
            result["message"] = f"Memory could not be inspected ({type(error).__name__})."
    if ledger:
        rows = []
        try:
            raw = ledger.read_bytes()
        except OSError:
            raw = b""
            result["message"] = "The trial ledger could not be read."
        # Only complete lines: a run may be appending right now.
        skipped = 0
        for line in raw[: raw.rfind(b"\n") + 1].splitlines():
            try:
                row = json.loads(line)
            except ValueError:
                row = None
            if isinstance(row, dict):
                rows.append(row)
            elif line.strip():
                skipped += 1
        if skipped:
            result["ledger_warning"] = (
                f"{skipped} trial ledger line(s) could not be read; their verdicts are not shown."
            )
        for round_ in result["rounds"]:
            round_["alpha_verdicts"] = {
                name: [
                    {key: row.get(key) for key in ("status", "q", "run_id")}
                    for row in rows
                    if row.get("name") == name
                ]
                for name in round_["factor_names"]
            }
    return result


def _plain(view: dict[str, Any]) -> str:
    manifest = view["manifest"]
    if manifest is None:
        return str(view["message"])
    rounds = view["rounds"]
    knowledge = view["knowledge"]
    lines = [
        f"RD-Agent remembers {len(rounds)} research rounds from {len(manifest['runs'])} runs.",
        f"Memory lives at {view['memory_dir']}.",
    ]
    if knowledge is not None:
        lines.append(
            f"It has {len(knowledge['working_factors'])} working factor programs it can reuse."
        )
        lines.append("Working programs: " + ", ".join(knowledge["working_factors"]))
        lines.append("ALPHA rejected the code of: " + ", ".join(knowledge["alpha_rejected"]))
        lines.append("Coding attempts per task: " + _json(knowledge["attempts_per_task"]))
        lines.append("Past coding errors: " + ", ".join(knowledge["error_kinds"]))
        lines.append("Knowledge links by kind: " + _json(knowledge["nodes_by_label"]))
        lines.append(
            f"{knowledge['nodes_with_embeddings']} knowledge entries can be found by similarity."
        )
    for index, round_ in enumerate(rounds, 1):
        lines.append(
            f"Round {index}: {round_['hypothesis']}\n"
            f"Factors: {', '.join(round_['factor_names'])}\n"
            f"RD-Agent decision: {round_['decision']}; {round_['reason']}"
        )
        lines.extend(round_.get("refused_before_coding", []))
        if round_.get("observation"):
            lines.append(round_["observation"])
        if "alpha_verdicts" in round_:
            lines.append("ALPHA's verdicts: " + _json(round_["alpha_verdicts"]))
    if "message" in view:
        lines.append(view["message"])
    if "ledger_warning" in view:
        lines.append(view["ledger_warning"])
    lines.append("ALPHA's trial ledger is the evidence authority.")
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description="RD-Agent's own persistent knowledge and sessions; ALPHA's ledger is the record"
    )
    sub = parser.add_subparsers(dest="command", required=True)
    inspect = sub.add_parser("show")
    inspect.add_argument("--memory-dir", type=Path, required=True)
    inspect.add_argument("--json", action="store_true")
    inspect.add_argument("--trial-ledger", type=Path)
    view = sub.add_parser("view")
    view.add_argument("source", type=Path)
    view.add_argument("memory_dir", type=Path)
    args = parser.parse_args(argv)
    if args.command == "view":
        with redirect_stdout(sys.stderr):
            result = _runtime_view(args.source, args.memory_dir)
        print(_json(result))
    else:
        result = show(args.memory_dir.resolve(), ledger=args.trial_ledger)
        print(_json(result) if args.json else _plain(result))


class MemoryEmbeddingError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def _gateway_embeddings(inputs: str | list[str]) -> dict[str, Any]:
    """Use the run's gateway session, bypassing upstream's model-agnostic vector cache."""
    import urllib.error
    import urllib.request

    request = urllib.request.Request(
        os.environ["LM_STUDIO_API_BASE"].rstrip("/") + "/embeddings",
        data=json.dumps({"model": "alpha-embed", "input": inputs}).encode(),
        headers={
            "Content-Type": "application/json",
            "Authorization": "Bearer " + os.environ["LM_STUDIO_API_KEY"],
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=180) as response:
            body = json.load(response)
    except urllib.error.HTTPError as error:
        body = json.loads(error.read())
        detail = body.get("error", {})
        raise MemoryEmbeddingError(
            str(detail.get("code", "gateway_error")),
            str(detail.get("message", "gateway embedding failed")),
        ) from None
    return dict(body)


def gateway_embedding(text: str) -> tuple[str, list[float]]:
    body = _gateway_embeddings(text)
    return str(body["model"]), list(body["data"][0]["embedding"])


def gateway_embedding_batch(
    texts: list[str],
) -> tuple[str, list[list[float] | MemoryEmbeddingError]]:
    body = _gateway_embeddings(texts)
    results: dict[int, list[float] | MemoryEmbeddingError] = {}
    for item in body["data"]:
        index = item["index"]
        if type(index) is not int or index in results:
            raise ValueError("invalid batch embedding indices")
        results[index] = item["embedding"]
    for error in body.get("input_errors", []):
        index = error["index"]
        if type(index) is not int or index in results:
            raise ValueError("invalid batch embedding error indices")
        results[index] = MemoryEmbeddingError(error["code"], error["message"])
    if set(results) != set(range(len(texts))):
        raise ValueError("batch embedding inputs and outputs differ")
    return str(body["model"]), [results[i] for i in range(len(texts))]


class EmbeddingMemory:
    """Per-entry sidecar, checked lazily when the coder first uses its graph.

    Sidecar vectors are bound to text, model and dimension. Unknown legacy vectors are
    re-embedded. Failed entries are removed from the active graph and returned for restoration
    after retrieval; the original persistent knowledge is retained for a later run.
    """

    def __init__(
        self,
        sidecar: Path,
        events: Path,
        model: str,
        embed: Callable[[str], tuple[str, list[float]]],
    ) -> None:
        self.sidecar, self.events, self.model, self.embed = sidecar, events, model, embed
        self.embed_many = (
            gateway_embedding_batch
            if embed is gateway_embedding and os.environ.get("ALPHA_EMBEDDING_ROUTE") == "provider"
            else None
        )
        self.dimension: int | None = None
        self.failed: dict[str, str] = {}
        self.reembedded: set[str] = set()
        try:
            data = json.loads(sidecar.read_text())
        except FileNotFoundError:
            data = {"schema": "AlphaEmbeddingMemoryV1", "entries": {}}
        if data.get("schema") != "AlphaEmbeddingMemoryV1" or not isinstance(
            data.get("entries"), dict
        ):
            raise ValueError("invalid embedding memory sidecar")
        self.entries: dict[str, Any] = data["entries"]

    def checked(self, vector: Any) -> list[float]:
        import math

        if (
            not isinstance(vector, list)
            or not vector
            or any(type(v) not in (int, float) or not math.isfinite(v) for v in vector)
        ):
            raise ValueError("invalid memory vector")
        if self.dimension is not None and len(vector) != self.dimension:
            raise ValueError("memory embedding dimension changed")
        self.dimension = len(vector)
        return list(vector)

    def vector(self, text: str) -> list[float]:
        model, vector = self.embed(text)
        if model != self.model:
            raise ValueError("gateway returned a different embedding model")
        return self.checked(vector)

    def save(self) -> None:
        self.sidecar.parent.mkdir(parents=True, exist_ok=True)
        with _lock(self.sidecar.parent):
            descriptor, name = tempfile.mkstemp(prefix=".embedding-", dir=self.sidecar.parent)
            try:
                with os.fdopen(descriptor, "w") as stream:
                    json.dump(
                        {"schema": "AlphaEmbeddingMemoryV1", "entries": self.entries},
                        stream,
                        allow_nan=False,
                    )
                    stream.flush()
                    os.fsync(stream.fileno())
                os.replace(name, self.sidecar)
            finally:
                Path(name).unlink(missing_ok=True)

    def remember(self, node_id: str, node: Any) -> None:
        vector = self.checked(node.embedding)
        self.entries[node_id] = {
            "model": self.model,
            "dimension": len(vector),
            "vector": vector,
            "text_sha256": hashlib.sha256(node.content.encode()).hexdigest(),
        }

    def rebuild(self, graph: Any) -> None:
        """PDVectorBase.search reads this table, not the embeddings on graph.nodes.

        Recreate its full-node rows (including trunk=content); never copy stale chunk rows
        from an old table. Nodes without a current vector retain their text only.
        """
        rows = (
            [
                {
                    "id": node_id,
                    "label": node.label,
                    "content": node.content,
                    "trunk": node.content,
                    "embedding": self.checked(node.embedding),
                }
                for node_id, node in graph.nodes.items()
                if node.embedding is not None
            ]
            if getattr(graph, "vector_base", None) is not None
            else []
        )
        if getattr(graph, "vector_base", None) is not None:
            import pandas as pd

            graph.vector_base.vector_df = pd.DataFrame(
                rows, columns=["id", "label", "content", "trunk", "embedding"]
            )
        # A restored graph can contain new vectorless nodes as well as refused inputs
        # currently hidden from search. Reporting them must not change retry eligibility.
        left_out = dict(self.failed)
        for node_id, node in graph.nodes.items():
            if node.embedding is None:
                left_out.setdefault(
                    node_id, "empty text" if not node.content.strip() else "no current vector"
                )
        (self.events.parent / "knowledge-vectors.json").write_text(
            _json(
                {
                    "knowledge_vectors": len(rows),
                    "knowledge_vectors_reembedded": len(self.reembedded),
                    "knowledge_vectors_left_out": len(left_out),
                    "knowledge_vectors_left_out_nodes": [
                        {"id": node_id, "reason": reason}
                        for node_id, reason in sorted(left_out.items())
                    ],
                    "knowledge_vector_dimension": self.dimension,
                }
            )
            + "\n"
        )

    def restore_vectors(self, graph: Any) -> None:
        """Repair the saved graph without extra calls, even if coding failed before its dump."""
        for node_id, node in graph.nodes.items():
            cached = self.entries.get(node_id, {})
            if (
                node_id not in self.failed
                and cached.get("model") == self.model
                and cached.get("text_sha256") == hashlib.sha256(node.content.encode()).hexdigest()
            ):
                node.embedding = self.checked(cached["vector"])
            else:
                node.embedding = None
                self.failed.setdefault(
                    node_id,
                    "empty text" if not node.content.strip() else "no matching cached vector",
                )
        self.rebuild(graph)

    @staticmethod
    def left_out_reason(text: str, error: Exception) -> str:
        message = str(error).lower()
        if not text.strip():
            return "empty text"
        if any(
            term in message
            for term in ("too long", "too_long", "context_length", "exceeds context")
        ):
            return "over length"
        if getattr(error, "code", None) == "embedding_input_refused" or "refused" in message:
            return "embedding refused"
        return f"{type(error).__name__}: {error}"

    def prepare(self, graph: Any, skip: Callable[[Any, Exception], None]) -> dict[str, Any]:
        removed = {}
        pending = []
        for node_id, node in list(graph.nodes.items()):
            if node_id in self.failed:
                removed[node_id] = graph.nodes.pop(node_id)
                continue
            cached = self.entries.get(node_id, {})
            text_hash = hashlib.sha256(node.content.encode()).hexdigest()
            if cached.get("model") == self.model and cached.get("text_sha256") == text_hash:
                vector = self.checked(cached["vector"])
                if cached.get("dimension") != len(vector):
                    raise ValueError("sidecar dimension differs")
                node.embedding = vector
                continue
            pending.append((node_id, node))
        vectors: list[list[float] | Exception] | None = None
        if len(pending) > 1 and self.embed_many is not None:
            try:
                model, batch = self.embed_many([node.content for _, node in pending])
                if model != self.model:
                    raise ValueError("gateway returned a different embedding model")
                if len(batch) != len(pending):
                    raise ValueError("batch embedding count differs")
                vectors = list(batch)
            except Exception as error:
                # A failed batch fails each of its inputs through the skip policy, so a budget
                # stop still ends the run there and nothing is re-sent one input at a time.
                vectors = [error] * len(pending)
        for index, (node_id, node) in enumerate(pending):
            try:
                value = vectors[index] if vectors is not None else self.vector(node.content)
                if isinstance(value, Exception):
                    raise value
                vector = self.checked(value)
            except Exception as error:
                skip(node, error)  # budget errors must raise SystemExit before marking a skip
                self.failed[node_id] = self.left_out_reason(node.content, error)
                removed[node_id] = graph.nodes.pop(node_id)
                # No stale vector can be reached by a retained neighbour reference either.
                node.embedding = None
                continue
            node.embedding = vector
            self.remember(node_id, node)
            self.reembedded.add(node_id)
            self.save()
            with self.events.open("a") as stream:
                stream.write(
                    _json(
                        {
                            "node_id": node_id,
                            "model": self.model,
                            "dimension": len(vector),
                            "text_sha256": hashlib.sha256(node.content.encode()).hexdigest(),
                        }
                    )
                    + "\n"
                )
        self.rebuild(graph)
        return removed


if __name__ == "__main__":
    main()
