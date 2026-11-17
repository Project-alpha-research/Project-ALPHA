"""Observed chat usage only: no pricing, reservations or routing preferences."""

from __future__ import annotations

import math
from collections import Counter
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .model_gateway import ChatResult

TOKEN_FIELDS = ("prompt_tokens", "cached_tokens", "completion_tokens", "reasoning_tokens")
EXTRA_FIELDS = ("provider", "id", "cache_write_tokens", "cache_discount", "charged_usd")


def response_facts(response: dict[str, Any]) -> dict[str, Any]:
    """Read only the documented response locations; missing values stay null."""
    usage = response["usage"]
    prompt = usage.get("prompt_tokens_details")
    completion = usage.get("completion_tokens_details")
    prompt = {} if prompt is None else prompt
    completion = {} if completion is None else completion
    if not isinstance(prompt, dict) or not isinstance(completion, dict):
        raise ValueError("invalid token details")
    facts = {
        "provider": response.get("provider"),
        "id": response.get("id"),
        "cached_tokens": prompt.get("cached_tokens"),
        "cache_write_tokens": prompt.get("cache_write_tokens"),
        "reasoning_tokens": completion.get("reasoning_tokens"),
        "cache_discount": usage.get("cache_discount"),
        "charged_usd": usage.get("cost"),
    }
    for field, value in facts.items():
        if value is None:
            continue
        if field in ("provider", "id"):
            valid = isinstance(value, str) and bool(value)
        elif field in ("cache_discount", "charged_usd"):
            valid = type(value) in (int, float) and math.isfinite(value) and value >= 0
        else:
            valid = type(value) is int and value >= 0
        if not valid:
            raise ValueError(f"invalid {field}")
    return facts


def record_defaults() -> dict[str, Any]:
    return {
        **dict.fromkeys(EXTRA_FIELDS),
        "usage_known": False,
        "attempt_usage": [],
        "router_session_sent": False,
    }


def record_attempt(
    row: dict[str, Any], result: ChatResult | None = None, *, error: str | None = None
) -> None:
    """Keep each attempt, including unknown usage, inside the existing request row."""
    fields = (*TOKEN_FIELDS, *EXTRA_FIELDS)
    attempt = {field: getattr(result, field) if result is not None else None for field in fields}
    attempt.update(
        usage_known=result is not None
        and result.prompt_tokens is not None
        and result.completion_tokens is not None,
        error_code=error,
        router_session_sent=row["router_session_sent"],
    )
    row["attempt_usage"].append(attempt)
    row["usage_known"] = all(item["usage_known"] for item in row["attempt_usage"])
    for field in EXTRA_FIELDS:
        values = [item[field] for item in row["attempt_usage"]]
        known = [value for value in values if value is not None]
        if field in ("provider", "id"):
            row[field] = (
                known[0] if known and len(known) == len(values) and len(set(known)) == 1 else None
            )
        else:
            row[field] = sum(known) if known else None


def chat_usage(calls: list[dict[str, Any]]) -> dict[str, Any]:
    """Totals of reported tokens; a rate requires complete cache and prompt observations."""
    attempts = [
        attempt
        for call in calls
        if call.get("endpoint") == "/v1/chat/completions"
        for attempt in call.get("attempt_usage", [call])
    ]
    totals: dict[str, Any] = {}
    for field in TOKEN_FIELDS:
        values = [a[field] for a in attempts if a.get(field) is not None]
        totals[field] = sum(values) if values else None
    complete = bool(attempts) and all(
        a.get("prompt_tokens") is not None and a.get("cached_tokens") is not None for a in attempts
    )
    rate = (
        totals["cached_tokens"] / totals["prompt_tokens"]
        if complete and totals["prompt_tokens"]
        else None
    )
    providers = Counter(a["provider"] for a in attempts if a.get("provider") is not None)
    sessions = [a.get("router_session_sent") for a in attempts]
    sent = (
        True
        if any(s is True for s in sessions)
        else (False if sessions and all(s is False for s in sessions) else None)
    )
    prefix = (
        f"{rate * 100:g}% of prompt tokens were served from cache"
        if rate is not None
        else ("Prompt-cache hit rate is unknown")
    )
    unknown = sum(a.get("provider") is None for a in attempts)
    provider_summary = (
        f"calls were served by {len(providers)} provider(s)"
        if not unknown
        else (
            f"{len(providers)} provider(s) were identified and "
            f"{unknown} call(s) have unknown providers"
        )
    )
    totals.update(
        cache_hit_rate=rate,
        provider_calls=dict(sorted(providers.items())),
        distinct_providers=len(providers),
        unknown_provider_calls=unknown,
        router_session_sent=sent,
        summary=f"{prefix}; {provider_summary}.",
    )
    return totals


def receipt_usage(
    calls: list[dict[str, Any]], labelled: list[dict[str, Any]] | None = None
) -> dict[str, Any]:
    result = chat_usage(calls)
    groups: dict[str, list[dict[str, Any]]] = {}
    for call in labelled or []:
        step = call.get("step")
        if call.get("endpoint") == "/v1/chat/completions" and step and step != "outside-step":
            groups.setdefault(step, []).append(call)
    if groups:
        result["by_step"] = {step: chat_usage(group) for step, group in sorted(groups.items())}
    return result
