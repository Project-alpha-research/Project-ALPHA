"""The resumable bench run: send stored prompts to models, keep every output, honour the caps."""

from __future__ import annotations

import fcntl
import json
import math
from collections.abc import Callable, Mapping
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

UNSETTLED = "unsettled-spend.jsonl"


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


def _append(spend: Path, now: datetime, usd: float, estimated: bool) -> None:
    with spend.open("a", encoding="utf-8") as stream:
        row = {"ts": now.isoformat(), "usd": usd, "estimated": estimated}
        stream.write(json.dumps(row) + "\n")


def _reserve(spend: Path, now: datetime, estimate: float) -> None:
    """Check the month cap and write the call's reservation under one lock, so two bench
    processes sharing the ledger cannot both take the last dollars."""
    spend.parent.mkdir(parents=True, exist_ok=True)
    with spend.with_suffix(".lock").open("w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        spent = month_spent(spend, now)
        if spent + estimate > MONTH_MAX_USD:
            raise BenchError(
                f"Stopped: {spent:.2f} USD is spent this month and the next call may cost "
                f"{estimate:.2f} USD. That would pass the {MONTH_MAX_USD:g} USD monthly cap."
            )
        _append(spend, now, estimate, True)


def _settle(spend: Path, now: datetime, estimate: float, record: dict[str, Any]) -> None:
    """Replace the reservation by the charge that was reported or estimated from tokens."""
    delta = float(record["charged_usd"]) - estimate
    if delta != 0:
        spend.parent.mkdir(parents=True, exist_ok=True)
        with spend.with_suffix(".lock").open("w") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            _append(spend, now, delta, record["usd_source"] != "reported by the gateway")


def _note_failed(store: Path, now: datetime, estimate: float) -> None:
    """A call that failed after dispatch may still have been billed. Its reservation stays in the
    month ledger; the store keeps it so a rerun counts it against the run's cost and call caps."""
    store.mkdir(parents=True, exist_ok=True)
    with (store / UNSETTLED).open("a", encoding="utf-8") as stream:
        stream.write(json.dumps({"ts": now.isoformat(), "usd": estimate}) + "\n")


def _unsettled(store: Path) -> tuple[float, int]:
    path = store / UNSETTLED
    if not path.exists():
        return 0.0, 0
    rows = [json.loads(x) for x in path.read_text().splitlines() if x.strip()]
    return sum(float(r["usd"]) for r in rows), len(rows)


def _stored(
    prompts: list[StoredPrompt], models: list[str], samples: int, store: Path
) -> tuple[set[tuple[str, str, int]], float, int]:
    """The outputs already stored and what they cost. A stored output made from a different
    prompt text is refused: the same id must mean the same prompt."""
    done: set[tuple[str, str, int]] = set()
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
    # Everything else already in this store counts toward the run's budget and call cap, whatever
    # models, stages or prompts this invocation selects.
    selected = len(done)
    every = [
        json.loads(p.read_text(encoding="utf-8")) for p in (store / "outputs").glob("*/*.json")
    ]
    others = len(every) - selected
    spent = sum(float(r["charged_usd"]) for r in every)
    failed_usd, failed_calls = _unsettled(store)
    return done, spent + failed_usd, failed_calls + others


def _run(
    prompts: list[StoredPrompt],
    models: list[str],
    samples: int,
    prices: Mapping[str, tuple[float, float]],
    client: Client,
    store: Path,
    *,
    spend: Path,
    max_new_calls: int | None = None,
    clock: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> RunResult:
    """The run itself, with the store's lock already held by `run_bench`."""
    month = month_spent(spend, clock())
    done, run_usd, failed = _stored(prompts, models, samples, store)
    make_plan(prompts, models, samples, prices, month, done, failed)
    new = 0
    for model in models:
        for p in prompts:
            for sample in range(samples):
                path = output_path(store, model, p.id, sample)
                if (model, p.id, sample) in done:
                    continue
                if max_new_calls is not None and new >= max_new_calls:
                    return RunResult(new_calls=new, finished=False)
                estimate = _estimate(p, prices[model])
                if run_usd + estimate > RUN_MAX_USD:
                    raise BenchError(
                        f"Stopped after {new} new calls: {run_usd:.2f} USD spent in this run. "
                        f"The next call would pass the cap of {RUN_MAX_USD:g} USD per run. "
                        "The stored outputs are kept."
                    )
                now = clock()  # each call reserves against the month it is made in
                _reserve(spend, now, estimate)
                try:
                    reply = client.complete(model, p, sample)
                except BenchError:
                    # Refused before dispatch: nothing was sent, so the reservation is released.
                    _settle(spend, now, estimate, {"charged_usd": 0.0, "usd_source": None})
                    raise
                except Exception:
                    _note_failed(store, now, estimate)
                    raise
                if reply.cost is not None and not (
                    isinstance(reply.cost, int | float)
                    and math.isfinite(reply.cost)
                    and reply.cost >= 0
                ):
                    # The call was made: charge its estimate, then stop. A bad charge never
                    # lowers the spend so far.
                    _note_failed(store, now, estimate)
                    raise BenchError(
                        f"{model} reported the cost {reply.cost!r} for prompt '{p.id}'. A cost "
                        "must be a finite number of zero or more. The run stopped; its estimate "
                        "was charged."
                    )
                record = _record(model, p, sample, reply, prices[model], estimate)
                _settle(spend, now, estimate, record)  # a billed reply is booked before it is saved
                path.parent.mkdir(parents=True, exist_ok=True)
                with path.open("x", encoding="utf-8") as stream:
                    stream.write(json.dumps(record, sort_keys=True, allow_nan=False) + "\n")
                run_usd += float(record["charged_usd"])
                new += 1
    return RunResult(new_calls=new, finished=True)


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
    clock: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> RunResult:
    """Send each stored prompt to each model `samples` times. An output already stored is kept.

    The plan is checked first. Then, before each call, the spend so far plus that call's
    estimate must stay within the run cap and the month cap: a model that writes more than the
    recorded counts stops the run, and the outputs stored so far are kept for a resume.
    One run at a time may use a store: a second one is refused before any call.
    """
    check_outside_git(store)
    store.mkdir(parents=True, exist_ok=True)
    with (store / ".run.lock").open("w") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise BenchError(
                "Another bench run is using this store. Wait for it to end."
            ) from error
        return _run(
            prompts,
            models,
            samples,
            prices,
            client,
            store,
            spend=spend,
            max_new_calls=max_new_calls,
            clock=clock,
        )
