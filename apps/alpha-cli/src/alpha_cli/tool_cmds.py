"""Discover and run registered investigation tools on recorded targets."""

from __future__ import annotations

import json
import re
import sys
from contextlib import redirect_stdout
from dataclasses import asdict
from typing import Annotated, Any

import typer

from alpha_cli._cli_json import emit
from alpha_cli.spine.errors import SpineError, fail, tool_error
from alpha_cli.toolbox import declarations, find
from alpha_cli.toolbox.contract import ToolSpec
from alpha_cli.toolbox.registry import SPECS, get
from alpha_cli.toolbox.sets import SETS
from alpha_cli.toolbox.situations import SITUATIONS
from alpha_core import DataError
from alpha_core.config import AlphaSettings

tool_app = typer.Typer(help="Discover and run investigation tools.", no_args_is_help=True)
_JSON = typer.Option(False, "--json", help="Emit JSON.")


def _card(spec: ToolSpec) -> dict[str, Any]:
    return {
        "id": spec.id,
        "version": spec.version,
        "family": spec.family,
        "kind": spec.kind,
        "question": spec.question,
        "answers": spec.answers,
        "situations": spec.situations,
        "needs": spec.needs,
        "outputs": [asdict(o) for o in spec.outputs],
        "params": [
            {
                **asdict(p),
                "type": p.type.__name__,
                "allowed": list(p.allowed) if p.allowed is not None else None,
            }
            for p in spec.params
        ],
        "cost": spec.cost,
        "seeded": spec.seeded,
        "reading": spec.reading,
        "caveats": spec.caveats,
        "look": spec.look,
        "time_safety": spec.time_safety,
        "reference": spec.reference,
        "poison_test": spec.poison_test,
        "runnable": spec.compute is not None,
    }


@tool_app.command("list")
def list_tools(
    target: str | None = typer.Option(None, "--for"),
    search: str = "",
    family: str | None = None,
    kind: str | None = None,
    json_out: bool = _JSON,
) -> None:
    """Find tools by target, question, family or kind."""
    from alpha_cli.toolbox.inputs import resolve

    try:
        kinds = resolve(AlphaSettings().data_dir, target).kinds if target else None
    except (ValueError, DataError, OSError) as exc:
        fail(tool_error(exc), json_out)
    matches = []
    words = set(re.findall(r"[a-z0-9]+", search.casefold()))
    for spec in SPECS:
        if (
            (kinds is not None and not set(spec.needs) <= kinds)
            or (family and family != spec.family)
            or (kind and kind != spec.kind)
        ):
            continue
        corpus = " ".join([spec.question, spec.family, spec.id, *(o.gloss for o in spec.outputs)])
        score = len(words.intersection(re.findall(r"[a-z0-9]+", corpus.lower())))
        if score or not words:
            matches.append((-score, spec.id, _card(spec)))
    cards = [card for _, _, card in sorted(matches)]
    emit(cards, json_out=json_out, fallback="\n".join(f"{c['id']}  {c['question']}" for c in cards))


@tool_app.command("describe")
def describe(tool_id: str, json_out: bool = _JSON) -> None:
    """Read a tool's question, inputs, parameters, outputs and caveats."""
    try:
        spec = get(tool_id)
    except SpineError as exc:
        fail(exc, json_out)
    lines = [
        f"{spec.id} (v{spec.version})",
        spec.question,
        f"{spec.kind} · {spec.look} · {spec.cost} · {spec.time_safety}",
        f"Inputs  {', '.join(spec.needs)}",
    ]
    for param in spec.params:
        allowed = f"  Choices {', '.join(map(str, param.allowed))}." if param.allowed else ""
        lines.append(
            f"{param.name} ({param.type.__name__}, default {param.default})  {param.gloss}{allowed}"
        )
    lines.extend(f"{o.label} ({spec.id}.{o.key}, {o.unit})  {o.gloss}" for o in spec.outputs)
    lines.extend([*spec.caveats, f"Reference  {spec.reference}"])
    card = "\n".join(lines)
    emit({**_card(spec), "card": card}, json_out=json_out, fallback=card)


def _printed(output: dict[str, Any]) -> dict[str, Any]:
    return {**output, "result": {k: v for k, v in output["result"].items() if k != "series"}}


def _text(output: dict[str, Any]) -> str:
    spec = get(output["tool"])
    lines = [f"{spec.id} [{', '.join(output['labels'])}]", output["reading"]]
    for fact, field in zip(output["facts"], spec.outputs, strict=True):
        value = fact["value"] if fact["reason"] is None else f"unavailable ({fact['reason']})"
        lines.append(f"  {fact['metric']} = {value}  {field.gloss}")
    lines.extend(f["detail"] for f in output["result"].get("flags", []))
    lines.extend(f"Change on {b['date'][:10]}" for b in output["result"].get("breaks", []))
    join = output["result"].get("join")
    if join and (join["run_bars_dropped"] or join["other_bars_dropped"]):
        lines.append(
            f"Matching dates dropped {join['run_bars_dropped']} run bars and "
            f"{join['other_bars_dropped']} bars of the other asset."
        )
    return "\n".join([*lines, output["basis"], *spec.caveats, f"Saved: {output['file']}"])


@tool_app.command("run")
def run_tool(
    tool_id: str,
    target: Annotated[str, typer.Argument(help="The run id (or use --run).")] = "",
    param: Annotated[list[str] | None, typer.Option("--param")] = None,
    seed: int = 0,
    run_id: Annotated[str, typer.Option("--run", help="The run id; the same as the target.")] = "",
    json_out: bool = _JSON,
) -> None:
    """Run one tool with repeatable key=value parameters."""
    from alpha_cli.toolbox.runner import run

    try:
        if bool(target) == bool(run_id):
            raise SpineError(
                "TOOL_TARGET",
                "Name the run once: as the id after the tool name, or with --run.",
                "Example: alpha tool run <tool> --run <run id>",
            )
        target = target or run_id
        with redirect_stdout(sys.stderr):
            output = run(AlphaSettings().data_dir, tool_id, target, param, seed)
    except SpineError as exc:
        fail(exc, json_out)
    emit(_printed(output), json_out=json_out, fallback=_text(output))


@tool_app.command("run-set")
def run_set(name: str, target: str, json_out: bool = _JSON) -> None:
    """Run each member of a predeclared set and report every outcome."""
    from alpha_cli.toolbox.runner import run

    if name not in SETS:
        fail(
            SpineError("UNKNOWN_SET", f"Unknown set {name!r}.", "Choose a known set.", list(SETS)),
            json_out,
        )
    results = []
    lines = []
    failed = False
    with redirect_stdout(sys.stderr):
        for tool_id in SETS[name]:
            try:
                output = run(AlphaSettings().data_dir, tool_id, target, set_name=name)
                results.append(_printed(output))
                lines.append(_text(output))
            except SpineError as exc:
                results.append({"tool": tool_id, "error": exc.payload})
                lines.append(f"{tool_id}: {exc}")
                failed = True
    emit(results, json_out=json_out, fallback="\n".join(lines))
    if failed:
        raise typer.Exit(1)


@tool_app.command("history")
def tool_history(target: str, json_out: bool = _JSON) -> None:
    """List successful, failed and unfinished attempts in ledger order."""
    from alpha_cli.toolbox.store import history

    rows = history(AlphaSettings().data_dir, target)
    emit(rows, json_out=json_out, fallback=json.dumps(rows, indent=2))


@tool_app.command("find")
def find_tool(
    words: Annotated[str, typer.Argument(help="Your situation or question, in plain words.")],
    json_out: bool = _JSON,
) -> None:
    """Find checks from plain words: what each answers, its cost and the command to run it."""
    hits = find.find(words)
    payload = {
        "query": words,
        "matches": [asdict(hit) for hit in hits],
        "situations": dict(SITUATIONS) if not hits else None,
        "pointers": find.pointers_for(words),
    }
    emit(payload, json_out=json_out, fallback=find.render_hits(words, hits))


@tool_app.command("situations")
def situations(
    json_out: bool = _JSON,
    markdown: Annotated[bool, typer.Option("--markdown", help="Print the README table.")] = False,
) -> None:
    """List each situation with its checks, cheapest first."""
    table = {tag: [spec.id for spec in specs] for tag, specs in find.index().items()}
    emit(
        table,
        json_out=json_out,
        fallback=find.markdown_index() if markdown else find.render_index(),
    )


@tool_app.command("declare")
def declare(
    run_id: str,
    set_name: Annotated[str | None, typer.Option("--set", help="A named set to declare.")] = None,
    tools: Annotated[str, typer.Option("--tools", help="Comma-separated tool ids.")] = "",
    why: Annotated[str, typer.Option("--why", help="Why these checks, in your words.")] = "",
    json_out: bool = _JSON,
) -> None:
    """Record which checks you chose before seeing their results. Nothing is refused later."""
    names = [name.strip() for name in tools.split(",") if name.strip()]
    try:
        row = declarations.declare(
            AlphaSettings().data_dir, run_id, set_name=set_name, tools=names, why=why
        )
    except SpineError as exc:
        fail(exc, json_out)
    fallback = (
        f"Declared before any result: {', '.join(row['tools'])} on {run_id} at {row['declared_at']}"
    )
    emit(row, json_out=json_out, fallback=fallback)


@tool_app.command("results")
def results(run_id: str, json_out: bool = _JSON) -> None:
    """List the stored check results of a run, each marked declared or exploratory."""
    from alpha_cli.spine.facts import tool_outputs

    stored = tool_outputs(AlphaSettings().data_dir, run_id)
    items = [
        {
            "tool": item["tool"],
            "id": item["id"],
            "status": declarations.word_of(item["labels"] or []),
            "recorded_at": item["recorded_at"],
            "labels": item["labels"],
            "reading": item["reading"],
            "file": item["file"],
        }
        for item in stored
    ]
    counted = declarations.counts(item["labels"] or [] for item in stored)
    lines = [f"{i['tool']} [{i['status']}]  {i['reading']}" for i in items] + [counted["text"]]
    emit(
        {"run_id": run_id, "counts": counted, "results": items},
        json_out=json_out,
        fallback="\n".join(lines),
    )
