"""Generic job classification: every served root is classified; nothing real is ``unknown``."""

from __future__ import annotations

import pytest
import typer
from typer.main import get_group

from alpha_cli.catalog import classify_generic_command
from alpha_cli.main import app


def test_empty_generic_command_is_unknown() -> None:
    assert classify_generic_command([]) == "unknown"


@pytest.mark.parametrize(
    ("argv", "expected"),
    [
        (["ledger", "summary"], "safe"),
        (["partner", "selftest"], "safe"),
        (["context", "list"], "safe"),
        (["context", "show-edgar"], "safe"),
        (["context", "show-binance"], "safe"),
        (["context", "pull-edgar"], "owner_only"),
        (["context", "pull-binance"], "owner_only"),
        (["context", "show", "X"], "safe"),
        (["context", "window"], "safe"),
        (["context"], "owner_only"),
        (["context", "unknown"], "owner_only"),
        (["context", "pull"], "owner_only"),
        (["crypto-data", "catalog"], "safe"),
        (["crypto-data", "storage-verify"], "safe"),
        (["crypto-data", "acquire"], "owner_only"),
        (["crypto-data", "asset-master-create"], "owner_only"),
        (["crypto-data"], "owner_only"),
        (["quantpad-data", "verify"], "unknown"),
        (["quantpad-data", "archive"], "unknown"),
        (["provider", "check", "tiingo"], "owner_only"),
        (["strategy-candidate", "paper-preflight"], "safe"),
        (["strategy-candidate", "run"], "empirical"),
        (["labels", "barrier"], "empirical"),
        (["labels", "weights"], "empirical"),
        (["labels", "importance"], "empirical"),
        (["chart", "overlays"], "safe"),
        (["rules", "save"], "safe"),
        (["scan", "check"], "safe"),
        (["follow", "list"], "safe"),
        (["follow", "show", "x"], "safe"),
        (["follow", "verify", "x"], "safe"),
        (["follow", "today"], "safe"),
        (["follow", "update", "--all"], "owner_only"),
        (["follow", "start"], "owner_only"),
        (["follow", "stop", "x"], "owner_only"),
        (["follow"], "owner_only"),
        (["home", "backup", "/tmp/x"], "owner_only"),
        (["home", "verify-backup", "/tmp/x.tar"], "owner_only"),
        (["tool", "run"], "empirical"),
        (["setup", "find"], "empirical"),
        (["setup", "study"], "empirical"),
        (["setup", "trade"], "empirical"),
        (["data", "audit"], "safe"),
        (["data", "repair"], "owner_only"),
        (["paper", "run"], "owner_only"),
        (["pricing", "price"], "unknown"),
        (["screener", "run"], "unknown"),
    ],
)
def test_roots_classify_by_subcommand(argv: list[str], expected: str) -> None:
    assert classify_generic_command(argv) == expected


def _subcommands(root: str) -> list[str]:
    group = get_group(app)
    sub = group.commands[root]
    return sorted(sub.commands) if isinstance(sub, typer.core.TyperGroup) else []


@pytest.mark.parametrize(
    "root", ["context", "crypto-data", "provider", "strategy-candidate", "data", "paper"]
)
def test_every_served_subcommand_of_a_classified_root_is_not_unknown(root: str) -> None:
    """An unlisted verb must fail this test rather than silently classify ``unknown``."""
    names = _subcommands(root)
    assert names, f"{root} serves no subcommands"
    for name in names:
        assert classify_generic_command([root, name]) != "unknown", f"{root} {name}"


def test_every_served_root_is_classified() -> None:
    """The web launcher refuses ``unknown``; a new root must be classified, not silently refused
    (or, before that refusal, launched without the run context empirical commands need)."""
    roots = sorted(get_group(app).commands)
    assert roots
    for root in roots:
        assert classify_generic_command([root, "x"]) != "unknown", root
