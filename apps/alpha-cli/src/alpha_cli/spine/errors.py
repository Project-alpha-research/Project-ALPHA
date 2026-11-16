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
