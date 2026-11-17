"""Embedding routes and their accounting; standard library only."""

from __future__ import annotations

import hashlib
import ipaddress
import json
import math
import os
import re
import time
import urllib.parse
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Protocol

if TYPE_CHECKING:
    from .model_gateway import Budget, Gateway, Settings

EMBEDDING_CALLS_PER_RUN = 2000
EMBED_BATCH_INPUTS = 32


def digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class GatewayError(Exception):
    def __init__(
        self,
        status: int,
        code: str,
        message: str,
        param: str | None = None,
        payload: dict[str, Any] | None = None,
        tool_events: int = 0,
    ) -> None:
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message
        self.param = param
        self.payload = payload
        self.tool_events = tool_events

    def body(self) -> dict[str, Any]:
        if self.payload is not None:
            return self.payload
        return {
            "error": {
                "message": self.message,
                "type": "invalid_request_error" if self.status < 500 else "gateway_error",
                "code": self.code,
                "param": self.param,
            }
        }


def unsupported(param: str, reason: str) -> GatewayError:
    return GatewayError(400, "unsupported_parameter", f"{param}: {reason}", param)


def loopback_url(url: str) -> bool:
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme not in ("http", "https") or parsed.username or parsed.password:
        return False
    if parsed.hostname == "localhost":
        return True
    try:
        return ipaddress.ip_address(parsed.hostname or "").is_loopback
    except ValueError:
        return False


@dataclass
class EmbeddingResult:
    vectors: list[list[float]]
    model: str
    tokens: int | None = None
    response_model: str | None = None
    model_check: str | None = None


class EmbeddingBackend(Protocol):
    def embed(self, inputs: list[str]) -> EmbeddingResult: ...


def split_for_embedding(text: str, limit: int) -> list[str]:
    """Pieces of at most ``limit`` characters, cut at sentence ends, then at spaces, then hard.

    Only the whitespace between pieces is dropped; every other character is kept in order.
    """
    if len(text) <= limit:
        return [text]
    pieces: list[str] = []
    current = ""
    for sentence in re.split(r"(?<=[.!?])\s+|\n+", text):
        units = [sentence] if len(sentence) <= limit else sentence.split()
        for unit in units:
            while len(unit) > limit:  # a single word longer than the limit
                if current:
                    pieces.append(current)
                    current = ""
                pieces.append(unit[:limit])
                unit = unit[limit:]
            candidate = f"{current} {unit}" if current else unit
            if len(candidate) <= limit:
                current = candidate
            else:
                pieces.append(current)
                current = unit
    if current:
        pieces.append(current)
    return [piece for piece in pieces if piece]


def mean_by_owner(vectors: list[Any], owners: list[int], count: int) -> list[list[float]]:
    """Each input's vector: the mean of its pieces' vectors (one piece: unchanged)."""
    if len(vectors) != len(owners):
        raise GatewayError(502, "invalid_provider_response", "embedding count differs")
    grouped: list[list[list[float]]] = [[] for _ in range(count)]
    for owner, vector in zip(owners, vectors, strict=True):
        grouped[owner].append(vector)
    return [
        [math.fsum(column) / len(group) for column in zip(*group, strict=True)]
        if len(group) > 1
        else group[0]
        for group in grouped
    ]


class FakeEmbeddings:
    def embed(self, inputs: list[str]) -> EmbeddingResult:
        vectors = [
            [
                int.from_bytes(hashlib.sha256(text.encode()).digest()[i : i + 4], "big")
                / (2**32 - 1)
                for i in range(0, 32, 4)
            ]
            for text in inputs
        ]
        return EmbeddingResult(vectors, "fake", sum(len(text) // 4 for text in inputs))


class OllamaEmbeddings:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def embed(self, inputs: list[str]) -> EmbeddingResult:
        response = self.settings.post_json(
            self.settings.ollama_url.rstrip("/") + "/api/embed",
            {"model": self.settings.ollama_embed_model, "input": inputs},
        )
        vectors = response.get("embeddings")
        if (
            not isinstance(vectors, list)
            or len(vectors) != len(inputs)
            or any(
                not isinstance(v, list)
                or not v
                or any(type(x) not in (float, int) or not math.isfinite(x) for x in v)
                for v in vectors
            )
        ):
            raise GatewayError(
                502, "invalid_provider_response", "Ollama returned invalid embeddings"
            )
        tokens = response.get("prompt_eval_count")
        if tokens is not None and (type(tokens) is not int or tokens < 0):
            raise GatewayError(
                502, "invalid_provider_response", "Ollama returned invalid token usage"
            )
        return EmbeddingResult(vectors, self.settings.ollama_embed_model, tokens)


def chunked(self: Gateway, inputs: list[str], row: dict[str, Any]) -> tuple[list[str], list[int]]:
    pieces: list[str] = []
    owners: list[int] = []
    for index, text in enumerate(inputs):
        parts = split_for_embedding(text, self.settings.embed_max_chars)
        if len(parts) > 1:
            row["chunked_inputs"] += 1
            row["chunks"] += len(parts)
        pieces += parts
        owners += [index] * len(parts)
    return pieces, owners


def embeddings(
    self: Gateway, request: dict[str, Any], *, batch: bool = False, single_retry: bool = False
) -> dict[str, Any]:
    inputs = request.get("input")
    if (
        self.settings.embedding_route == "provider"
        and not batch
        and isinstance(inputs, list)
        and len(inputs) > 1
        and all(isinstance(text, str) for text in inputs)
    ):
        return provider_batches(self, request)
    row = self.record("/v1/embeddings", request)
    provider = self.settings.embedding_route == "provider"
    if provider:  # the local route's call rows keep exactly their earlier fields
        row.update(
            response_model=None,
            reserved_usd=0.0,
            input_count=0,
            single_retry=single_retry,
            model_check=None,
        )
    start = time.monotonic()
    prompt = reply = ""
    try:
        self.check_model(request, self.settings.embedding_model_alias)
        for key, value in request.items():
            if key not in ("model", "input", "encoding_format", "report_embedding_stats"):
                raise unsupported(key, "parameter is not supported for embeddings")
            if key == "encoding_format" and value != "float":
                raise unsupported(key, "only float encoding is supported")
            if key == "report_embedding_stats" and type(value) is not bool:
                raise unsupported(key, "must be boolean")
            row["honoured"].append(key)
        inputs = request.get("input")
        if isinstance(inputs, str):
            inputs = [inputs]
        if not isinstance(inputs, list) or any(not isinstance(text, str) for text in inputs):
            raise unsupported(
                "input", "must be a string or list of strings; token arrays are unsupported"
            )
        if provider:
            row["input_count"] = len(inputs)
        prompt = json.dumps(inputs, ensure_ascii=False)
        row.update(prompt_sha256=digest(prompt), prompt_chars=sum(map(len, inputs)))
        with self.slot(row):
            try:
                result = self.embedding_attempt(inputs, row)
                pieces = None
            except GatewayError as exc:
                if (
                    self.settings.embedding_route == "provider"
                    or exc.status != 400
                    or not any(len(text) > self.settings.embed_max_chars for text in inputs)
                ):
                    raise
                row["provider_errors"].append(exc.code)
                pieces, owners = self.chunked(inputs, row)
            if pieces is not None:
                result = self.embedding_attempt(pieces, row)
                result.vectors = mean_by_owner(result.vectors, owners, len(inputs))
        # Retain successful earlier batches even if a later batch is refused by a cap.
        for text, vector in zip(inputs, result.vectors, strict=True):
            self.embedding_cache[(row["route"], row["model_used"], digest(text))] = list(vector)
        reply = json.dumps(result.vectors)
        row.update(
            model_used=result.model,
            prompt_tokens=result.tokens,
            reply_sha256=digest(reply),
            reply_chars=len(reply),
        )
        return {
            **(
                {"chunked_inputs": row["chunked_inputs"]}
                if request.get("report_embedding_stats")
                else {}
            ),
            "object": "list",
            "data": [
                {"object": "embedding", "index": i, "embedding": vector}
                for i, vector in enumerate(result.vectors)
            ],
            "model": result.model,
            "usage": {"prompt_tokens": result.tokens, "total_tokens": result.tokens},
        }
    except GatewayError as exc:
        row.update(status=exc.status, error_code=exc.code)
        if (
            self.settings.embedding_route != "provider"
            and exc.status == 400
            and (
                exc.code in {"context_length_exceeded", "input_too_long", "embedding_input_refused"}
                or exc.code == "provider_error"
                and re.search(
                    r"(?:input|context).*(?:length|limit|window)|too many tokens", str(exc), re.I
                )
            )
        ):
            row["error_code"] = "embedding_input_refused"
            raise GatewayError(
                400, "embedding_input_refused", f"local embedding input refused: {exc}"
            ) from exc
        if exc.param:
            row["refused"].append(exc.param)
        raise
    finally:
        row["latency_ms"] = (time.monotonic() - start) * 1000
        self.log(row, prompt, reply)


def provider_batches(self: Gateway, request: dict[str, Any]) -> dict[str, Any]:
    """One log/reservation per provider request; refused inputs stay explicit in the response."""
    inputs = request["input"]
    data: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    tokens: int | None = 0

    def collect(reply: dict[str, Any], offset: int) -> None:
        nonlocal tokens
        for item in reply["data"]:
            data.append({**item, "index": offset + item["index"]})
        used = reply["usage"]["total_tokens"]
        tokens = tokens + used if tokens is not None and used is not None else None

    for offset in range(0, len(inputs), EMBED_BATCH_INPUTS):
        chunk = inputs[offset : offset + EMBED_BATCH_INPUTS]
        try:
            collect(embeddings(self, {**request, "input": chunk}, batch=True), offset)
        except GatewayError as error:
            if error.code != "embedding_input_refused":
                raise
            if len(chunk) == 1:
                errors.append({"index": offset, "code": error.code, "message": str(error)})
                continue
            for index, text in enumerate(chunk, offset):
                try:
                    collect(
                        embeddings(
                            self, {**request, "input": [text]}, batch=True, single_retry=True
                        ),
                        index,
                    )
                except GatewayError as single_error:
                    if single_error.code != "embedding_input_refused":
                        raise
                    errors.append(
                        {"index": index, "code": single_error.code, "message": str(single_error)}
                    )
    return {
        "object": "list",
        "model": self.settings.provider_embed_model,
        "data": data,
        "usage": {"prompt_tokens": tokens, "total_tokens": tokens},
        **({"input_errors": errors} if errors else {}),
        **({"chunked_inputs": 0} if request.get("report_embedding_stats") else {}),
    }


def validate_settings(settings: Settings) -> None:
    if settings.embedding_route not in ("local", "provider", "ollama", "fake"):
        raise ValueError("invalid embedding route")
    if settings.embedding_route == "provider":
        if not settings.provider_embed_model or not settings.provider_embed_model.strip():
            raise ValueError("missing provider_embed_model (--provider-embed-model)")
        price = settings.provider_embed_usd_per_mtok
        if price is None or not math.isfinite(price) or price <= 0:
            raise ValueError("missing or invalid provider_embed_usd_per_mtok")


def counter_defaults(entry: dict[str, Any]) -> None:
    for name in ("local_embedding_calls", "provider_embedding_calls", "provider_embedding_tokens"):
        entry.setdefault(name, 0)
    entry.setdefault("provider_embedding_usd", 0.0)


def valid_counters(entry: dict[str, Any]) -> bool:
    counts = ("local_embedding_calls", "provider_embedding_calls", "provider_embedding_tokens")
    allowed = {"calls", "usd", "provider_embedding_usd", *counts}
    return (
        {"calls", "usd"} <= set(entry) <= allowed
        and all(type(entry.get(name, 0)) is int and entry.get(name, 0) >= 0 for name in counts)
        and type(entry.get("provider_embedding_usd", 0)) in (int, float)
        and math.isfinite(entry.get("provider_embedding_usd", 0))
        and entry.get("provider_embedding_usd", 0) >= 0
    )


def reserve_embedding(budget: Budget, usd: float, *, provider: bool) -> tuple[str, str, float]:
    # The same lock covers both embedding buckets and the existing money totals.
    from datetime import UTC, datetime

    current_month, run = datetime.now(UTC).strftime("%Y-%m"), budget.settings.run_id
    with budget.locked():
        state = budget.read()
        for group, key, prefix in (("runs", run, "run"), ("months", current_month, "month")):
            entry = state[group].setdefault(key, {"calls": 0, "usd": 0.0})
            # The local route writes exactly main's fields; provider counters appear only when used.
            entry.setdefault("local_embedding_calls", 0)
            if provider:
                counter_defaults(entry)
            attempts = entry["local_embedding_calls"] + entry.get("provider_embedding_calls", 0)
            if prefix == "run" and attempts >= EMBEDDING_CALLS_PER_RUN:
                raise GatewayError(
                    429,
                    "budget_exhausted",
                    "budget exhausted: embedding limit "
                    f"EMBEDDING_CALLS_PER_RUN ({EMBEDDING_CALLS_PER_RUN}) reached",
                )
            if provider and entry["usd"] + usd > getattr(budget.settings, f"{prefix}_max_usd"):
                raise GatewayError(429, "budget_exhausted", f"budget exhausted: {prefix}_max_usd")
            entry["provider_embedding_calls" if provider else "local_embedding_calls"] += 1
            if provider:
                entry["usd"] += usd
                entry["provider_embedding_usd"] += usd
        budget.write(state)
    return current_month, run, usd


def settle_embedding(
    budget: Budget, ticket: tuple[str, str, float], actual: float, tokens: int | None
) -> None:
    if not math.isfinite(actual) or actual < 0:
        raise GatewayError(502, "invalid_usage", "provider cost is invalid")
    current_month, run, reserved = ticket
    with budget.locked():
        state = budget.read()
        for group, key in (("months", current_month), ("runs", run)):
            entry = state[group][key]
            entry["usd"] = max(0.0, entry["usd"] + actual - reserved)
            entry["provider_embedding_usd"] = max(
                0.0, entry["provider_embedding_usd"] + actual - reserved
            )
            entry["provider_embedding_tokens"] += tokens or 0
        budget.write(state)


def usage_tokens(response: dict[str, Any]) -> int | None:
    usage = response.get("usage")
    if usage is None:
        return None
    if not isinstance(usage, dict):
        raise GatewayError(502, "invalid_usage", "provider embedding usage is invalid")
    value = usage.get("total_tokens", usage.get("prompt_tokens"))
    if value is not None and (type(value) is not int or value < 0):
        raise GatewayError(502, "invalid_usage", "provider embedding token usage is invalid")
    return value


def same_model(reported: Any, requested: str) -> bool:
    """OpenRouter reports the upstream spelling (``Qwen/Qwen3-Embedding-8B``, or no vendor)."""
    if not isinstance(reported, str):
        return False
    return reported.lower().rsplit("/", 1)[-1] == requested.lower().rsplit("/", 1)[-1]


class ProviderEmbeddings:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        # Exactly the same environment and slash handling as ApiChat.__init__.
        self.base = os.environ["ALPHA_GATEWAY_API_BASE"].rstrip("/")
        self.key = os.environ["ALPHA_GATEWAY_API_KEY"]

    def embed(self, inputs: list[str]) -> EmbeddingResult:
        response = self.settings.post_json(
            self.base + "/embeddings",
            {"model": self.settings.provider_embed_model, "input": inputs},
            self.key,
            timeout=self.settings.api_timeout,
        )
        tokens = usage_tokens(response)
        try:
            if "model" in response and not same_model(
                response["model"], self.settings.provider_embed_model or ""
            ):
                raise ValueError("provider returned a different model")
            data = response["data"]
            if not isinstance(data, list) or len(data) != len(inputs):
                raise ValueError("invalid count")
            ordered = sorted(data, key=lambda item: item["index"])
            if any(
                type(item["index"]) is not int or item["index"] != i
                for i, item in enumerate(ordered)
            ):
                raise ValueError("invalid indices")
            vectors = [item["embedding"] for item in ordered]
            if any(
                not isinstance(v, list)
                or not v
                or any(type(x) not in (int, float) or not math.isfinite(x) for x in v)
                for v in vectors
            ):
                raise ValueError("invalid vectors")
            if vectors and any(len(v) != len(vectors[0]) for v in vectors):
                raise ValueError("inconsistent dimensions")
        except (KeyError, TypeError, ValueError) as exc:
            raise GatewayError(
                502,
                "invalid_provider_response",
                "provider returned invalid embeddings",
                payload={
                    "usage": response.get("usage"),
                    "response_model": response.get("model"),
                    "model_check": "model_mismatch"
                    if "model" in response
                    and not same_model(response["model"], self.settings.provider_embed_model or "")
                    else "invalid_response",
                },
            ) from exc
        return EmbeddingResult(
            vectors,
            self.settings.provider_embed_model or "",
            tokens,
            response_model=response.get("model"),
            model_check="matched" if "model" in response else "model_not_reported",
        )


def embedding_attempt(self: Gateway, inputs: list[str], row: dict[str, Any]) -> EmbeddingResult:
    backend = self.embedding_backend
    local = type(backend) is FakeEmbeddings or (
        type(backend) is OllamaEmbeddings and loopback_url(self.settings.ollama_url)
    )
    provider = type(backend) is ProviderEmbeddings and self.settings.embedding_route == "provider"
    row["local_embedding"] = local
    if not provider:
        ticket = self.budget.reserve(0, local_embedding=local)
        row["attempts"] += 1
        row["embedding_inputs_sent"] = row.get("embedding_inputs_sent", 0) + len(inputs)
        try:
            return backend.embed(inputs)
        finally:
            if not local:
                self.budget.settle(ticket, 0)
    assert isinstance(backend, ProviderEmbeddings)
    row["provider_embedding"] = True
    price = self.settings.provider_embed_usd_per_mtok
    assert price is not None
    reserved = sum(map(len, inputs)) / 3 * price / 1e6
    ticket = reserve_embedding(self.budget, reserved, provider=True)
    row["reserved_usd"] = reserved
    row["attempts"] += 1
    row["embedding_inputs_sent"] = row.get("embedding_inputs_sent", 0) + len(inputs)
    actual, tokens = reserved, None
    try:
        result = backend.embed(inputs)
        row.update(response_model=result.response_model, model_check=result.model_check)
        tokens = result.tokens
        actual = reserved if tokens is None else tokens * price / 1e6
        return result
    except GatewayError as exc:
        row.update(
            response_model=(exc.payload or {}).get("response_model"),
            model_check=(exc.payload or {}).get("model_check"),
        )
        tokens = usage_tokens(exc.payload or {})
        # Timeouts/invalid replies may have been billed; explicit errors with no usage were not.
        explicit_error = exc.payload is not None and "error" in exc.payload
        actual = (
            tokens * price / 1e6
            if tokens is not None
            else (
                reserved
                if not explicit_error
                and exc.code in ("provider_timeout", "invalid_provider_response", "invalid_usage")
                else 0.0
            )
        )
        code = exc.code.replace(backend.key, "[redacted]")
        message = str(exc).replace(backend.key, "[redacted]")
        row["provider_errors"].append(code)
        input_refused = code in {
            "context_length_exceeded",
            "input_too_long",
            "embedding_input_refused",
            "invalid_input",
        } or re.search(r"(?:input|context).*(?:length|limit|window)|too many tokens", message, re.I)
        if exc.status == 413 or (exc.status in (400, 422) and input_refused):
            message = f"provider embedding input refused ({code}): {message}"
            code = "embedding_input_refused"
        raise GatewayError(exc.status, code, message) from None
    except (ValueError, OSError):
        actual = 0.0
        row["provider_errors"].append("provider_unavailable")
        raise GatewayError(
            502, "provider_unavailable", "embedding request could not be sent"
        ) from None
    finally:
        settle_embedding(self.budget, ticket, actual, tokens)
        row["usd"] += actual
        row["prompt_tokens"] = tokens


def cached_embeddings(self: Gateway, request: dict[str, Any]) -> dict[str, Any]:
    """Cache exact texts only for this gateway process; retain partial-batch input errors."""
    inputs = request.get("input")
    texts = [inputs] if isinstance(inputs, str) else inputs
    allowed = {"model", "input", "encoding_format", "report_embedding_stats"}
    valid = (
        isinstance(texts, list)
        and bool(texts)
        and all(isinstance(t, str) for t in texts)
        and set(request) <= allowed
        and request.get("encoding_format", "float") == "float"
        and type(request.get("report_embedding_stats", False)) is bool
        and request.get("model") == self.settings.embedding_model_alias
    )
    if not valid:
        return embeddings(self, request)
    assert isinstance(texts, list)
    with self.embedding_cache_lock:
        row = self.record("/v1/embeddings", request)
        route, model = row["route"], row["model_used"]
        keys = [(route, model, digest(text)) for text in texts]
        pending: dict[tuple[str, str, str], str] = {}
        hits = 0
        for key, text in zip(keys, texts, strict=True):
            if key in self.embedding_cache or key in pending:
                hits += 1
            else:
                pending[key] = text
        reply = (
            embeddings(self, {**request, "input": list(pending.values())})
            if pending
            else {
                "model": model,
                "data": [],
                "usage": {"prompt_tokens": 0, "total_tokens": 0},
                **({"chunked_inputs": 0} if request.get("report_embedding_stats") else {}),
            }
        )
        requested = list(pending)
        for item in reply["data"]:
            self.embedding_cache[requested[item["index"]]] = list(item["embedding"])
        failures = {requested[item["index"]]: item for item in reply.get("input_errors", [])}
        if hits:
            row.update(
                embedding_cache_hits=hits, cache_only=True, local_embedding=route != "provider"
            )
            self.log(row)
        return {
            **reply,
            "object": "list",
            "data": [
                {
                    "object": "embedding",
                    "index": index,
                    "embedding": list(self.embedding_cache[key]),
                }
                for index, key in enumerate(keys)
                if key in self.embedding_cache
            ],
            **(
                {
                    "input_errors": [
                        {**failures[key], "index": index}
                        for index, key in enumerate(keys)
                        if key in failures
                    ]
                }
                if failures
                else {}
            ),
        }
