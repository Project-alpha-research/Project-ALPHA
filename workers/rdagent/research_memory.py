"""RD-Agent's own persistent knowledge and sessions; ALPHA's ledger remains authoritative."""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import importlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from collections import Counter
from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import contextmanager, redirect_stdout
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

SCHEMA = "AlphaRdagentResearchMemoryV1"
KNOWLEDGE = "costeer/factor-knowledge.pkl"
WORKER = Path(__file__).resolve().parent


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=True)


def _hash(path: Path) -> str | None:
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else None


def judge_sha256() -> str:
    names = ("alpha_factor_judge.py", "alpha_factor_data.py", "factor_loop_entry.py")
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


@contextmanager
def _lock(root: Path, *, shared: bool = False) -> Iterator[None]:
    path = root / "memory.lock"
    # Inspection must not even create a lock file in an empty directory.
    if shared and not path.exists():
        yield
        return
    with path.open("rb" if shared else "a+b") as stream:
        fcntl.flock(stream, fcntl.LOCK_SH if shared else fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(stream, fcntl.LOCK_UN)


def _write(root: Path, value: dict[str, Any]) -> None:
    descriptor, name = tempfile.mkstemp(prefix=".memory-", dir=root)
    try:
        with os.fdopen(descriptor, "w") as stream:
            stream.write(_json(value) + "\n")
        os.replace(name, root / "memory.json")
    finally:
        Path(name).unlink(missing_ok=True)


def _fresh(source: str) -> dict[str, Any]:
    return {
        "schema": SCHEMA,
        "rdagent_source_sha256": source,
        "scenario": "fin_factor",
        "knowledge_file": KNOWLEDGE,
        "latest_session": None,
        "runs": [],
    }


def _fields(value: Any, fields: Mapping[str, Any]) -> bool:
    return isinstance(value, dict) and all(
        key in value and type(value[key]) in (kind if isinstance(kind, tuple) else (kind,))
        for key, kind in fields.items()
    )


def _read(root: Path) -> dict[str, Any]:
    value = json.loads((root / "memory.json").read_text())
    valid = _fields(
        value,
        {
            "schema": str,
            "rdagent_source_sha256": str,
            "scenario": str,
            "knowledge_file": str,
            "runs": list,
            "latest_session": (dict, type(None)),
        },
    )
    if not valid or (value["schema"], value["scenario"], value["knowledge_file"]) != (
        SCHEMA,
        "fin_factor",
        KNOWLEDGE,
    ):
        raise ValueError("Invalid memory manifest")
    latest = value["latest_session"]
    if latest is not None and (
        not _fields(
            latest,
            {
                "run_id": str,
                "run_dir": str,
                "session_dir": str,
                "completed_loops": int,
                "judge_sha256": str,
                "recorded_at": str,
            },
        )
        or latest["completed_loops"] < 0
    ):
        raise ValueError("Invalid latest session")
    for run in value["runs"]:
        if not _fields(
            run,
            {
                "run_id": str,
                "run_dir": str,
                "started_at": str,
                "ended_at": str,
                "continued_from_run_id": (str, type(None)),
                "loops_before": int,
                "loops_after": int,
                "knowledge_sha256_before": (str, type(None)),
                "knowledge_sha256_after": (str, type(None)),
                "judge_sha256": str,
                "warnings": list,
            },
        ) or any(not _fields(w, {"code": str, "message": str}) for w in run["warnings"]):
            raise ValueError("Invalid memory run")
    return dict(value)


def _warning(code: str, message: str) -> dict[str, str]:
    return {"code": code, "message": message}


def _quarantine(
    root: Path, paths: Sequence[Path], warning: dict[str, str], *, delete: bool = False
) -> None:
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    parent = root / "quarantine"
    parent.mkdir(exist_ok=True)
    destination = parent / f"{stamp}-{warning['code']}"
    # Preserve earlier quarantines even if two failures occur within the same second.
    if destination.exists():
        destination = Path(tempfile.mkdtemp(prefix=destination.name + "-", dir=parent))
    else:
        destination.mkdir()
    moved = []
    for path in paths:
        if path.exists():
            moved.append(str(path.relative_to(root)))
            if delete:
                path.unlink()
            else:
                shutil.move(str(path), destination / path.name)
    (destination / "reason.json").write_text(
        _json(
            {
                "schema": "AlphaRdagentMemoryQuarantineV1",
                **warning,
                "moved": moved,
            }
        )
        + "\n"
    )


def completed_loops(session_dir: Path) -> int:
    """Loops completed in the whole session lineage: highest recorded loop index plus one.

    A continued session keeps RD-Agent's loop numbering, so its folder holds only the new loops
    (for example ``2`` after two inherited ones); counting folders would undercount and the next
    run's ``loop_n`` would be spent on loops that already finished.
    """
    if not session_dir.is_dir():
        return 0
    indexes = [
        int(folder.name)
        for folder in session_dir.iterdir()
        if folder.is_dir()
        and folder.name.isdecimal()
        and any(p.is_file() for p in folder.glob("*_record"))
    ]
    return max(indexes) + 1 if indexes else 0


def close_unfinished_rounds(session: Path) -> None:
    """Append an idempotent abandonment record beside the previous session, never a trial."""
    if not session.is_dir():
        return
    record = session.parents[2] / "rounds.jsonl"
    existing = (
        [json.loads(line) for line in record.read_text().splitlines()] if record.exists() else []
    )
    closed = {r["loop"] for r in existing if r.get("status") == "abandoned_at_cap"}
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
                            "status": "abandoned_at_cap",
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
        if previous and previous["judge_sha256"] != judge_sha256:
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


def _load_knowledge(path: Path) -> Any:
    # These modules exist only in the verified factor runtime, not the root environment.
    knowledge_module = importlib.import_module(
        "rdagent.components.coder.CoSTEER.knowledge_management"
    )
    serialization = importlib.import_module("rdagent.core.serialization")

    with path.open("rb") as stream:
        knowledge = serialization.load(stream)
    if not isinstance(knowledge, knowledge_module.CoSTEERKnowledgeBaseV2):
        raise TypeError("Unexpected knowledge type")
    return knowledge


def _new_factor_loop(loop_cls: Any, settings: Any, environ: Mapping[str, str]) -> Any:
    if environ.get("ALPHA_FACTOR_RUN_DIR"):
        from alpha_factor_judge import FamilyGuard, current_universe

        # Refuse before any model call, with one plain line at the entry-point boundary.
        try:
            current_universe()
        except ValueError as error:
            raise SystemExit(str(error)) from error
        loop = loop_cls(settings)
        loop.coder = FamilyGuard(loop.coder, loop)
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
        close_unfinished_rounds(session)
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
        _record(plan, run_id, run_dir, started_at, ended_at, secrets, result)
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
                        "reason": feedback.reason[:300],
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


def gateway_embedding(text: str) -> tuple[str, list[float]]:
    """Use the run's gateway session, bypassing upstream's model-agnostic vector cache."""
    import urllib.error
    import urllib.request

    request = urllib.request.Request(
        os.environ["LM_STUDIO_API_BASE"].rstrip("/") + "/embeddings",
        data=json.dumps({"model": "alpha-embed", "input": text}).encode(),
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
    return str(body["model"]), list(body["data"][0]["embedding"])


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
        self.dimension: int | None = None
        self.failed: set[str] = set()
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

    def prepare(self, graph: Any, skip: Callable[[Any, Exception], None]) -> dict[str, Any]:
        removed = {}
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
            try:
                vector = self.vector(node.content)
            except Exception as error:
                skip(node, error)  # budget errors must raise SystemExit before marking a skip
                self.failed.add(node_id)
                removed[node_id] = graph.nodes.pop(node_id)
                # No stale vector can be reached by a retained neighbour reference either.
                node.embedding = None
                continue
            node.embedding = vector
            self.remember(node_id, node)
            self.save()
            with self.events.open("a") as stream:
                stream.write(
                    _json(
                        {
                            "node_id": node_id,
                            "model": self.model,
                            "dimension": len(vector),
                            "text_sha256": text_hash,
                        }
                    )
                    + "\n"
                )
        return removed


if __name__ == "__main__":
    main()
