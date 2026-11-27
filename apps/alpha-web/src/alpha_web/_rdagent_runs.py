"""Read a closed projection of factor receipts and the default ledger, without execution.

No request string is a path. No artifact reference in a receipt is followed. Counts that the
writer did not record remain unknown: in particular, candidate is not a deflation verdict.
"""

from __future__ import annotations

import json
import re
import shlex
from datetime import datetime
from pathlib import Path
from typing import Any

from alpha_web._rdagent_run_factor import _factor
from alpha_web._rdagent_run_files import (
    FACTOR_SCHEMAS,
    MISSING,
    RECEIPT_SCHEMA,
    _get,
    _json,
    _lines,
    _object,
    _read,
    _record_path,
    _stamp,
    _text,
    counted,
    fact,
    project,
)
from alpha_web._rdagent_run_funnel import _funnel, _ledger, _ledger_factor_rows
from alpha_web._rdagent_run_story import IdeaKey, _story, _story_key
from alpha_web._rdagent_run_words import (
    CACHE,
    UNIVERSE,
    status_sentence,
)
from alpha_web.api.rdagent_models import (
    JourneyIdea,
    JourneyMissing,
    RdAgentCap,
    RdAgentDetail,
    RdAgentRun,
    RdAgentRunList,
    RdAgentStory,
    RecordedFact,
    StoredJourney,
)


def _runs(root: Path) -> list[tuple[Path, dict[str, Any]]]:
    if not root.exists():
        return []
    if root.is_symlink() or not root.is_dir():
        raise ValueError("The RD-Agent runs directory is not a regular directory.")
    result: list[tuple[Path, dict[str, Any]]] = []
    seen: set[str] = set()
    for folder in sorted(root.iterdir()):
        if folder.is_symlink() or not folder.is_dir():
            continue
        receipt = _json(folder, "receipt.json")
        if receipt.get("schema") != RECEIPT_SCHEMA:
            continue
        run_id = receipt.get("run_id")
        if not isinstance(run_id, str) or not re.fullmatch(
            r"[A-Za-z0-9][A-Za-z0-9_.-]{0,199}", run_id
        ):
            raise ValueError("Invalid recorded RD-Agent run identity.")
        if run_id in seen:
            raise ValueError("Duplicate recorded RD-Agent run identity.")
        seen.add(run_id)
        result.append((folder, receipt))
    return sorted(result, key=lambda item: _started(item[1]), reverse=True)


def _started(receipt: dict[str, Any]) -> float:
    value = receipt.get("started_at")
    if value is None:
        return float("-inf")
    stamp = datetime.fromisoformat(value)
    if stamp.tzinfo is None:
        raise ValueError("RD-Agent timestamps must include a timezone.")
    return stamp.timestamp()


def _summary(
    folder: Path,
    receipt: dict[str, Any],
    panel: dict[str, Any],
    counts: dict[str, RecordedFact],
) -> RdAgentRun:
    exit_status = receipt.get("exit_status")
    reason = str(receipt.get("loop_reason", "")).lower()
    outcome = None
    if exit_status is not None:
        outcome = "completed" if exit_status == 0 else "error"
        if any(word in reason for word in ("budget_exhausted", "cap", "wall-clock limit")):
            outcome = "stopped by a cap"
    return RdAgentRun(
        run_id=receipt["run_id"],
        folder=_text(folder.name),
        started_at=fact(receipt.get("started_at")),
        ended_at=fact(receipt.get("ended_at")),
        outcome=fact(outcome),
        rounds_completed=fact(
            receipt.get("rounds_completed", _get(receipt, "memory.rounds_completed"))
        ),
        counted_calls=fact(
            receipt.get("counted_calls", _get(receipt, "gateway_status.this_run.calls"))
        ),
        local_embedding_calls=fact(receipt.get("local_embedding_calls")),
        provider_embedding_calls=fact(receipt.get("provider_embedding_calls")),
        cost_usd=fact(_get(receipt, "gateway_status.this_run.usd")),
        factors_proposed=counts["proposed"],
        stages=counts,
        universe_size=_universe_size(panel),
        universe_includes_delisted=fact(panel.get("universe_includes_delisted")),
    )


def _universe_size(panel: dict[str, Any]) -> RecordedFact:
    names = panel.get("instruments")
    if isinstance(names, (dict, list)):
        return counted(len(names), "counted from the instruments listed in the panel receipt")
    return fact(None)


def list_runs(root: Path, ledger: Path) -> RdAgentRunList:
    ledger_rows, ledger_reason = _ledger(ledger)
    has_ledger = ledger.exists()
    items = []
    for folder, receipt in _runs(root):
        rounds, _ = _lines(folder, "rounds.jsonl")
        has_rounds = (folder / "rounds.jsonl").exists()
        counts = _funnel(
            receipt,
            _ledger_factor_rows(ledger_rows, receipt["run_id"], folder) if has_ledger else None,
            rounds if has_rounds else None,
        )
        items.append(_summary(folder, receipt, _json(folder, "panel/panel-receipt.json"), counts))
    return RdAgentRunList(
        items=items,
        reason=None
        if items
        else "No RD-Agent run is stored yet. Start one with: alpha rdagent run",
        ledger_reason=ledger_reason if not has_ledger else None,
    )


def _caps(receipt: dict[str, Any]) -> dict[str, RdAgentCap]:
    stamp = receipt.get("ended_at") or receipt.get("started_at")
    month = datetime.fromisoformat(stamp).strftime("%Y-%m") if stamp else None
    values = {
        "calls": (
            receipt.get("counted_calls", _get(receipt, "gateway_status.this_run.calls")),
            _get(receipt, "gateway_status.caps.run_max_calls") or receipt.get("run_max_calls"),
        ),
        "run_usd": (
            _get(receipt, "gateway_status.this_run.usd"),
            _get(receipt, "gateway_status.caps.run_max_usd"),
        ),
        "month_usd": (
            _get(receipt, f"gateway_status.months.{month}.usd") if month else None,
            _get(receipt, "gateway_status.caps.month_max_usd"),
        ),
        "month_calls": (
            _get(receipt, f"gateway_status.months.{month}.calls") if month else None,
            _get(receipt, "gateway_status.caps.month_max_calls"),
        ),
    }
    return {
        name: RdAgentCap(used=fact(used), limit=fact(limit))
        for name, (used, limit) in values.items()
    }


def _identity(panel: dict[str, Any], key: str) -> list[dict[str, RecordedFact]]:
    rows = panel.get(key, [])
    if not isinstance(rows, list):
        raise ValueError("Invalid recorded identity corrections.")
    return [
        project(_object(row), ("instrument", "new_from", "reason", "new_name", "ratio"))
        for row in rows
    ]


def _timing(steps: list[dict[str, Any]]) -> list[dict[str, RecordedFact]]:
    """One row per recorded step; minutes are the difference of its two recorded timestamps."""
    starts: dict[tuple[Any, Any, Any], dict[str, Any]] = {}
    ends: dict[tuple[Any, Any, Any], dict[str, Any]] = {}
    for row in steps:
        key = (row.get("loop"), row.get("step_index"), row.get("step"))
        if row.get("event") == "start":
            starts[key] = row
        elif row.get("event") == "end":
            ends[key] = row
    rows: list[dict[str, RecordedFact]] = []
    for key, start in starts.items():
        end = ends.get(key)
        minutes = (
            RecordedFact(value=None, reason="this step has no recorded end")
            if end is None
            else counted(
                round((_stamp(end["ts"]) - _stamp(start["ts"])).total_seconds() / 60, 2),
                "end time minus start time, both recorded",
            )
        )
        rows.append(
            {
                "loop": fact(key[0]),
                "step": fact(key[2]),
                "started_at": fact(start.get("ts")),
                "ended_at": fact(None if end is None else end.get("ts")),
                "minutes": minutes,
                "status": fact(None if end is None else end.get("status")),
            }
        )
    return rows


def _selected_run(root: Path, run_id: str) -> tuple[Path, dict[str, Any]]:
    selected = next((item for item in _runs(root) if item[1]["run_id"] == run_id), None)
    if selected is None:
        raise FileNotFoundError("The requested RD-Agent run is not in the recorded run list.")
    return selected


def read_run(root: Path, ledger: Path, run_id: str) -> RdAgentDetail:
    folder, receipt = _selected_run(root, run_id)
    panel = _json(folder, "panel/panel-receipt.json")
    ledger_rows, ledger_reason = _ledger(ledger)
    factor_rows = _ledger_factor_rows(ledger_rows, run_id, folder)
    factors = [_factor(row) for row in factor_rows]
    unknown = [
        row
        for row in ledger_rows
        if row.get("run_id") == run_id
        and row.get("schema") not in FACTOR_SCHEMAS | {"AlphaRuleTrialV1"}
    ]
    if unknown:
        raise ValueError("This run has an unrecognised trial ledger schema.")
    rounds, refusal_reason = _lines(folder, "rounds.jsonl")
    funnel = _funnel(
        receipt,
        factor_rows if ledger.exists() else None,
        rounds if (folder / "rounds.jsonl").exists() else None,
    )
    steps, timing_reason = _lines(folder, "steps.jsonl")
    evaluations, evaluation_reason = _lines(folder, "evaluations.jsonl")
    evaluations = _archived_evaluations(folder, evaluations)
    story, identities = _story(folder, receipt, factor_rows, rounds, evaluations)
    for issue in (refusal_reason, evaluation_reason):
        if issue and issue != MISSING:
            story.missing_links.append(issue)
    usage = _get(receipt, "call_split.chat_usage") or {}
    providers = _object(usage.get("provider_calls") or {})
    months = _get(receipt, "gateway_status.months") or {}
    if any(not re.fullmatch(r"\d{4}-\d{2}", month) for month in months):
        raise ValueError("Invalid recorded gateway month.")
    notes = [
        str(value)
        for value in (
            receipt.get("call_cap_note"),
            receipt.get("memory_warning"),
            usage.get("summary"),
            panel.get("universe_text"),
            *[row.get("feedback_text") for row in evaluations],
        )
        if value
    ]
    if evaluation_reason and evaluation_reason != MISSING:
        notes.append(evaluation_reason)
    return RdAgentDetail(
        story=story,
        journeys=_journey_ideas(folder, story, identities),
        run=_summary(folder, receipt, panel, funnel),
        funnel=funnel,
        factors=factors,
        factor_reason=ledger_reason,
        refusals=[
            {
                **project(
                    row, ("status", "closed_families", "open_families", "attempt", "trial_created")
                ),
                "sentence": fact(status_sentence(row["status"], None)),
            }
            for row in rounds
            if row.get("status")
            in {
                "refused_closed_family",
                "no_admissible_idea",
                "abandoned_at_cap",
                "abandoned_after_error",
                "coding_failed_provider_timeout",
                "coding_failed_provider_error",
                "coding_failed_internal_error",
                "proposal_failed_provider_timeout",
                "proposal_failed_provider_error",
                "critic_unavailable_provider_timeout",
                "critic_unavailable_provider_error",
            }
        ],
        refusal_reason=refusal_reason,
        timing=_timing(steps),
        timing_reason=timing_reason,
        caps=_caps(receipt),
        months={
            month: project(_object(value), ("calls", "usd")) for month, value in months.items()
        },
        cache=project(usage, CACHE),
        providers={_text(name): fact(value) for name, value in providers.items()},
        universe=project(
            {
                **panel,
                "instruments": list(panel["instruments"])
                if isinstance(panel.get("instruments"), dict)
                else panel.get("instruments"),
            },
            UNIVERSE,
        )
        | {"instrument_count": _universe_size(panel)},
        identity_splits=_identity(panel, "identity_breaks"),
        identity_rescales=_identity(panel, "identity_rescales"),
        notes=[_text(note) for note in notes],
    )


def _archived_evaluations(folder: Path, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The writer accepts either evaluations.jsonl or per-iteration results."""
    by_iteration = {row.get("iteration"): row for row in rows}
    archive = _record_path(folder, "evaluations")
    for path in sorted(archive.glob("iter-*/result.json")):
        row = _json(folder, str(path.relative_to(folder)))
        iteration = row.get("iteration")
        if type(iteration) is not int or path.parent.name != f"iter-{iteration}":
            raise ValueError("Invalid archived evaluation identity.")
        if iteration in by_iteration and row != by_iteration[iteration]:
            raise ValueError("Archived evaluation and evaluation log disagree.")
        if iteration not in by_iteration:
            rows.append(row)
            by_iteration[iteration] = row
    return rows


def _journey_folder(key: IdeaKey) -> str:
    iteration, name, digest = key
    if iteration < 0 or not name.strip() or name in {".", ".."} or Path(name).name != name:
        raise ValueError("Invalid recorded journey name.")
    return f"{iteration}-{name}-{digest[:8]}"


def _journey_ideas(
    folder: Path, story: RdAgentStory, identities: dict[str, IdeaKey]
) -> list[JourneyIdea]:
    # A filtered CLI build still indexes every judged idea. Presence requires its actual file.
    indexed: dict[IdeaKey, str | None] = {}
    for item in _json(folder, "journey/index.json").get("ideas", []):
        key = _story_key(_object(item))
        if key is None or key in indexed or item.get("folder") != _journey_folder(key):
            raise ValueError("Invalid recorded journey index.")
        indexed[key] = None
    for idea in story.ideas:
        key = identities.get(idea.id)
        if key and idea.trial is not None:
            indexed[key] = idea.trial.status
    directories = {_journey_folder(key) for key in indexed}
    if len(directories) != len(indexed):
        raise ValueError("Conflicting recorded journey folder identities.")
    # Copied journeys can outlive their index or evaluation files.
    parent = _record_path(folder, "journey")
    for child in sorted(parent.iterdir()) if parent.exists() else []:
        if child.name in directories or not re.fullmatch(
            r"[0-9]+-.+-[0-9a-f]{8}", child.name, re.DOTALL
        ):
            continue
        content = _read(folder, f"journey/{child.name}/journey.json")
        if content is None:
            continue
        key = _story_key(_object(json.loads(content)))
        if key is None or child.name != _journey_folder(key):
            raise ValueError("Journey file and folder identities disagree.")
        indexed[key] = None
    result = []
    for key, verdict in indexed.items():
        iteration, name, digest = key
        directory = _journey_folder(key)
        path = _record_path(folder, f"journey/{directory}/journey.json")
        if path.exists() and not path.is_file():
            raise ValueError("Invalid recorded journey file.")
        result.append(
            JourneyIdea(
                id=f"{iteration}-{digest}-{name}",
                iteration=iteration,
                name=name,
                verdict=verdict,
                built=path.is_file(),
            )
        )
    for idea in story.ideas:
        if identities.get(idea.id) not in indexed:
            result.append(
                JourneyIdea(
                    id=idea.id,
                    iteration=None,
                    name=str(idea.name.value or "not recorded"),
                    verdict=idea.trial.status if idea.trial else None,
                    built=False,
                )
            )
    return result


def _published_journey(folder: Path, idea_id: str) -> tuple[str, StoredJourney] | None:
    # A folder carries eight hash digits. Bind both reads to the document's full identity.
    identity = re.fullmatch(r"(0|[1-9][0-9]*)-([0-9a-f]{64})-([^/]+)", idea_id, re.DOTALL)
    if identity is None:
        return None
    iteration, digest, name = identity.groups()
    key = int(iteration), name, digest
    expected = _journey_folder(key)
    parent = _record_path(folder, "journey")
    if not parent.is_dir():
        return None
    directory = next((child.name for child in parent.iterdir() if child.name == expected), None)
    if directory is None:
        return None
    data = _read(folder, f"journey/{directory}/journey.json")
    if data is None:
        return None
    journey = StoredJourney.model_validate_json(data, strict=True)
    if (journey.iteration, journey.name, journey.code_sha256) != key:
        raise ValueError("Published journey belongs to a different idea.")
    return directory, journey


def read_journey(
    root: Path, ledger: Path, run_id: str, idea_id: str
) -> StoredJourney | JourneyMissing:
    folder, _ = _selected_run(root, run_id)
    published = _published_journey(folder, idea_id)
    if published:
        return published[1]
    idea = next((i for i in read_run(root, ledger, run_id).journeys if i.id == idea_id), None)
    if idea is None:
        raise FileNotFoundError("Unknown recorded idea.")
    args = ["uv", "run", "alpha", "ledger", "journey", "--run-dir", str(folder.absolute())]
    if idea.iteration is not None:
        args.extend(["--factor", idea.name])
    return JourneyMissing(reason="Journey not built yet", command=shlex.join(args))


def read_journey_figure(root: Path, run_id: str, idea_id: str, filename: str) -> bytes:
    folder, _ = _selected_run(root, run_id)
    published = _published_journey(folder, idea_id)
    if not published or Path(filename).name != filename or not filename.endswith(".png"):
        raise FileNotFoundError("Unknown journey figure.")
    directory, journey = published
    files = {figure.file for figure in journey.figures.values()}
    if filename not in files and filename not in {step.figure for step in journey.steps}:
        raise FileNotFoundError("Unlisted journey figure.")
    data = _read(folder, f"journey/{directory}/{filename}")
    if data is None:
        raise FileNotFoundError("Missing journey figure.")
    if not data.startswith(b"\x89PNG\r\n\x1a\n"):
        raise ValueError("Invalid recorded PNG.")
    return data
