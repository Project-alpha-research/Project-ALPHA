"""Shared plumbing for the free key-less context sources: polite HTTP client, no-revision merge."""

from __future__ import annotations

import http.client
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

import polars as pl

from alpha_core import DataError
from alpha_data.context.events import load_events
from alpha_data.context.fred import _NoRedirect

USER_AGENT = "Project-ALPHA/1.0"
TIMEOUT_SECONDS = 30
PAUSE_SECONDS = 1.0
MAX_BYTES = 64 * 1024 * 1024
type Transport = Callable[[str, Mapping[str, str], float], tuple[int, Mapping[str, str], bytes]]


def default_transport(
    url: str, headers: Mapping[str, str], timeout: float
) -> tuple[int, Mapping[str, str], bytes]:
    """The only place these sources touch the network; redirects are refused."""
    opener = urllib.request.build_opener(_NoRedirect())
    try:
        with opener.open(
            urllib.request.Request(url, headers=dict(headers)), timeout=timeout
        ) as response:
            return response.status, dict(response.headers), response.read(MAX_BYTES + 1)
    except urllib.error.HTTPError as error:
        with error:
            return error.code, dict(error.headers), error.read(MAX_BYTES + 1)


class Client:
    """Sequential client: generic User-Agent, a timeout, and a pause between request starts."""

    def __init__(
        self,
        transport: Transport | None = None,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._transport = transport
        self._clock, self._sleep = clock, sleep
        self._last: float | None = None

    def get(self, url: str, label: str) -> tuple[int, bytes]:
        if self._last is not None:
            delay = PAUSE_SECONDS - (self._clock() - self._last)
            if delay > 0:
                self._sleep(delay)
        self._last = self._clock()
        send = self._transport or default_transport
        try:
            status, _, raw = send(url, {"User-Agent": USER_AGENT}, TIMEOUT_SECONDS)
        except (ValueError, http.client.HTTPException, urllib.error.URLError, OSError) as exc:
            raise DataError(
                f"{label} is offline or unreachable ({type(exc).__name__}); nothing was stored"
            ) from None
        if len(raw) > MAX_BYTES:
            raise DataError(f"{label} response exceeds 64 MiB")
        return status, raw


def merge_without_revision(
    path: Path,
    incoming: pl.DataFrame,
    *,
    source: str,
    schema: dict[str, Any],
    key: str,
    label: str,
) -> pl.DataFrame:
    """Stored rows plus new rows; a changed value for a stored period is refused, never replaced."""
    if path.exists() or path.with_suffix(".json").exists():
        stored = load_events(path, source=source, schema=schema)
        merged = pl.concat([stored, incoming]).unique(maintain_order=True)
    else:
        merged = incoming.unique(maintain_order=True)
    clash = merged.filter(pl.col(key).is_duplicated())
    if clash.height:
        raise DataError(f"revised {label} at {key} {clash[key][0]}; stored values were kept")
    return merged.sort(key)


def check_ascending(values: list[Any], field: str) -> None:
    """Typed errors for repeated or out-of-order period values."""
    for before, after in zip(values, values[1:], strict=False):
        if after == before:
            raise DataError(f"duplicate {field} {after}")
        if after < before:
            raise DataError(f"disordered {field}: {after} follows {before}")
