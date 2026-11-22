"""The replay bench: stored prompts, the plan with its caps, the clients and the resumable run.

The bench sends stored prompts to candidate models and stores every output. It takes no ledger and
no memory folder, so it cannot write to either. The caps are the owner's and are never raised.
"""

from __future__ import annotations

import hashlib
import json
import math
import tomllib
import urllib.parse
from collections.abc import Collection, Mapping
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Protocol

RUN_MAX_CALLS = 60
RUN_MAX_USD = 10.0
MONTH_MAX_USD = 50.0
TOKEN_VARIABLE = "ALPHA_BENCH_GATEWAY_TOKEN"
LOCAL_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})


class BenchError(Exception):
    """A refusal in plain words."""


@dataclass(frozen=True)
class StoredPrompt:
    id: str
    stage: str
    messages: list[dict[str, Any]]
    prompt_tokens: int | None
    completion_tokens: int | None


@dataclass(frozen=True)
class Reply:
    text: str
    provider: str | None
    prompt_tokens: int | None
    completion_tokens: int | None
    latency_ms: float | None
    cost: float | None = None


@dataclass(frozen=True)
class Plan:
    calls: int
    usd: float
    per_model: dict[str, tuple[int, float]]


@dataclass
class RunResult:
    new_calls: int
    finished: bool


class Client(Protocol):
    def complete(self, model: str, prompt: StoredPrompt, sample: int) -> Reply: ...


def _count(value: object, where: str) -> int | None:
    if value is None:
        return None
    if type(value) is not int or value < 0:
        raise BenchError(f"{where}: a token count must be a whole number of zero or more.")
    return value


def load_prompts(folder: Path, stages: list[str] | None) -> list[StoredPrompt]:
    if not folder.is_dir():
        raise BenchError(f"The prompt folder does not exist: {folder}")
    found: list[StoredPrompt] = []
    for path in sorted(folder.glob("*.json")):
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            prompt = StoredPrompt(
                id=str(raw["id"]),
                stage=str(raw["stage"]),
                messages=list(raw["messages"]),
                prompt_tokens=_count(raw.get("prompt_tokens"), path.name),
                completion_tokens=_count(raw.get("completion_tokens"), path.name),
            )
        except (OSError, ValueError, KeyError, TypeError) as error:
            raise BenchError(f"{path.name} is not a stored prompt: {error!r}") from error
        if "/" in prompt.id or not prompt.id:
            raise BenchError(f"{path.name}: the id must be a plain name.")
        if stages is None or prompt.stage in stages:
            found.append(prompt)
    if len({p.id for p in found}) != len(found):
        raise BenchError("Two stored prompts share one id.")
    if not found:
        raise BenchError("No stored prompt matches. Nothing to do.")
    return found


def load_prices(path: Path, models: list[str]) -> dict[str, tuple[float, float]]:
    """Dollars per million tokens, in and out, for every candidate. A missing price is a refusal."""
    try:
        raw = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as error:
        raise BenchError(f"The price file cannot be read: {error}") from error
    prices: dict[str, tuple[float, float]] = {}
    for model in models:
        entry = raw.get(model)
        if not isinstance(entry, dict):
            raise BenchError(f"There is no price for model '{model}' in {path}.")
        try:
            price = (float(entry["in_per_mtok"]), float(entry["out_per_mtok"]))
        except (KeyError, TypeError, ValueError) as error:
            raise BenchError(
                f"The price for '{model}' needs in_per_mtok and out_per_mtok."
            ) from error
        if not all(math.isfinite(v) and v >= 0 for v in price):
            raise BenchError(f"The price for '{model}' must be finite and not negative.")
        prices[model] = price
    return prices


def make_plan(
    prompts: list[StoredPrompt],
    models: list[str],
    samples: int,
    prices: Mapping[str, tuple[float, float]],
    month_spent: float,
    done: Collection[tuple[str, str, int]] = (),
) -> Plan:
    """The calls and cost of a plan. Outputs in `done` are already paid for and in the month's
    spend, so only the calls still missing count against the month cap."""
    if samples < 1 or not models:
        raise BenchError("Give at least one model and one sample.")
    if len(set(models)) != len(models):
        raise BenchError("A model name is given twice. Give each model once.")
    per_model: dict[str, tuple[int, float]] = {}
    missing_usd = 0.0
    for model in models:
        usd = 0.0
        for p in prompts:
            if p.prompt_tokens is None or p.completion_tokens is None:
                raise BenchError(
                    f"Prompt '{p.id}' has no recorded token counts; the cost is unknown."
                )
            price_in, price_out = prices[model]
            each = (p.prompt_tokens * price_in + p.completion_tokens * price_out) / 1e6
            usd += samples * each
            missing_usd += each * sum((model, p.id, n) not in done for n in range(samples))
        per_model[model] = (samples * len(prompts), usd)
    calls = sum(c for c, _ in per_model.values())
    usd = sum(u for _, u in per_model.values())
    if calls > RUN_MAX_CALLS:
        raise BenchError(f"The plan has {calls} calls. The cap is {RUN_MAX_CALLS} per run.")
    if usd > RUN_MAX_USD:
        raise BenchError(f"The plan costs about {usd:.2f} USD. The cap is {RUN_MAX_USD:g} per run.")
    if month_spent + missing_usd > MONTH_MAX_USD:
        raise BenchError(
            f"The calls still to make plus {month_spent:.2f} USD already spent this month pass "
            f"the {MONTH_MAX_USD:g} USD monthly cap."
        )
    return Plan(calls=calls, usd=usd, per_model=per_model)


def check_outside_git(path: Path) -> None:
    probe = path.resolve()
    if any((p / ".git").exists() for p in (probe, *probe.parents)):
        raise BenchError("The bench store must be outside every git work tree.")


def spend_ledger(data_dir: Path) -> Path:
    """The one month ledger of bench spend. It is fixed under the data home, so a new output
    folder cannot start the month again."""
    return data_dir / "rdagent-bench" / "spend.jsonl"


def month_spent(spend: Path, now: datetime) -> float:
    if not spend.exists():
        return 0.0
    stem = f"{now:%Y-%m}"
    rows = [json.loads(line) for line in spend.read_text().splitlines() if line.strip()]
    return sum(float(r["usd"]) for r in rows if r["ts"].startswith(stem))


def prompt_sha(p: StoredPrompt) -> str:
    body = json.dumps({"stage": p.stage, "messages": p.messages}, sort_keys=True)
    return hashlib.sha256(body.encode()).hexdigest()


def output_path(store: Path, model: str, prompt_id: str, sample: int) -> Path:
    return store / "outputs" / urllib.parse.quote(model, safe="") / f"{prompt_id}.{sample}.json"
