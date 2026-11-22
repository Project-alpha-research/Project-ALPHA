"""The resumable bench run: send stored prompts to models, keep every output, honour the caps."""

from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from alpha_cli.rdagent_bench_model import (
    MONTH_MAX_USD,
    RUN_MAX_USD,
    BenchError,
    Client,
    Reply,
    RunResult,
    StoredPrompt,
    check_outside_git,
    make_plan,
    month_spent,
    output_path,
    prompt_sha,
)


def _record(
    model: str,
    p: StoredPrompt,
    sample: int,
    reply: Reply,
    price: tuple[float, float],
    estimate: float,
) -> dict[str, Any]:
    usd: float | None = None
    reason = None
    source = None
    if reply.cost is not None:
        usd, source = float(reply.cost), "reported by the gateway"
    elif reply.prompt_tokens is None or reply.completion_tokens is None:
        reason = "the model did not report token counts"
    else:
        usd = (reply.prompt_tokens * price[0] + reply.completion_tokens * price[1]) / 1e6
        source = "estimated from token counts and your prices"
    return {
        "schema": "AlphaBenchOutputV1",
        "model": model,
        "prompt_id": p.id,
        "stage": p.stage,
        "prompt_sha256": prompt_sha(p),
        "charged_usd": usd if usd is not None else estimate,
        "sample": sample,
        "text": reply.text,
        "provider": reply.provider,
        "provider_reason": None if reply.provider else "the call did not report its provider",
        "prompt_tokens": reply.prompt_tokens,
        "completion_tokens": reply.completion_tokens,
        "usd": usd,
        "usd_reason": reason,
        "usd_source": source,
        "latency_ms": reply.latency_ms,
        "latency_reason": None
        if reply.latency_ms is not None
        else "the call did not report latency",
    }


def _estimate(p: StoredPrompt, price: tuple[float, float]) -> float:
    return ((p.prompt_tokens or 0) * price[0] + (p.completion_tokens or 0) * price[1]) / 1e6


def _charge(spend: Path, now: datetime, record: dict[str, Any]) -> float:
    """Write the spend of one call. A call without token counts is charged its estimate."""
    spend.parent.mkdir(parents=True, exist_ok=True)
    with spend.open("a", encoding="utf-8") as stream:
        row = {
            "ts": now.isoformat(),
            "usd": record["charged_usd"],
            "estimated": record["usd_source"] != "reported by the gateway",
        }
        stream.write(json.dumps(row) + "\n")
    return float(record["charged_usd"])


def _stored(
    prompts: list[StoredPrompt], models: list[str], samples: int, store: Path
) -> tuple[set[tuple[str, str, int]], float]:
    """The outputs already stored and what they cost. A stored output made from a different
    prompt text is refused: the same id must mean the same prompt."""
    done: set[tuple[str, str, int]] = set()
    spent = 0.0
    for model in models:
        for p in prompts:
            for sample in range(samples):
                path = output_path(store, model, p.id, sample)
                if not path.exists():
                    continue
                record = json.loads(path.read_text(encoding="utf-8"))
                if record.get("prompt_sha256") != prompt_sha(p):
                    raise BenchError(
                        f"Prompt '{p.id}' changed since its output was stored for {model}. "
                        "Use a new id or a new store."
                    )
                done.add((model, p.id, sample))
                spent += float(record["charged_usd"])
    return done, spent


def run_bench(
    prompts: list[StoredPrompt],
    models: list[str],
    samples: int,
    prices: Mapping[str, tuple[float, float]],
    client: Client,
    store: Path,
    *,
    spend: Path,
    max_new_calls: int | None = None,
) -> RunResult:
    """Send each stored prompt to each model `samples` times. An output already stored is kept.

    The plan is checked first. Then, before each call, the spend so far plus that call's
    estimate must stay within the run cap and the month cap: a model that writes more than the
    recorded counts stops the run, and the outputs stored so far are kept for a resume.
    """
    check_outside_git(store)
    now = datetime.now(UTC)
    month = month_spent(spend, now)
    done, run_usd = _stored(prompts, models, samples, store)
    make_plan(prompts, models, samples, prices, month, done)
    new, new_usd = 0, 0.0
    for model in models:
        for p in prompts:
            for sample in range(samples):
                path = output_path(store, model, p.id, sample)
                if (model, p.id, sample) in done:
                    continue
                if max_new_calls is not None and new >= max_new_calls:
                    return RunResult(new_calls=new, finished=False)
                estimate = _estimate(p, prices[model])
                if run_usd + estimate > RUN_MAX_USD or month + new_usd + estimate > MONTH_MAX_USD:
                    raise BenchError(
                        f"Stopped after {new} new calls: {run_usd:.2f} USD spent in this run and "
                        f"{month + new_usd:.2f} USD this month. The next call would pass the cap "
                        f"of {RUN_MAX_USD:g} USD per run or {MONTH_MAX_USD:g} USD per month. "
                        "The stored outputs are kept."
                    )
                record = _record(
                    model, p, sample, client.complete(model, p, sample), prices[model], estimate
                )
                path.parent.mkdir(parents=True, exist_ok=True)
                with path.open("x", encoding="utf-8") as stream:
                    stream.write(json.dumps(record, sort_keys=True, allow_nan=False) + "\n")
                charged = _charge(spend, now, record)
                run_usd += charged
                new_usd += charged
                new += 1
    return RunResult(new_calls=new, finished=True)
