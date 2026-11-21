"""Actionable error envelopes for the rule-test command spine."""

from __future__ import annotations

from pathlib import Path
from typing import Any, NoReturn

import typer

from alpha_cli._cli_json import emit


class SpineError(ValueError):
    def __init__(self, code: str, message: str, next_step: str, known: list[str] | None = None):
        super().__init__(message)
        self.payload: dict[str, Any] = {
            "code": code,
            "message": message,
            "known": known,
            "next": next_step,
        }


def fail(error: SpineError, json_out: bool) -> NoReturn:
    emit({"error": error.payload}, json_out=json_out, fallback=f"{error}\n{error.payload['next']}")
    raise typer.Exit(1)


def unreadable_file(path: Path, exc: OSError | UnicodeError) -> SpineError:
    return SpineError(
        "UNREADABLE_FILE",
        f"Cannot read answer file {path}: {exc}",
        "Run alpha results check with a readable UTF-8 Markdown or plain-text file.",
    )


def test_error(message: str, stores: list[str] | None = None) -> SpineError:
    if "unknown rule kind" in message:
        return SpineError(
            "UNKNOWN_RULE",
            message,
            "Run alpha test with a known --rule kind.",
            ["ma_cross", "breakout", "tsmom"],
        )
    if "not built yet" in message or "reads volume" in message or "price level" in message:
        return SpineError(
            "RULE_NOT_SUPPORTED",
            message,
            "Edit the rule so it stays long or flat, uses no volume and meets no fixed price.",
        )
    if "not found" in message or "unknown store" in message:
        return SpineError(
            "UNKNOWN_ASSET", message, "Run alpha test with an asset in a known store.", stores
        )
    if "bars" in message and ("need" in message or "requires at least" in message):
        return SpineError(
            "TOO_FEW_BARS", message, "Run alpha test on an asset with more stored history."
        )
    return SpineError(
        "TEST_FAILED",
        message,
        "Run alpha test again after correcting the reported input or data error.",
    )


def tool_error(exc: Exception, stores: list[str] | None = None) -> SpineError:
    """Map a failure inside ``alpha tool`` to its stable code and next step."""
    if isinstance(exc, SpineError):
        return exc
    message = str(exc)
    if "not found" in message or "unknown store" in message:
        return SpineError(
            "UNKNOWN_ASSET",
            message,
            "Run alpha tool again with a symbol held in a known store (SYMBOL or SYMBOL@store).",
            stores,
        )
    if "at least" in message and ("bars" in message or "points" in message):
        return SpineError(
            "TOO_FEW_BARS",
            message,
            "Run alpha tool on a run, benchmark or market with more shared history.",
        )
    return SpineError(
        "TOOL_FAILED",
        message,
        "Run alpha tool again after correcting the reported input or data error.",
    )


def setup_error(exc: Exception, stores: list[str] | None = None) -> SpineError:
    """Map setup input and asset failures to the command's stable envelope."""
    if isinstance(exc, SpineError):
        return exc
    message = str(exc)
    if "not found" in message or "unknown store" in message:
        return SpineError(
            "UNKNOWN_ASSET",
            message,
            "Run alpha setup find with an asset in a known store.",
            stores,
        )
    return SpineError(
        "FIND_FAILED",
        message,
        "Run alpha setup find again after correcting the reported input or data error.",
    )


def study_error(exc: Exception) -> SpineError:
    """Preserve specific study failures and fail loud on computation/publication errors."""
    return (
        exc
        if isinstance(exc, SpineError)
        else SpineError(
            "STUDY_FAILED",
            str(exc),
            "Correct the reported data or study error, then run alpha setup study again.",
        )
    )
