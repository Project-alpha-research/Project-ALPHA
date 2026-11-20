"""MCP front-door tools: where the project stands, ideas, the library, finding a check, today.

Each tool relays ONE read-mostly ``alpha`` command with ``--json``. Arguments are typed and
validated before an argv is built; free text is one argv element and never starts with ``-``,
so no value can act as an option. The command's own JSON, including its error JSON, comes back
unchanged. Two tools (``idea_new``, ``library_card``) write one small note file in the data
directory: a card is a note, and nothing is tested or approved. There is no tool to start, stop
or update a paper follow, to run the nightly job, to run RD-Agent, to pull data or to import a
catalogue: those are owner-only commands. This module never reads the follow store.
The follow tools are named ``follows_*``: they relay and do not read.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from typing import Any, Final, Literal

from mcp.server.fastmcp import FastMCP

from alpha_core.config import AlphaSettings
from alpha_mcp import _invoke

_TIMEOUT_S: Final = 60.0
_MAX_WORDS: Final = 300
_MAX_ENTRY: Final = 1_000_000
_HEX_ID = re.compile(r"[0-9a-f]{4,16}")
_LIBRARY_ID = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")
_NOTE = " Results are research records, not advice."


def _words(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > _MAX_WORDS:
        raise ValueError(f"{label} must be non-empty text of at most {_MAX_WORDS} characters")
    if value.startswith("-") or value.strip().startswith("-"):
        raise ValueError(f"{label} must not start with '-'")
    if any(char in value for char in ("\x00", "\r", "\n")):
        raise ValueError(f"{label} contains a forbidden control character")
    return value


def _hex_id(value: object, label: str) -> str:
    if not isinstance(value, str) or _HEX_ID.fullmatch(value) is None:
        raise ValueError(f"{label} must be 4 to 16 lower-case hex characters")
    return value


def _library_id(value: object) -> str:
    if not isinstance(value, str) or len(value) > 64 or _LIBRARY_ID.fullmatch(value) is None:
        raise ValueError(
            "record_id must be lower-case words joined by dashes, at most 64 characters"
        )
    return value


def _relay(args: list[str]) -> Any:
    return _invoke.run_json_relay(
        [*args, "--json"], data_dir=AlphaSettings().data_dir, timeout_seconds=_TIMEOUT_S
    )


def next_step() -> Any:
    """Run `alpha next`: say where the project stands and what can be done now. Read-only.

    Call this first. Returns JSON with the paths you can take.
    Results are research records, not advice.
    """
    return _relay(["next"])


def idea_list() -> Any:
    """Run `alpha idea list`: list every idea card and whether a test is linked to it. Read-only.

    Returns JSON. Results are research records, not advice.
    """
    return _relay(["idea", "list"])


def idea_show(card_id: str) -> Any:
    """Run `alpha idea show`: read one idea card and see which fields are not stated. Read-only.

    Returns JSON. Results are research records, not advice.
    """
    return _relay(["idea", "show", _hex_id(card_id, "card_id")])


def idea_file(card_id: str) -> Any:
    """Run `alpha idea file`: read one idea's whole story: card, map, readings, counts, open points.

    Read-only. Returns JSON. Results are research records, not advice.
    """
    return _relay(["idea", "file", _hex_id(card_id, "card_id")])


def idea_new(
    claim: str | None = None,
    mechanism: str | None = None,
    other_side: str | None = None,
    disproved_by: str | None = None,
    baseline: str | None = None,
    signal_forms: str | None = None,
    held_for: str | None = None,
    how_often: str | None = None,
    edge_lasts: str | None = None,
    supersedes: str | None = None,
) -> Any:
    """Run `alpha idea new`: save an idea card from the owner's own words. Writes one note file.

    A card is a note: nothing is tested or approved. Any field may stay empty.
    Returns JSON with the card id. Results are research records, not advice.
    """
    fields = (
        ("--claim", claim),
        ("--mechanism", mechanism),
        ("--other-side", other_side),
        ("--disproved-by", disproved_by),
        ("--baseline", baseline),
        ("--signal-forms", signal_forms),
        ("--held-for", held_for),
        ("--how-often", how_often),
        ("--edge-lasts", edge_lasts),
    )
    args = ["idea", "new"]
    for flag, value in fields:
        if value is not None:
            args += [flag, _words(value, flag.removeprefix("--").replace("-", "_"))]
    if supersedes is not None:
        args += ["--supersedes", _hex_id(supersedes, "supersedes")]
    return _relay(args)


def library_list(
    market: Literal["us-equities", "crypto", "futures", "multi"] | None = None,
    tier: Literal["checked", "imported", "all"] | None = None,
) -> Any:
    """Run `alpha library list`: list published ideas, by market and tier. Read-only.

    Returns JSON. Results are research records, not advice.
    """
    if market is not None and market not in ("us-equities", "crypto", "futures", "multi"):
        raise ValueError("market must be us-equities, crypto, futures or multi")
    if tier is not None and tier not in ("checked", "imported", "all"):
        raise ValueError("tier must be checked, imported or all")
    args = ["library", "list"]
    args += ["--market", market] if market is not None else []
    args += ["--tier", tier] if tier is not None else []
    return _relay(args)


def library_show(record_id: str) -> Any:
    """Run `alpha library show`: read one published idea and the idea cards made from it.

    Read-only. Returns JSON. Results are research records, not advice.
    """
    return _relay(["library", "show", _library_id(record_id)])


def library_card(record_id: str) -> Any:
    """Run `alpha library card`: make an idea card from a published idea. Writes one note file.

    Nothing is tested and no ledger row is written. Returns JSON.
    Results are research records, not advice.
    """
    return _relay(["library", "card", _library_id(record_id)])


def tool_find(words: str) -> Any:
    """Run `alpha tool find`: find checks from a plain question, with cost and command.

    Read-only. Returns JSON. Results are research records, not advice.
    """
    return _relay(["tool", "find", _words(words, "words")])


def tool_situations() -> Any:
    """Run `alpha tool situations`: list each situation with its checks, cheapest first. Read-only.

    Returns JSON. Results are research records, not advice.
    """
    return _relay(["tool", "situations"])


def follows_today() -> Any:
    """Run `alpha follow today`: show what is active today, one row per paper follow. Read-only.

    Paper only; it reads journals and writes nothing. Returns JSON.
    Results are readings, not advice.
    """
    return _relay(["follow", "today"])


def follows_list() -> Any:
    """Run `alpha follow list`: list every paper follow with its state. Read-only.

    Returns JSON. Results are research records, not advice.
    """
    return _relay(["follow", "list"])


def follows_show(follow_id: str) -> Any:
    """Run `alpha follow show`: read one paper follow's frozen record, entries and chain head.

    Read-only. Returns JSON. Results are research records, not advice.
    """
    return _relay(["follow", "show", _hex_id(follow_id, "follow_id")])


def follows_verify(follow_id: str, entry: int = 0) -> Any:
    """Run `alpha follow verify`: recompute one paper follow's hash chain. Read-only.

    With entry above 0, also returns that entry's hash. Returns JSON.
    Results are research records, not advice.
    """
    if isinstance(entry, bool) or not isinstance(entry, int) or not 0 <= entry <= _MAX_ENTRY:
        raise ValueError(f"entry must be an integer from 0 to {_MAX_ENTRY}")
    args = ["follow", "verify", _hex_id(follow_id, "follow_id")]
    return _relay([*args, "--entry", str(entry)] if entry else args)


def nightly_status() -> Any:
    """Run `alpha nightly status`: say what the last nightly run showed and whether it is ready.

    Read-only; it writes nothing and does not start a run. Returns JSON.
    Results are readings, not advice.
    """
    return _relay(["nightly", "status"])


FRONT_DOOR_TOOLS: Final[tuple[Callable[..., Any], ...]] = (
    next_step,
    idea_list,
    idea_show,
    idea_file,
    idea_new,
    library_list,
    library_show,
    library_card,
    tool_find,
    tool_situations,
    follows_today,
    follows_list,
    follows_show,
    follows_verify,
    nightly_status,
)


def register(server: FastMCP) -> None:
    """Register every front-door tool and make each one refuse any argument it does not declare."""
    manager = server._tool_manager
    for function in FRONT_DOOR_TOOLS:
        server.tool()(function)
        registered = manager.get_tool(function.__name__)
        if registered is None:
            raise RuntimeError(f"{function.__name__} was not registered")
        model = registered.fn_metadata.arg_model
        model.model_config["extra"] = "forbid"
        model.model_rebuild(force=True)
