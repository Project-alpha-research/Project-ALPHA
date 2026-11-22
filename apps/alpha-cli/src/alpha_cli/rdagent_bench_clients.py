"""The bench's two clients: a fake one for tests, and one that posts to a local gateway."""

from __future__ import annotations

import json
import os
import time
import urllib.parse
import urllib.request
from collections.abc import Mapping
from typing import Any

from alpha_cli.rdagent_bench_model import TOKEN_VARIABLE, BenchError, Reply, StoredPrompt

LOCAL_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})


class FakeClient:
    """Deterministic outputs from a fixture: {model: {prompt id: [reply, ...]}}. No network."""

    def __init__(self, fixture: Mapping[str, Any]) -> None:
        self.fixture = fixture
        self.calls = 0

    def complete(self, model: str, prompt: StoredPrompt, sample: int) -> Reply:
        try:
            raw = self.fixture[model][prompt.id][sample % len(self.fixture[model][prompt.id])]
        except (KeyError, IndexError, ZeroDivisionError) as error:
            raise BenchError(f"The fixture has no reply for {model} / {prompt.id}.") from error
        self.calls += 1
        return Reply(
            text=str(raw["text"]),
            provider=raw.get("provider"),
            prompt_tokens=raw.get("prompt_tokens"),
            completion_tokens=raw.get("completion_tokens"),
            latency_ms=raw.get("latency_ms"),
            cost=raw.get("cost"),
        )


class GatewayClient:
    """Posts to a running local gateway, one gateway address per model. The token is read from
    the environment and is never stored. The gateway holds the provider pin and the call caps."""

    def __init__(self, urls: Mapping[str, str]) -> None:
        self.urls = urls
        self.token = os.environ.get(TOKEN_VARIABLE, "")

    def complete(self, model: str, prompt: StoredPrompt, sample: int) -> Reply:
        if model not in self.urls or not self.token:
            raise BenchError(f"No gateway address for '{model}', or {TOKEN_VARIABLE} is not set.")
        address = urllib.parse.urlsplit(self.urls[model])
        if address.scheme != "http" or address.hostname not in LOCAL_HOSTS:
            raise BenchError("The gateway address must be on this machine.")
        body = json.dumps({"model": model, "messages": prompt.messages}).encode()
        request = urllib.request.Request(
            self.urls[model].rstrip("/") + "/v1/chat/completions",
            data=body,
            headers={"Authorization": f"Bearer {self.token}", "Content-Type": "application/json"},
        )
        started = time.monotonic()
        with urllib.request.urlopen(request, timeout=900) as response:
            data = json.loads(response.read())
        usage = data.get("usage") or {}
        return Reply(
            text=str(data["choices"][0]["message"]["content"]),
            provider=data.get("provider"),
            prompt_tokens=usage.get("prompt_tokens"),
            completion_tokens=usage.get("completion_tokens"),
            latency_ms=(time.monotonic() - started) * 1000,
            cost=usage.get("cost"),
        )
