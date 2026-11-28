"""Call accounting of the ALPHA-judged factor loop: step labels, round counts and the call split.

Standard library only. ``factor_loop_launch.py`` writes these into the run's receipt.
"""

from __future__ import annotations

import importlib
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from . import gateway_usage
else:
    _WORKER = str(Path(__file__).resolve().parent)
    if _WORKER not in sys.path:
        sys.path.insert(0, _WORKER)
    gateway_usage = importlib.import_module("gateway_usage")


def label_calls(calls: list[dict[str, Any]], steps: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Copy calls with the latest-starting completed step that contains each timestamp."""
    active: dict[tuple[int, int, str], list[dict[str, Any]]] = {}
    intervals = []
    for row in steps:
        key = (row["loop"], row["step_index"], row["step"])
        if row["event"] == "start":
            active.setdefault(key, []).append(row)
        elif row["event"] == "end" and active.get(key):
            start = active[key].pop()
            intervals.append(
                (datetime.fromisoformat(start["ts"]), datetime.fromisoformat(row["ts"]), start)
            )
    labelled = []
    for call in calls:
        ts = datetime.fromisoformat(call["ts"])
        matching = [(start, row) for start, end, row in intervals if start <= ts <= end]
        step = max(matching, key=lambda item: item[0])[1] if matching else None
        labelled.append(
            {
                **call,
                "schema": "AlphaRdagentCallLabelV1",
                "loop": step["loop"] if step else None,
                "step": step["step"] if step else "outside-step",
            }
        )
    return labelled


def round_counts(run: Path) -> dict[str, int | float]:
    rounds_path, evaluations = run / "rounds.jsonl", run / "evaluations.jsonl"
    rounds = (
        [json.loads(line) for line in rounds_path.read_text().splitlines()]
        if rounds_path.exists()
        else []
    )
    evaluated = (
        [json.loads(line) for line in evaluations.read_text().splitlines()]
        if evaluations.exists()
        else []
    )
    refused = [
        row
        for row in rounds
        if row.get("refused_families", row.get("closed_families"))
        or row.get("reason") == "refused_closed_family"
    ]
    return {
        "rounds_with_trial": len({row["iteration"] for row in evaluated if row.get("factors")}),
        "rounds_no_admissible_idea": sum(
            row.get("status") == "no_admissible_idea" for row in rounds
        ),
        "proposals_refused": len(refused),
        "rounds_failed_provider": len(
            {
                r["iteration"]
                for r in rounds
                if str(r.get("status", "")).startswith(
                    ("coding_failed_provider_", "proposal_failed_provider_")
                )
            }
        ),
        "provider_failed_wait_seconds": sum(
            float(r.get("provider_wait_seconds", 0)) for r in rounds
        ),
    }


def call_split(
    calls: list[dict[str, Any]], labelled: list[dict[str, Any]] | None = None
) -> dict[str, Any]:
    """Model calls versus free local embeddings, as the gateway logged them.

    Only embedding rows the gateway marked ``local_embedding`` or ``provider_embedding`` are exempt
    (owner decision 2026-11-17); old logs without the mark stay counted as they were.
    """
    split: dict[str, Any] = {
        "model_chat": {"requests": 0, "attempts": 0, "usd": 0.0},
        "local_embedding": {"requests": 0, "attempts": 0, "usd": 0.0},
        "provider_embedding": {"requests": 0, "attempts": 0, "usd": 0.0},
        "counted_calls": 0,
        "local_embedding_calls": 0,
        "provider_embedding_calls": 0,
        "provider_embedding_requests": 0,
        "provider_embedding_inputs": 0,
        "embedding_single_retries": 0,
        "embedding_model_not_reported": 0,
        "provider_embedding_usd": 0.0,
        "provider_embedding_tokens": 0,
        "provider_timeouts": 0,
        "empty_or_invalid_replies": 0,
        "retried_attempts": 0,
        "timeout_retry_attempts": 0,
        "failed_requests": {},
        "chunked_embedding_inputs": 0,
        "embedding_chunks": 0,
        "embedding_cache_hits": 0,
        "embedding_requests": 0,
        "embedding_inputs_sent": 0,
        "provider_call_seconds_with_retries": 0.0,
    }
    routes: set[str] = set()
    models: set[str] = set()
    for call in calls:
        split["embedding_cache_hits"] += int(call.get("embedding_cache_hits", 0))
        if call.get("cache_only"):
            continue
        if call.get("endpoint") == "/v1/chat/completions" and call.get("provider_errors"):
            split["provider_call_seconds_with_retries"] += float(call.get("latency_ms", 0)) / 1000
        if call.get("endpoint") == "/v1/embeddings":
            split["embedding_requests"] += int(call.get("attempts", 0))
            split["embedding_inputs_sent"] += int(call.get("embedding_inputs_sent", 0))
            if isinstance(call.get("route"), str):
                routes.add(call["route"])
            if isinstance(call.get("model_used"), str):
                models.add(call["model_used"])
        kind = "model_chat" if call.get("endpoint") == "/v1/chat/completions" else "local_embedding"
        if kind == "local_embedding" and call.get("local_embedding") is False:
            kind = "provider_embedding"
        split[kind]["requests"] += 1
        split[kind]["attempts"] += int(call.get("attempts") or 0)
        split[kind]["usd"] += float(call.get("usd") or 0.0)
        split["chunked_embedding_inputs"] += int(call.get("chunked_inputs") or 0)
        split["embedding_chunks"] += int(call.get("chunks") or 0)
        errors = call.get("provider_errors") or []
        split["provider_timeouts"] += errors.count("provider_timeout")
        split["empty_or_invalid_replies"] += errors.count("invalid_provider_response")
        attempts = int(call.get("attempts") or 0)
        local = kind == "local_embedding" and call.get("local_embedding") is True
        provider = kind == "provider_embedding" and call.get("provider_embedding") is True
        bucket = (
            "local_embedding_calls"
            if local
            else "provider_embedding_calls"
            if provider
            else "counted_calls"
        )
        split[bucket] += attempts
        if provider:
            split["provider_embedding_requests"] += attempts
            split["provider_embedding_inputs"] += (
                int(call.get("input_count") or 0) if not call.get("single_retry") else 0
            )
            split["embedding_single_retries"] += int(bool(call.get("single_retry"))) * attempts
            split["embedding_model_not_reported"] += int(
                call.get("model_check") == "model_not_reported"
            )
            split["provider_embedding_usd"] += float(call.get("usd") or 0)
            split["provider_embedding_tokens"] += int(call.get("prompt_tokens") or 0)
        split["retried_attempts"] += max(0, attempts - 1)
        split["timeout_retry_attempts"] += int(
            call.get(
                "timeout_retry_attempts", errors[: max(0, attempts - 1)].count("provider_timeout")
            )
        )
        if call.get("status") != 200:
            code = str(call.get("error_code"))
            split["failed_requests"][code] = split["failed_requests"].get(code, 0) + 1
    split.update(
        embedding_route=next(iter(routes)) if len(routes) == 1 else None,
        embedding_model=next(iter(models)) if len(models) == 1 else None,
        embedding_routes=sorted(routes),
        embedding_models=sorted(models),
    )
    reasks = [
        c
        for c in labelled or []
        if c.get("step") == "proposal_reask" and c.get("endpoint") == "/v1/chat/completions"
    ]
    split["proposal_prompt_chars"] = [
        {"loop": c.get("loop"), "step": c["step"], "chars": c["total_prompt_chars"]}
        for c in labelled or []
        if c.get("step") in ("direct_exp_gen", "proposal_reask", "discussion_revision")
        and c.get("endpoint") == "/v1/chat/completions"
        and "total_prompt_chars" in c
    ]
    split["reask_calls"] = sum(int(c.get("attempts") or 0) for c in reasks)
    split["reask_usd"] = sum(float(c.get("usd") or 0) for c in reasks)
    split["chat_usage"] = gateway_usage.receipt_usage(calls, labelled)
    split["counted_toward_call_cap"] = split["counted_calls"]
    return split
