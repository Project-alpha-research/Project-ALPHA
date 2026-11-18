"""Local RD-Agent model boundary; run directly without importing RD-Agent or ALPHA."""

from __future__ import annotations

import argparse
import fcntl
import importlib
import json
import math
import os
import re
import secrets
import signal
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, fields
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol

if TYPE_CHECKING:
    from . import gateway_embeddings as embeddings_impl
    from . import gateway_usage as usage_impl
else:
    if not __package__:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
    embeddings_impl = importlib.import_module(
        f"{__package__}.gateway_embeddings" if __package__ else "gateway_embeddings"
    )

    usage_impl = importlib.import_module(
        f"{__package__}.gateway_usage" if __package__ else "gateway_usage"
    )

GatewayError = embeddings_impl.GatewayError
EmbeddingResult = embeddings_impl.EmbeddingResult
EmbeddingBackend = embeddings_impl.EmbeddingBackend
FakeEmbeddings = embeddings_impl.FakeEmbeddings
OllamaEmbeddings = embeddings_impl.OllamaEmbeddings
ProviderEmbeddings = embeddings_impl.ProviderEmbeddings
EMBEDDING_CALLS_PER_RUN = embeddings_impl.EMBEDDING_CALLS_PER_RUN
digest = embeddings_impl.digest
loopback_url = embeddings_impl.loopback_url
unsupported = embeddings_impl.unsupported
split_for_embedding = embeddings_impl.split_for_embedding
mean_by_owner = embeddings_impl.mean_by_owner

GATEWAY_DISABLED_FEATURES = (
    "shell_tool",
    "unified_exec",
    "apps",
    "plugins",
    "remote_plugin",
    "browser_use",
    "browser_use_external",
    "computer_use",
    "image_generation",
    "multi_agent",
    "multi_agent_v2",
    "memories",
    "hooks",
    "view_image",
    "sleep_tool",
    "goals",
    "skill_search",
    "tool_suggest",
    "in_app_browser",
    "workspace_dependencies",
    "code_mode_host",
)
MAX_BODY = 4 * 1024 * 1024


def now() -> str:
    return datetime.now(UTC).isoformat()


def month() -> str:
    return datetime.now(UTC).strftime("%Y-%m")


@dataclass
class Settings:
    data_dir: Path
    run_id: str
    chat_route: str = "codex"
    embedding_route: str = "local"
    provider_embed_model: str | None = None
    provider_embed_usd_per_mtok: float | None = None
    chat_model_alias: str = "alpha-chat"
    embedding_model_alias: str = "alpha-embed"
    codex_bin: str = "codex"
    codex_model: str = "gpt-6.1-sol"
    codex_effort: str = "medium"
    codex_timeout: float = 900
    json_retries: int = 2
    # Total paid-call deadline; retries reserve against every cap (ADR-0055).
    api_timeout: float = 180
    provider_retries: int = 1
    coding_reasoning_tokens: int | None = None
    # Retry refused long embeddings as averaged sentence chunks, never truncated (ADR-0055).
    embed_max_chars: int = 2000
    accept_unhonoured: tuple[str, ...] = ()
    api_model: str | None = None
    api_price_in_per_mtok: float | None = None
    api_price_out_per_mtok: float | None = None
    api_reserve_output_tokens: int = 4096
    api_openrouter: bool = False
    no_router_session: bool = False
    ollama_url: str = "http://127.0.0.1:11434"
    ollama_embed_model: str = "nomic-embed-text"
    run_max_calls: int = 60
    month_max_calls: int = 3000
    month_max_usd: float = 50.0
    run_max_usd: float = 10.0
    max_concurrency: int = 2
    queue_timeout: float = 600
    log_content: bool = False

    def post_json(
        self, url: str, body: dict[str, Any], key: str | None = None, timeout: float | None = None
    ) -> dict[str, Any]:
        if key is None and timeout is None:
            return post_json(url, body)
        return post_json(url, body, key, timeout=900 if timeout is None else timeout)

    @property
    def state_dir(self) -> Path:
        return self.data_dir / "model-gateway"

    def validate(self) -> None:
        if self.coding_reasoning_tokens is not None:
            raise ValueError(
                "coding_reasoning_tokens cannot be sent: provider request field is unconfirmed"
            )
        if not self.data_dir.is_absolute() or not self.data_dir.is_dir():
            raise ValueError("data-dir must be an existing absolute directory")
        root = self.data_dir.resolve()
        if any((p / ".git").exists() for p in (root, *root.parents)):
            raise ValueError("state is stored under the data directory, never in git")
        if self.month_max_usd > 50:
            raise ValueError("the owner's ceiling is 50 USD a month")
        if not 0 < self.run_max_usd <= self.month_max_usd:
            raise ValueError("run_max_usd must be positive and at most month_max_usd")
        for name in (
            "run_max_calls",
            "month_max_calls",
            "max_concurrency",
            "codex_timeout",
            "api_timeout",
            "queue_timeout",
            "month_max_usd",
            "run_max_usd",
        ):
            value = getattr(self, name)
            if not math.isfinite(value) or value <= 0:
                raise ValueError(f"{name} must be positive and finite")
        if self.json_retries < 0 or self.api_reserve_output_tokens < 0:
            raise ValueError("json_retries and api_reserve_output_tokens must be nonnegative")
        if type(self.provider_retries) is not int or not 0 <= self.provider_retries <= 3:
            raise ValueError("provider_retries must be 0, 1, 2 or 3")
        if type(self.embed_max_chars) is not int or self.embed_max_chars < 100:
            raise ValueError("embed_max_chars must be an integer of at least 100")
        if not loopback_url(self.ollama_url):
            raise ValueError("ollama-url must be loopback")
        if self.chat_route not in ("codex", "api", "fake"):
            raise ValueError("invalid chat route")
        embeddings_impl.validate_settings(self)
        if self.codex_effort not in ("low", "medium", "high"):
            raise ValueError("invalid codex effort")
        if self.chat_route == "api" or self.embedding_route == "provider":
            for key in ("ALPHA_GATEWAY_API_KEY", "ALPHA_GATEWAY_API_BASE"):
                if not os.environ.get(key):
                    raise ValueError(f"missing {key}")
            base = os.environ["ALPHA_GATEWAY_API_BASE"]
            parsed = urllib.parse.urlsplit(base)
            local = parsed.scheme == "http" and parsed.hostname in ("127.0.0.1", "localhost")
            if (
                not parsed.hostname
                or parsed.username
                or parsed.password
                or parsed.query
                or parsed.fragment
                or not (parsed.scheme == "https" or local)
            ):
                raise ValueError("ALPHA_GATEWAY_API_BASE must be HTTPS or local HTTP")
        if self.chat_route == "api":
            if not self.api_model:
                raise ValueError("missing api_model (--api-model)")
            for name in ("api_price_in_per_mtok", "api_price_out_per_mtok"):
                price = getattr(self, name)
                if price is None or not math.isfinite(price) or price <= 0:
                    raise ValueError(f"missing or invalid {name}")
        self.state_dir.mkdir(mode=0o700, exist_ok=True)


class Budget:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        settings.validate()
        self.path = settings.state_dir / "budget.json"
        self.lock_path = settings.state_dir / "budget.lock"

    @contextmanager
    def locked(self) -> Iterator[None]:
        try:
            with self.lock_path.open("a") as lock:
                fcntl.flock(lock, fcntl.LOCK_EX)
                try:
                    yield
                finally:
                    fcntl.flock(lock, fcntl.LOCK_UN)
        except OSError as exc:
            raise GatewayError(503, "budget_state_unreadable", "budget lock is unreadable") from exc

    def read(self) -> dict[str, Any]:
        try:
            try:
                raw = self.path.read_text(encoding="utf-8")
            except FileNotFoundError:
                return {"schema_version": 1, "months": {}, "runs": {}}
            state = json.loads(raw)
            if (
                not isinstance(state, dict)
                or set(state) != {"schema_version", "months", "runs"}
                or type(state["schema_version"]) is not int
                or state["schema_version"] != 1
            ):
                raise ValueError("invalid budget schema")
            for group in ("months", "runs"):
                if not isinstance(state[group], dict):
                    raise ValueError("invalid budget group")
                for key, entry in state[group].items():
                    if (
                        not key
                        or not isinstance(entry, dict)
                        or not embeddings_impl.valid_counters(entry)
                        or type(entry["calls"]) is not int
                        or entry["calls"] < 0
                        or type(entry["usd"]) not in (int, float)
                        or not math.isfinite(entry["usd"])
                        or entry["usd"] < 0
                    ):
                        raise ValueError("invalid budget counters")
            return state
        except (OSError, UnicodeError, ValueError, OverflowError) as exc:
            raise GatewayError(
                503, "budget_state_unreadable", "budget state is unreadable"
            ) from exc

    def write(self, state: dict[str, Any]) -> None:
        temp_name: str | None = None
        try:
            with tempfile.NamedTemporaryFile(mode="w", dir=self.path.parent, delete=False) as file:
                temp_name = file.name
                json.dump(state, file, allow_nan=False)
                file.flush()
                os.fsync(file.fileno())
            os.replace(temp_name, self.path)
        except (OSError, ValueError) as exc:
            raise GatewayError(
                503, "budget_state_unreadable", "budget state cannot be written"
            ) from exc
        finally:
            if temp_name and Path(temp_name).exists():
                Path(temp_name).unlink()

    def status(self) -> dict[str, Any]:
        with self.locked():
            state = self.read()
            for group in ("runs", "months"):
                for entry in state[group].values():
                    entry.update(counted_calls=entry["calls"])
                    embeddings_impl.counter_defaults(entry)
            return state

    def reserve(self, usd: float, *, local_embedding: bool = False) -> tuple[str, str, float]:
        if local_embedding:
            if usd != 0:
                raise ValueError("local embeddings must have zero provider cost")
            return embeddings_impl.reserve_embedding(self, 0, provider=False)
        current_month, run = month(), self.settings.run_id
        with self.locked():
            state = self.read()
            for group, key, prefix in (("runs", run, "run"), ("months", current_month, "month")):
                entry = state[group].setdefault(key, {"calls": 0, "usd": 0.0})
                entry.setdefault("local_embedding_calls", 0)
                for field, increment in (("calls", 1), ("usd", usd)):
                    cap = f"{prefix}_max_{field}"
                    if entry[field] + increment > getattr(self.settings, cap):
                        raise GatewayError(429, "budget_exhausted", f"budget exhausted: {cap}")
                entry["calls"] += 1
                entry["usd"] += usd
            self.write(state)
        return current_month, run, usd

    def settle(self, ticket: tuple[str, str, float], actual: float) -> None:
        if not math.isfinite(actual) or actual < 0:
            raise GatewayError(502, "invalid_usage", "provider cost is invalid")
        current_month, run, reserved = ticket
        with self.locked():
            state = self.read()
            for group, key in (("months", current_month), ("runs", run)):
                if key not in state[group]:
                    raise GatewayError(503, "budget_state_unreadable", "reservation is missing")
                state[group][key]["usd"] = max(0.0, state[group][key]["usd"] + actual - reserved)
            self.write(state)


@dataclass
class ChatResult:
    text: str
    model: str
    prompt_tokens: int | None = None
    cached_tokens: int | None = None
    completion_tokens: int | None = None
    reasoning_tokens: int | None = None
    tool_events: int = 0
    usd: float = 0.0
    response: dict[str, Any] | None = None
    estimated_usd: float | None = None
    provider: str | None = None
    id: str | None = None
    cache_write_tokens: int | None = None
    cache_discount: float | None = None
    charged_usd: float | None = None


class ChatBackend(Protocol):
    def complete(
        self,
        request: dict[str, Any],
        prompt: str,
        instructions: str,
        effort: str,
        schema: dict[str, Any] | None,
    ) -> ChatResult: ...


class FakeChat:
    def __init__(self) -> None:
        script = os.environ.get("ALPHA_GATEWAY_FAKE_SCRIPT")
        self.script = json.loads(Path(script).read_text()) if script else []
        if not isinstance(self.script, list) or any(
            not isinstance(entry, dict)
            or not isinstance(entry.get("contains"), str)
            or not isinstance(entry.get("reply"), str)
            for entry in self.script
        ):
            raise ValueError(
                "ALPHA_GATEWAY_FAKE_SCRIPT must contain a list of contains/reply strings"
            )
        self.remaining_bad = int(os.environ.get("ALPHA_GATEWAY_FAKE_BAD_JSON_FIRST", "0"))
        self.lock = threading.Lock()

    def complete(
        self,
        request: dict[str, Any],
        prompt: str,
        instructions: str,
        effort: str,
        schema: dict[str, Any] | None,
    ) -> ChatResult:
        for entry in self.script:
            if entry["contains"] in instructions + "\n" + prompt:
                reply = entry["reply"]
                return ChatResult(
                    reply, "fake", len(prompt) // 4, completion_tokens=len(reply) // 4
                )
        with self.lock:
            bad = self.remaining_bad > 0
            self.remaining_bad -= int(bad)
        reply = "not json" if bad else json.dumps({"fake": True, "prompt_sha256": digest(prompt)})
        return ChatResult(reply, "fake", len(prompt) // 4, completion_tokens=len(reply) // 4)


def sanitise(message: str, sensitive: tuple[str, ...] = ()) -> str:
    for value in (*sensitive, os.environ.get("ALPHA_GATEWAY_API_KEY", "")):
        if value:
            message = message.replace(value, "[redacted]")
    message = re.sub(r"sk-[A-Za-z0-9_-]+", "[redacted]", message)
    return " ".join(message.split())[:300]


class CodexChat:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def complete(
        self,
        request: dict[str, Any],
        prompt: str,
        instructions: str,
        effort: str,
        schema: dict[str, Any] | None,
    ) -> ChatResult:
        s = self.settings
        with tempfile.TemporaryDirectory(prefix="alpha-gateway-") as directory:
            temp = Path(directory)
            work = temp / "work"
            work.mkdir()
            instruction_path = temp / "instructions.md"
            instruction_path.write_text(instructions, encoding="utf-8")
            last = temp / "last.txt"
            cmd = [
                s.codex_bin,
                "exec",
                "--ignore-user-config",
                "--skip-git-repo-check",
                "--ephemeral",
                "-s",
                "read-only",
                "-C",
                str(work),
                "-m",
                s.codex_model,
            ]
            for config in (
                f"model_reasoning_effort={json.dumps(effort)}",
                'approval_policy="never"',
                'web_search="disabled"',
                f"model_instructions_file={json.dumps(str(instruction_path))}",
                "include_environment_context=false",
                "include_permissions_instructions=false",
                "include_collaboration_mode_instructions=false",
                "include_apps_instructions=false",
                "skills.include_instructions=false",
                "skills.bundled.enabled=false",
                "agents.enabled=false",
            ):
                cmd += ["-c", config]
            for feature in GATEWAY_DISABLED_FEATURES:
                cmd += ["--disable", feature]
            if schema is not None:
                schema_path = temp / "schema.json"
                schema_path.write_text(json.dumps(schema), encoding="utf-8")
                cmd += ["--output-schema", str(schema_path)]
            cmd += ["--json", "-o", str(last), "--color", "never", "-"]
            env = {
                k: os.environ[k]
                for k in ("PATH", "HOME", "LANG", "LC_ALL", "TMPDIR", "CODEX_HOME")
                if k in os.environ
            }
            try:
                process = subprocess.Popen(
                    cmd,
                    cwd=work,
                    env=env,
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    start_new_session=True,
                )
            except OSError as exc:
                raise GatewayError(502, "codex_failed", "codex could not start") from exc
            try:
                stdout, stderr = process.communicate(prompt, timeout=s.codex_timeout)
            except subprocess.TimeoutExpired as exc:
                os.killpg(process.pid, signal.SIGKILL)
                process.communicate()
                raise GatewayError(504, "codex_timeout", "codex exceeded its timeout") from exc
            usage: dict[str, Any] = {}
            tool_events = 0
            failures: list[str] = []
            try:
                # An "error" item is a CLI notice (e.g. code mode failing closed), not a tool.
                for line in stdout.splitlines():
                    event = json.loads(line)
                    kind = event.get("type")
                    if kind in ("item.started", "item.completed") and event.get("item", {}).get(
                        "type"
                    ) not in ("agent_message", "reasoning", "error"):
                        tool_events += 1
                    if kind == "turn.completed":
                        usage = event.get("usage") or {}
                    if kind in ("turn.failed", "error"):
                        error = event.get("error", event)
                        failures.append(
                            str(error.get("message", "codex failed"))
                            if isinstance(error, dict)
                            else str(error)
                        )
            except (ValueError, AttributeError, TypeError) as exc:
                raise GatewayError(
                    502, "codex_failed", "codex emitted invalid JSON events"
                ) from exc
            if tool_events:
                raise GatewayError(
                    502, "codex_used_a_tool", "codex used a tool", tool_events=tool_events
                )
            if failures or process.returncode:
                raw_message = " ".join(failures) or stderr or "codex failed"
                message = sanitise(raw_message, (prompt, instructions))
                limited = re.search(
                    r"usage limit|usageLimitExceeded|rate limit|429|quota|purchase more credits",
                    raw_message,
                    re.IGNORECASE,
                )
                raise GatewayError(
                    429 if limited else 502,
                    "codex_usage_limit" if limited else "codex_failed",
                    message,
                )
            try:
                reply = last.read_text(encoding="utf-8")
            except (OSError, UnicodeError) as exc:
                raise GatewayError(
                    502, "codex_failed", "codex output file is missing or unreadable"
                ) from exc
            if not reply.strip():
                raise GatewayError(502, "codex_failed", "codex output is empty")
            if not isinstance(usage, dict) or any(
                value is not None and (type(value) is not int or value < 0)
                for value in (
                    usage.get(field)
                    for field in (
                        "input_tokens",
                        "cached_input_tokens",
                        "output_tokens",
                        "reasoning_output_tokens",
                    )
                )
            ):
                raise GatewayError(502, "codex_failed", "codex returned invalid token usage")
            return ChatResult(
                reply,
                s.codex_model,
                usage.get("input_tokens"),
                usage.get("cached_input_tokens"),
                usage.get("output_tokens"),
                usage.get("reasoning_output_tokens"),
                tool_events,
            )


PROVIDER_RETRYABLE = ("provider_timeout", "invalid_provider_response")


def post_json(
    url: str, body: dict[str, Any], key: str | None = None, timeout: float = 900
) -> dict[str, Any]:
    """Bound the whole call; abandon its daemon thread at the deadline.
    The connection closes when the process ends or the reply arrives."""
    box: dict[str, Any] = {}

    def call() -> None:
        try:
            box["result"] = _post_json(url, body, key, timeout)
        except BaseException as exc:  # re-raised in the caller's thread
            box["error"] = exc

    worker = threading.Thread(target=call, name="provider-call", daemon=True)
    worker.start()
    worker.join(timeout)
    if worker.is_alive():
        raise GatewayError(
            504, "provider_timeout", f"provider gave no complete reply within {timeout:g} s"
        )
    if "error" in box:
        raise box["error"]
    result: dict[str, Any] = box["result"]
    return result


def _post_json(url: str, body: dict[str, Any], key: str | None, timeout: float) -> dict[str, Any]:
    headers = {"Content-Type": "application/json"}
    if key is not None:
        headers["Authorization"] = f"Bearer {key}"
    request = urllib.request.Request(url, data=json.dumps(body).encode(), headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            result = json.load(response)
    except urllib.error.HTTPError as exc:
        try:
            payload = json.loads(exc.read())
        except (ValueError, UnicodeError):
            payload = None
        if isinstance(payload, dict) and isinstance(payload.get("error"), dict):
            error = payload["error"]
            raise GatewayError(
                exc.code,
                str(error.get("code") or "provider_error"),
                str(error.get("message", "provider error")),
                payload=payload,
            ) from exc
        message = payload.get("error") if isinstance(payload, dict) else None
        raise GatewayError(
            exc.code,
            "provider_error",
            message if isinstance(message, str) else "provider returned an HTTP error",
        ) from exc
    except TimeoutError as exc:
        raise GatewayError(504, "provider_timeout", "provider read timed out") from exc
    except (OSError, urllib.error.URLError) as exc:
        if isinstance(getattr(exc, "reason", None), TimeoutError):
            raise GatewayError(504, "provider_timeout", "provider connection timed out") from exc
        raise GatewayError(502, "provider_unavailable", "model provider unavailable") from exc
    except (ValueError, UnicodeError) as exc:
        raise GatewayError(
            502, "invalid_provider_response", "provider returned invalid JSON"
        ) from exc
    if not isinstance(result, dict):
        raise GatewayError(502, "invalid_provider_response", "provider response must be an object")
    return result


class ApiChat:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.base = os.environ["ALPHA_GATEWAY_API_BASE"].rstrip("/")
        self.key = os.environ["ALPHA_GATEWAY_API_KEY"]

    def complete(
        self,
        request: dict[str, Any],
        prompt: str,
        instructions: str,
        effort: str,
        schema: dict[str, Any] | None,
    ) -> ChatResult:
        s = self.settings
        response = post_json(
            self.base + "/chat/completions",
            {
                **{k: v for k, v in request.items() if k not in ("stream_options", "session_id")},
                "model": s.api_model,
                "stream": False,
                **(
                    {"session_id": s.run_id}
                    if s.chat_route == "api" and not s.no_router_session
                    else {}
                ),
                # Require parameter fidelity and the provider's charged cost in usage.
                **(
                    {"provider": {"require_parameters": True}, "usage": {"include": True}}
                    if s.api_openrouter
                    else {}
                ),
            },
            self.key,
            timeout=s.api_timeout,
        )
        try:
            text = response["choices"][0]["message"]["content"]
            usage = response["usage"]
            incoming, outgoing = usage["prompt_tokens"], usage["completion_tokens"]
            if (
                not isinstance(text, str)
                or type(incoming) is not int
                or type(outgoing) is not int
                or min(incoming, outgoing) < 0
            ):
                raise ValueError("invalid usage or text")
            assert s.api_price_in_per_mtok is not None and s.api_price_out_per_mtok is not None
            estimate = (
                incoming * s.api_price_in_per_mtok + outgoing * s.api_price_out_per_mtok
            ) / 1e6
            cost = estimate
            charged = usage.get("cost")
            if s.api_openrouter:
                # The provider's charged cost settles the budget; a missing or invalid one fails.
                if type(charged) not in (int, float) or not math.isfinite(charged) or charged < 0:
                    raise ValueError("provider omitted its charged cost")
                cost = float(charged)
            facts = usage_impl.response_facts(response)
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            raise GatewayError(
                502, "invalid_provider_response", "provider omitted text or usage"
            ) from exc
        response["model"] = s.api_model
        return ChatResult(
            text,
            s.api_model or "",
            incoming,
            completion_tokens=outgoing,
            usd=cost,
            response=response,
            estimated_usd=estimate,
            **facts,
        )


@dataclass
class ChatPlan:
    prompt: str
    instructions: str
    effort: str
    schema: dict[str, Any] | None
    json_required: bool


class Gateway:
    def __init__(
        self,
        settings: Settings,
        chat_backend: ChatBackend | None = None,
        embedding_backend: EmbeddingBackend | None = None,
    ) -> None:
        self.settings = settings
        self.budget = Budget(settings)
        self.chat_backend: ChatBackend
        if chat_backend is not None:
            self.chat_backend = chat_backend
        elif settings.chat_route == "codex":
            self.chat_backend = CodexChat(settings)
        elif settings.chat_route == "api":
            self.chat_backend = ApiChat(settings)
        else:
            self.chat_backend = FakeChat()
        self.embedding_backend = embedding_backend or (
            ProviderEmbeddings(settings)
            if settings.embedding_route == "provider"
            else FakeEmbeddings()
            if settings.embedding_route == "fake"
            else OllamaEmbeddings(settings)
        )
        self.slots = threading.BoundedSemaphore(settings.max_concurrency)
        self.log_lock = threading.Lock()
        self.log_path = settings.state_dir / "calls.jsonl"
        self.session_token = ""
        self.embedding_cache: dict[tuple[str, str, str], list[float]] = {}
        self.embedding_cache_lock = threading.Lock()

    def record(self, endpoint: str, request: dict[str, Any]) -> dict[str, Any]:
        chat = endpoint == "/v1/chat/completions"
        s = self.settings
        route = s.chat_route if chat else s.embedding_route
        model = (
            s.codex_model
            if route == "codex"
            else s.api_model
            if route == "api"
            else s.ollama_embed_model
            if route in ("local", "ollama")
            else s.provider_embed_model
            if route == "provider"
            else "fake"
        )
        return dict(
            **(usage_impl.record_defaults() if chat else {}),
            ts=now(),
            run_id=s.run_id,
            endpoint=endpoint,
            route=route,
            local_embedding=False,
            requested_model=request.get("model"),
            model_used=model,
            effort=None,
            honoured=[],
            enforced=[],
            waived=[],
            refused=[],
            attempts=0,
            timeout_retry_attempts=0,
            provider_errors=[],
            chunked_inputs=0,
            chunks=0,
            json_valid=None,
            prompt_tokens=None,
            cached_tokens=None,
            completion_tokens=None,
            reasoning_tokens=None,
            usd=0.0,
            estimated_usd=None,
            queue_ms=0.0,
            latency_ms=0.0,
            status=200,
            error_code=None,
            prompt_sha256=None,
            reply_sha256=None,
            prompt_chars=0,
            reply_chars=0,
            tool_events=0,
        )

    def log_json(self, value: dict[str, Any]) -> str:
        line = json.dumps(value, allow_nan=False)
        for secret in (
            self.session_token,
            os.environ.get("ALPHA_GATEWAY_API_KEY", ""),
            getattr(getattr(self, "chat_backend", None), "key", ""),
            getattr(getattr(self, "embedding_backend", None), "key", ""),
        ):
            if secret:
                line = line.replace(json.dumps(secret)[1:-1], "[redacted]")
        return line

    def log(
        self, row: dict[str, Any], prompt: str = "", reply: str = "", instructions: str = ""
    ) -> None:
        line = self.log_json(row)
        with self.log_lock, self.log_path.open("a", encoding="utf-8") as file:
            file.write(line + "\n")
            print(line, file=sys.stderr)
            if self.settings.log_content:
                with (self.settings.state_dir / "content.jsonl").open(
                    "a", encoding="utf-8"
                ) as content:
                    content.write(
                        self.log_json(
                            {
                                "ts": row["ts"],
                                "instructions": instructions,
                                "prompt": prompt,
                                "reply": reply,
                            }
                        )
                        + "\n"
                    )

    def check_model(self, request: dict[str, Any], alias: str) -> None:
        if request.get("model") != alias:
            raise GatewayError(
                400, "model_not_served", "model is not served by this endpoint", "model"
            )

    def chat_plan(self, request: dict[str, Any], row: dict[str, Any]) -> ChatPlan:
        self.check_model(request, self.settings.chat_model_alias)
        api = self.settings.chat_route == "api"
        effort = request.get("reasoning_effort", self.settings.codex_effort)
        schema = None
        json_required = False
        if api:
            # The provider is called without streaming; the reply is replayed as a stream.
            enforced = ("stream", "stream_options", "session_id")
            row["honoured"] = [k for k in request if k not in enforced]
            row["enforced"] += [k for k in request if k in enforced]
            fmt = request.get("response_format", {})
            json_required = isinstance(fmt, dict) and fmt.get("type") == "json_object"
            if json_required:
                row["enforced"].append("response_format")
        else:
            for key, value in request.items():
                category = "honoured"
                if key in ("model", "messages"):
                    pass
                elif key == "stream":
                    if type(value) is not bool:
                        raise unsupported(key, "must be a boolean")
                    category = "enforced"
                elif key == "stream_options":
                    if (
                        not isinstance(value, dict)
                        or set(value) - {"include_usage"}
                        or type(value.get("include_usage", False)) is not bool
                    ):
                        raise unsupported(key, "only include_usage boolean is supported")
                    category = "enforced"
                elif key == "response_format":
                    if not isinstance(value, dict) or value.get("type") not in (
                        "json_object",
                        "json_schema",
                    ):
                        raise unsupported(key, "only json_object and json_schema are supported")
                    if value["type"] == "json_schema":
                        detail = value.get("json_schema")
                        if not isinstance(detail, dict) or not isinstance(
                            detail.get("schema"), dict
                        ):
                            raise unsupported(key, "json_schema.schema must be an object")
                        schema = detail["schema"]
                    json_required = True
                    category = "enforced"
                elif key == "reasoning_effort":
                    if value not in ("low", "medium", "high"):
                        raise unsupported(key, "must be low, medium or high")
                elif (
                    key == "n"
                    and type(value) is int
                    and value == 1
                    or key in ("frequency_penalty", "presence_penalty")
                    and value == 0
                ):
                    pass
                elif key in ("max_tokens", "max_completion_tokens") and value is None:
                    continue
                elif key in (
                    "temperature",
                    "top_p",
                    "seed",
                    "frequency_penalty",
                    "presence_penalty",
                    "max_tokens",
                    "max_completion_tokens",
                ):
                    if key not in self.settings.accept_unhonoured:
                        raise unsupported(key, "codex exec cannot honour this parameter")
                    category = "waived"
                else:
                    raise unsupported(key, "parameter is not supported by the codex route")
                row[category].append(key)
        messages = request.get("messages")
        if not isinstance(messages, list) or not messages:
            if api:
                return ChatPlan(
                    "" if messages == [] else json.dumps(messages),
                    "",
                    effort,
                    schema,
                    json_required,
                )
            raise unsupported("messages", "must be a nonempty list")
        systems: list[str] = []
        conversation: list[tuple[str, str]] = []
        for message in messages:
            if not isinstance(message, dict) or not isinstance(message.get("role"), str):
                if api:
                    return ChatPlan(json.dumps(messages), "", effort, schema, json_required)
                raise unsupported("messages", "each message needs a role and text content")
            if not api and set(message) - {"role", "content"}:
                raise unsupported(
                    "messages", "message fields other than role and content cannot be honoured"
                )
            role, content = message["role"], message.get("content")
            if isinstance(content, list) and not api:
                if any(
                    not isinstance(part, dict)
                    or set(part) != {"type", "text"}
                    or part.get("type") != "text"
                    or not isinstance(part.get("text"), str)
                    for part in content
                ):
                    raise unsupported("messages", "only text parts can be honoured")
                content = "".join(part["text"] for part in content)
            if not isinstance(content, str):
                if not api:
                    raise unsupported("messages", "content must be text")
                content = json.dumps(content)
            if role == "system":
                systems.append(content)
            else:
                conversation.append((role, content))
        if not systems and not api:
            raise unsupported("messages", "codex route needs a system message")
        if len(conversation) == 1 and conversation[0][0] == "user":
            prompt = conversation[0][1]
        else:
            prompt = "".join(f"[{role}]\n{content}\n" for role, content in conversation)
            if not api:
                row["enforced"].append("messages_rendered_as_transcript")
        return ChatPlan(prompt, "\n\n".join(systems), effort, schema, json_required)

    @contextmanager
    def slot(self, row: dict[str, Any]) -> Iterator[None]:
        start = time.monotonic()
        acquired = self.slots.acquire(timeout=self.settings.queue_timeout)
        row["queue_ms"] += (time.monotonic() - start) * 1000
        if not acquired:
            raise GatewayError(503, "gateway_busy", "timed out waiting for a model slot")
        try:
            yield
        finally:
            self.slots.release()

    def chat(self, request: dict[str, Any]) -> dict[str, Any]:
        row = self.record("/v1/chat/completions", request)
        start = time.monotonic()
        prompt = reply = instructions = ""
        try:
            plan = self.chat_plan(request, row)
            prompt, instructions = plan.prompt, plan.instructions
            row.update(
                effort=plan.effort,
                prompt_sha256=digest(prompt),
                prompt_chars=len(prompt),
                total_prompt_chars=len(prompt) + len(instructions),
            )
            json_failures = 0
            timeout_retry = False
            while True:
                with self.slot(row):
                    reserve = 0.0
                    if self.settings.chat_route == "api":
                        s = self.settings
                        assert (
                            s.api_price_in_per_mtok is not None
                            and s.api_price_out_per_mtok is not None
                        )
                        reserve = (
                            (len(prompt) + len(plan.instructions)) / 4 * s.api_price_in_per_mtok
                            + s.api_reserve_output_tokens * s.api_price_out_per_mtok
                        ) / 1e6
                    ticket = self.budget.reserve(reserve)
                    row["attempts"] += 1
                    row["timeout_retry_attempts"] += int(timeout_retry)
                    timeout_retry = False
                    row["usd"] += reserve
                    row["router_session_sent"] = (
                        self.settings.chat_route == "api" and not self.settings.no_router_session
                    )
                    try:
                        result = self.chat_backend.complete(
                            request, prompt, plan.instructions, plan.effort, plan.schema
                        )
                    except GatewayError as exc:
                        # The reservation stays charged: a provider may bill an abandoned call.
                        usage_impl.record_attempt(row, error=exc.code, reserved_usd=reserve)
                        row["provider_errors"].append(exc.code)
                        retried = len(row["provider_errors"]) <= self.settings.provider_retries
                        if exc.code in PROVIDER_RETRYABLE and retried:
                            timeout_retry = exc.code == "provider_timeout"
                            continue
                        raise
                    usage_impl.record_attempt(row, result)
                    self.budget.settle(ticket, result.usd)
                    row["usd"] += result.usd - reserve
                    if result.estimated_usd is not None:
                        row["estimated_usd"] = (row["estimated_usd"] or 0.0) + result.estimated_usd
                reply = result.text
                row.update(
                    model_used=result.model,
                    tool_events=result.tool_events,
                    reply_sha256=digest(reply),
                    reply_chars=len(reply),
                )
                for field in (
                    "prompt_tokens",
                    "cached_tokens",
                    "completion_tokens",
                    "reasoning_tokens",
                ):
                    value = getattr(result, field)
                    if value is not None:
                        row[field] = (row[field] or 0) + value
                if plan.json_required:
                    try:
                        row["json_valid"] = isinstance(json.loads(reply), dict)
                    except ValueError:
                        row["json_valid"] = False
                    if not row["json_valid"]:
                        json_failures += 1
                        if json_failures > self.settings.json_retries:
                            break
                        continue
                return (
                    result.response
                    if result.response is not None
                    else {
                        "id": "chatcmpl-" + secrets.token_hex(12),
                        "object": "chat.completion",
                        "created": int(time.time()),
                        "model": result.model,
                        "choices": [
                            {
                                "index": 0,
                                "message": {"role": "assistant", "content": reply},
                                "finish_reason": "stop",
                            }
                        ],
                        "usage": {
                            "prompt_tokens": result.prompt_tokens,
                            "completion_tokens": result.completion_tokens,
                            "total_tokens": (
                                result.prompt_tokens + result.completion_tokens
                                if result.prompt_tokens is not None
                                and result.completion_tokens is not None
                                else None
                            ),
                        },
                    }
                )
            raise GatewayError(502, "invalid_json_from_model", "model did not return a JSON object")
        except GatewayError as exc:
            row.update(status=exc.status, error_code=exc.code, tool_events=exc.tool_events)
            if exc.param:
                row["refused"].append(exc.param)
            raise
        finally:
            row["latency_ms"] = (time.monotonic() - start) * 1000
            self.log(row, prompt, reply, instructions)

    def chunked(self, inputs: list[str], row: dict[str, Any]) -> tuple[list[str], list[int]]:
        return embeddings_impl.chunked(self, inputs, row)

    def embedding_attempt(self, inputs: list[str], row: dict[str, Any]) -> EmbeddingResult:
        return embeddings_impl.embedding_attempt(self, inputs, row)

    def embeddings(self, request: dict[str, Any]) -> dict[str, Any]:
        return embeddings_impl.cached_embeddings(self, request)


def sse_chunks(response: dict[str, Any], include_usage: bool) -> Iterator[bytes]:
    base = {key: response[key] for key in ("id", "created", "model")}
    base["object"] = "chat.completion.chunk"
    for delta, finish in (
        ({"role": "assistant", "content": response["choices"][0]["message"]["content"]}, None),
        ({}, "stop"),
    ):
        chunk = {**base, "choices": [{"index": 0, "delta": delta, "finish_reason": finish}]}
        yield ("data: " + json.dumps(chunk) + "\n\n").encode()
    if include_usage:
        yield (
            "data: " + json.dumps({**base, "choices": [], "usage": response["usage"]}) + "\n\n"
        ).encode()
    yield b"data: [DONE]\n\n"


class GatewayServer(ThreadingHTTPServer):
    def __init__(self, port: int, gateway: Gateway, token: str) -> None:
        self.gateway = gateway
        self.token = token
        gateway.session_token = token
        super().__init__(("127.0.0.1", port), Handler)


class Handler(BaseHTTPRequestHandler):
    server: GatewayServer

    def log_message(self, format: str, *args: Any) -> None:
        """The gateway writes a structured record instead of HTTP access logs."""

    def do_GET(self) -> None:
        self.dispatch()

    do_POST = do_PUT = do_DELETE = do_PATCH = do_HEAD = do_OPTIONS = do_GET

    def dispatch(self) -> None:
        gateway = self.server.gateway
        start = time.monotonic()
        row = gateway.record(self.path, {})
        delegated = False
        response: dict[str, Any]
        try:
            if self.command == "GET" and self.path == "/health":
                response = {"status": "ok"}
            else:
                auth = self.headers.get("Authorization", "")
                if not secrets.compare_digest(auth, "Bearer " + self.server.token):
                    raise GatewayError(401, "unauthorized", "a valid bearer token is required")
                if self.command == "GET" and self.path == "/v1/models":
                    response = {
                        "object": "list",
                        "data": [
                            {"id": alias, "object": "model", "owned_by": "alpha"}
                            for alias in (
                                gateway.settings.chat_model_alias,
                                gateway.settings.embedding_model_alias,
                            )
                        ],
                    }
                elif self.command == "POST" and self.path in (
                    "/v1/chat/completions",
                    "/v1/embeddings",
                ):
                    try:
                        length = int(self.headers.get("Content-Length", "0"))
                    except ValueError as exc:
                        raise GatewayError(
                            400, "invalid_request", "invalid Content-Length"
                        ) from exc
                    if length > MAX_BODY:
                        raise GatewayError(413, "request_too_large", "request body exceeds 4 MiB")
                    if length < 0 or self.headers.get("Transfer-Encoding"):
                        raise GatewayError(
                            400, "invalid_request", "a nonnegative Content-Length is required"
                        )
                    try:
                        request = json.loads(self.rfile.read(length))
                    except (ValueError, UnicodeError) as exc:
                        raise GatewayError(
                            400, "invalid_json", "request body must be JSON"
                        ) from exc
                    if not isinstance(request, dict):
                        raise GatewayError(400, "invalid_request", "request body must be an object")
                    delegated = True
                    response = (
                        gateway.chat(request)
                        if self.path == "/v1/chat/completions"
                        else gateway.embeddings(request)
                    )
                    if self.path == "/v1/chat/completions" and request.get("stream"):
                        options = request.get("stream_options") or {}
                        body = b"".join(sse_chunks(response, options.get("include_usage", False)))
                        self.send_body(200, body, "text/event-stream")
                        return
                else:
                    raise GatewayError(404, "not_found", "endpoint not found")
            self.send_body(200, json.dumps(response).encode(), "application/json")
        except GatewayError as exc:
            row.update(status=exc.status, error_code=exc.code)
            self.send_body(exc.status, json.dumps(exc.body()).encode(), "application/json")
        finally:
            if not delegated:
                row["latency_ms"] = (time.monotonic() - start) * 1000
                gateway.log(row)

    def send_body(self, status: int, body: bytes, content_type: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description=__doc__)
    sub = root.add_subparsers(dest="command", required=True)
    for name in ("serve", "status"):
        p = sub.add_parser(name)
        p.add_argument("--data-dir", type=Path, required=True)
        p.add_argument("--run-id", required=name == "serve", default="")
        p.add_argument("--run-max-calls", type=int, default=60)
        p.add_argument("--month-max-calls", type=int, default=3000)
        p.add_argument("--month-max-usd", type=float, default=50)
        p.add_argument("--run-max-usd", type=float, default=10)
        if name == "status":
            continue
        p.add_argument("--port", type=int, default=0)
        p.add_argument("--chat-route", choices=("codex", "api", "fake"), default="codex")
        p.add_argument(
            "--embedding-route", choices=("local", "provider", "ollama", "fake"), default="local"
        )
        p.add_argument("--provider-embed-model")
        p.add_argument("--provider-embed-usd-per-mtok", type=float)
        p.add_argument("--chat-model-alias", default="alpha-chat")
        p.add_argument("--embedding-model-alias", default="alpha-embed")
        p.add_argument("--codex-bin", default="codex")
        p.add_argument("--codex-model", default="gpt-6.1-sol")
        p.add_argument("--codex-effort", choices=("low", "medium", "high"), default="medium")
        p.add_argument("--codex-timeout", type=float, default=900)
        p.add_argument("--json-retries", type=int, default=2)
        p.add_argument("--api-timeout", type=float, default=180)
        p.add_argument("--provider-retries", type=int, default=1)
        p.add_argument("--coding-reasoning-tokens", type=int, default=None)
        p.add_argument("--embed-max-chars", type=int, default=2000)
        p.add_argument("--accept-unhonoured", default="")
        p.add_argument("--api-model")
        p.add_argument("--api-price-in-per-mtok", type=float)
        p.add_argument("--api-price-out-per-mtok", type=float)
        p.add_argument("--api-reserve-output-tokens", type=int, default=4096)
        p.add_argument("--api-openrouter", action="store_true")
        p.add_argument("--no-router-session", action="store_true")
        p.add_argument("--ollama-url", default="http://127.0.0.1:11434")
        p.add_argument("--ollama-embed-model", default="nomic-embed-text")
        p.add_argument("--max-concurrency", type=int, default=2)
        p.add_argument("--queue-timeout", type=float, default=600)
        p.add_argument("--log-content", action="store_true")
    return root


def main(argv: list[str] | None = None) -> int:
    cli = parser()
    parsed = cli.parse_args(argv)
    options = {
        field.name: getattr(parsed, field.name)
        for field in fields(Settings)
        if hasattr(parsed, field.name)
    }
    command = parsed.command
    port = getattr(parsed, "port", 0)
    if "accept_unhonoured" in options:
        options["accept_unhonoured"] = tuple(filter(None, options["accept_unhonoured"].split(",")))
    try:
        settings = Settings(**options)
        settings.validate()
        if command == "status":
            state = Budget(settings).status()
            state["caps"] = {
                key: getattr(settings, key)
                for key in ("run_max_calls", "month_max_calls", "month_max_usd", "run_max_usd")
            }
            print(json.dumps(state))
            return 0
        gateway = Gateway(settings)
        token = secrets.token_urlsafe(32)
        with GatewayServer(port, gateway, token) as server:
            actual_port = server.server_address[1]
            # Runs share one state folder so the monthly cap covers them all; each gateway also
            # publishes under its own pid so a launcher finds its own when several start at once.
            latest = settings.state_dir / "session.json"
            session = settings.state_dir / f"session-{os.getpid()}.json"
            session_data = dict(
                port=actual_port,
                token=token,
                pid=os.getpid(),
                base_url=f"http://127.0.0.1:{actual_port}",
                chat_route=settings.chat_route,
                chat_model_alias=settings.chat_model_alias,
                embedding_model_alias=settings.embedding_model_alias,
                started_at=now(),
            )
            try:
                for path in (session, latest):
                    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
                    os.fchmod(fd, 0o600)
                    with os.fdopen(fd, "w") as file:
                        json.dump(session_data, file)

                def stop(signum: int, frame: Any) -> None:
                    raise KeyboardInterrupt

                previous = signal.signal(signal.SIGTERM, stop)
                try:
                    server.serve_forever()
                except KeyboardInterrupt:
                    return 0
                finally:
                    signal.signal(signal.SIGTERM, previous)
            finally:
                session.unlink(missing_ok=True)
                # Remove the shared pointer only while it is still ours, never another run's.
                try:
                    if json.loads(latest.read_text()).get("pid") == os.getpid():
                        latest.unlink(missing_ok=True)
                except (OSError, ValueError):
                    pass
    except (ValueError, OSError, GatewayError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
