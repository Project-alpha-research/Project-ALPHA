"""The run story: one idea card per recorded trial, task or loop event, and the stage counts.

Moved from _rdagent_runs.py without a change in behaviour.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from alpha_web._rdagent_run_factor import _factor
from alpha_web._rdagent_run_files import _object, _read, _stamp, counted, fact
from alpha_web._rdagent_run_words import REFUSED_STATUSES, status_sentence
from alpha_web.api.rdagent_models import RdAgentIdea, RdAgentStory

type IdeaKey = tuple[int, str, str]


STORY_STAGES = ("proposed", "refused", "coded", "ran", "judged", "shortlisted", "candidate")
STORY_REFUSALS = REFUSED_STATUSES | {"refused_missing_declaration"}
STORY_FIELDS = (
    "schema",
    "iteration",
    "loop",
    "attempt",
    "name",
    "description",
    "code_sha256",
    "status",
    "reason",
    "message",
    "trial_created",
    "factor_names",
    "refused_families",
    "all_closed_families",
    "closed_families",
    "declared_direction",
    "primary_clock",
    "direction_reason",
    "failure_reason",
    "failure_detail",
    "shortlist",
    "composite_suspect",
    "eligibility",
    "idea_families",
    "trial_index",
    "stage",
)


def _story_key(row: dict[str, Any]) -> IdeaKey | None:
    iteration, name, digest = (row.get(key) for key in ("iteration", "name", "code_sha256"))
    if iteration is None or name is None or digest is None:
        return None
    if type(iteration) is not int or not isinstance(name, str) or not isinstance(digest, str):
        raise ValueError("Invalid recorded idea identity.")
    if not re.fullmatch(r"[a-f0-9]{64}", digest):
        raise ValueError("Invalid recorded idea code hash.")
    return iteration, name, digest


def _story_raw(row: dict[str, Any]) -> str:
    # Keep the existing closed projection: never return environments, prompts or paths.
    return json.dumps(
        {key: fact(row[key]).value for key in STORY_FIELDS if key in row},
        ensure_ascii=False,
        indent=2,
    )


BEFORE_SHORTLIST = frozenset(
    {"SCREEN_FAIL", "SPREAD_FAIL", "REPLAY_FAIL", "FAILED", "LOOKAHEAD", "UNSTABLE", "DEGENERATE"}
)


def _shortlisted(row: dict[str, Any]) -> bool | None:
    """The stored flag; else False only for a status the writer gives before the shortlist step."""
    if type(row.get("shortlist")) is bool:
        return bool(row["shortlist"])
    return False if row.get("status") in BEFORE_SHORTLIST else None


def _idea(
    identity: str,
    row: dict[str, Any],
    trial: dict[str, Any] | None = None,
    round_row: dict[str, Any] | None = None,
) -> RdAgentIdea:
    source = trial or row
    status = row.get("status") if trial is None else None
    if status:
        status_sentence(status, None)  # unknown stored states fail loud
    refused = status in STORY_REFUSALS
    stopped = (
        trial is None
        and row.get("trial_created") is False
        and row.get("coding_status") is None
        and str(status).startswith(("coding_failed_provider_", "proposal_failed_provider_"))
    )
    open_end = not (refused or stopped)  # only these stored states prove nothing was coded
    factor = _factor(trial) if trial is not None else None
    evaluated = factor is not None and factor.status not in {"IMPORTED", "REPEAT", "FAILED"}
    ran = evaluated or source.get("failure_reason") == "critic_rejected"
    feedback = _object((round_row or {}).get("feedback") or {})
    words = [
        feedback[key]
        for key in ("observations", "hypothesis_evaluation", "new_hypothesis", "reason")
        if feedback.get(key)
    ]
    if any(not isinstance(word, str) for word in words):
        raise ValueError("Invalid recorded feedback text.")
    labels = []
    for key in ("shortlist", "composite_suspect"):
        if source.get(key) is True:
            labels.append(key)
    if source.get("eligibility"):
        labels.append(str(source["eligibility"]))
    if source.get("label"):
        labels.append(str(source["label"]))
    if source.get("diagnostics"):
        labels.append("diagnostic clocks")
    if factor is not None:
        statuses = ["coded"] if ran else [source.get("failure_reason") or factor.status]
    else:
        statuses = [status] if status else []
    stages: dict[str, bool | None] = {
        "proposed": True,
        "refused": refused,
        "coded": True
        if ran or row.get("coding_status") == "coded"
        else None
        if open_end
        else False,
        "ran": True if ran else None if open_end else False,
        "judged": evaluated
        if trial is not None
        else False
        if refused or row.get("trial_created") is False
        else None,
        "shortlisted": _shortlisted(source) if trial is not None else False if refused else None,
        "candidate": factor.status == "CANDIDATE" if factor else False if refused else None,
    }
    return RdAgentIdea(
        id=identity,
        round=fact(source.get("iteration", source.get("loop"))),
        round_kind="evaluation" if trial is not None or round_row is not None else "loop",
        name=fact(row.get("name", source.get("name"))),
        description=fact(row.get("description", source.get("description"))),
        direction=fact(source.get("declared_direction")),
        clock=fact(source.get("primary_clock")),
        reason=fact(source.get("direction_reason")),
        system_statuses=statuses,
        refusal=fact(row.get("message") if refused else None),
        feedback=fact(" ".join(words) if words else None),
        feedback_scope="round" if words else "unknown",
        trial=factor,
        stages=stages,
        labels=labels,
        code_file=fact(None),
        raw=_story_raw(source),
    )


def _story_trials(
    ledger_rows: list[dict[str, Any]],
    evaluations: list[dict[str, Any]],
    run_ids: set[str],
) -> list[dict[str, Any]]:
    rows = list(ledger_rows)
    seen = {_story_key(row): row for row in rows if _story_key(row) is not None}
    if len(seen) != sum(_story_key(row) is not None for row in rows):
        raise ValueError("Duplicate recorded idea identity.")
    for evaluation in evaluations:
        for value in evaluation.get("factors", []):
            row = _object(value)
            if row.get("run_id") is not None and row["run_id"] not in run_ids:
                raise ValueError("Recorded evaluation belongs to a different run.")
            row = {"iteration": evaluation.get("iteration"), **row}
            key = _story_key(row)
            if key is None:
                rows.append(row)  # Keep it separate; its missing link must remain unknown.
                continue
            if row.get("iteration") != evaluation.get("iteration"):
                raise ValueError("Recorded evaluation and trial identifiers disagree.")
            previous = seen.get(key)
            if previous is not None:
                if previous != row:
                    raise ValueError("Recorded evaluation and ledger trial disagree.")
            else:
                rows.append(row)
                seen[key] = row
    return rows


def _story_tasks(
    rounds: list[dict[str, Any]],
) -> dict[tuple[int, str, str], tuple[dict[str, Any], dict[str, Any]]]:
    tasks = {}
    for record in rounds:
        for value in record.get("tasks", []):
            task = _object(value)
            key = _story_key({**task, "iteration": record.get("iteration")})
            if key is not None:
                if key in tasks:
                    raise ValueError("Duplicate recorded round task identity.")
                tasks[key] = (task, record)
    return tasks


def _story_ending(receipt: dict[str, Any]) -> str:
    reason = str(receipt.get("loop_reason", "")).lower()
    if any(
        word in reason
        for word in ("budget_exhausted", "budget exhausted", "cap", "wall-clock limit")
    ):
        return "budget"
    if "internal coding error" in reason:
        return "internal_error"
    if receipt.get("exit_status") == 0:
        return "finished"
    if any(word in reason for word in ("provider_timeout", "provider_error", "provider timeout")):
        return "provider"
    return "error" if receipt.get("exit_status") is not None else "not_recorded"


def _story(
    folder: Path,
    receipt: dict[str, Any],
    ledger_rows: list[dict[str, Any]],
    rounds: list[dict[str, Any]],
    evaluations: list[dict[str, Any]],
) -> tuple[RdAgentStory, dict[str, IdeaKey]]:
    tasks = _story_tasks(rounds)
    identities: dict[str, IdeaKey] = {}
    ideas = []
    missing = []
    events = []
    uncertain = bool(ledger_rows) and any(
        _story_key(row) is None
        for evaluation in evaluations
        for row in evaluation.get("factors", [])
    )
    if uncertain:
        missing.append(
            "An evaluation has no stored identity linking it to the ledger; counts are unknown."
        )
    trials = _story_trials(ledger_rows, evaluations, {receipt["run_id"], folder.name})
    for index, trial in enumerate(trials):
        if trial.get("status") == "IMPORTED":
            continue
        key = _story_key(trial)
        task, record = tasks.pop(key, ({}, {})) if key else ({}, {})
        idea = _idea(f"trial-{index}", task, trial, record)
        if key:
            identities[idea.id] = key
        digest = trial.get("code_sha256")
        if key and _read(folder, f"code/{digest}.py") is not None:
            idea.code_file = fact(f"{digest}.py")
            idea.stages["coded"] = True
        if idea.round.value is None:
            idea.round_kind = "unknown"
        if not record:
            missing.append("The trial's link to recorded proposer feedback is not recorded.")
        ideas.append(idea)
    for key, (task, record) in tasks.items():
        idea = _idea(f"task-{len(ideas)}", {**task, "iteration": key[0]}, round_row=record)
        ideas.append(idea)
        identities[idea.id] = key
        uncertain = True
        missing.append("A task's link to its trial is not recorded.")
    for index, record in enumerate(rounds):
        if record.get("tasks") is not None:
            for position, task in enumerate(record["tasks"]):
                entry = {**_object(task), "iteration": record.get("iteration")}
                if _story_key(entry) is None:
                    ideas.append(
                        _idea(f"unlinked-task-{index}-{position}", entry, round_row=record)
                    )
                    uncertain = True
                    missing.append("A task has no stored identifier linking it to a trial.")
            continue
        if record.get("status"):
            status_sentence(record["status"], None)
            events.append(record["status"])
        names = record.get("factor_names", [])
        if not isinstance(names, list) or any(not isinstance(name, str) for name in names):
            raise ValueError("Invalid recorded proposal names.")
        if not names and record.get("trial_created") is False and record.get("status"):
            missing.append(
                "A round ended before any idea of it was recorded; ideas it may have "
                "proposed are not counted."
            )
        elif not names:
            missing.append("An event has no recorded idea names; its idea count is not recorded.")
            uncertain = True
        if record.get("trial_created") is not False and names:
            uncertain = True
            missing.append(
                "Loop event to evaluation/trial link is not recorded; "
                "these cards may describe the same idea."
            )
        per_factor = {row["name"]: row for row in record.get("factors", [])}
        for position, name in enumerate(names):
            entry = {**record, "name": name}
            if name in per_factor:
                entry["trial_created"] = per_factor[name].get("trial_created")
                entry["coding_status"] = per_factor[name].get("status")
            ideas.append(_idea(f"event-{index}-{position}", entry))
    if rounds:
        missing.append(
            "Evaluation numbers and loop round numbers have no stored link "
            "and are grouped separately."
        )
    present = bool(ideas or rounds or evaluations)
    no_trials = (
        bool(rounds)
        and not evaluations
        and not any(idea.trial is not None for idea in ideas)
        and all(row.get("trial_created") is False for row in rounds)
    )
    journey = {}
    for stage in STORY_STAGES:
        known = present and not uncertain and all(idea.stages[stage] is not None for idea in ideas)
        known = known or no_trials and stage in {"judged", "shortlisted", "candidate"}
        journey[stage] = (
            counted(
                sum(idea.stages[stage] is True for idea in ideas), "counted from linked idea cards"
            )
            if known
            else fact(None)
        )
    start, end = receipt.get("started_at"), receipt.get("ended_at")
    minutes = (
        counted((_stamp(end) - _stamp(start)).total_seconds() / 60, "recorded end minus start")
        if start and end
        else fact(None)
    )
    if isinstance(minutes.value, (int, float)) and minutes.value < 0:
        raise ValueError("Recorded run ends before it starts.")
    story = RdAgentStory(
        events=list(dict.fromkeys(events)),
        ideas=ideas,
        journey=journey,
        missing_links=list(dict.fromkeys(missing)),
        ending=_story_ending(receipt),
        ending_reason=fact(receipt.get("loop_reason")),
        minutes=minutes,
    )
    return story, identities
