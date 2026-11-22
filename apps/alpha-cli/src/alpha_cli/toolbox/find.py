"""Find a check from plain words. Deterministic token overlap: no model, no network."""

from __future__ import annotations

import re
import textwrap
from dataclasses import dataclass

from alpha_cli.toolbox.contract import InputKind, ToolSpec
from alpha_cli.toolbox.registry import SPECS
from alpha_cli.toolbox.sets import SETS
from alpha_cli.toolbox.situations import SITUATIONS, Situation

TAG_SCORE, NAME_SCORE, WORD_SCORE = 3, 2, 1
COST_RANK = {"instant": 0, "seconds": 1, "minutes": 2}
LOOK_RANK = {"describe": 0, "test": 1, "search": 2}
STOP = frozenset(
    [
        "a",
        "an",
        "and",
        "are",
        "be",
        "could",
        "did",
        "do",
        "does",
        "for",
        "get",
        "how",
        "i",
        "if",
        "in",
        "is",
        "it",
        "its",
        "me",
        "my",
        "of",
        "on",
        "one",
        "or",
        "result",
        "results",
        "run",
        "strategy",
        "rule",
        "test",
        "check",
        "checks",
        "idea",
        "tell",
        "the",
        "this",
        "to",
        "was",
        "what",
        "when",
        "which",
        "with",
        "would",
        "you",
    ]
)
# Word start -> situations it points at. A key matches every word that begins with it.
SYNONYMS: dict[str, tuple[Situation, ...]] = {
    "overfit": ("looks-too-good", "many-tries"),
    "lucky": ("looks-too-good", "lucky-trades"),
    "luck": ("looks-too-good",),
    "fluke": ("looks-too-good",),
    "chance": ("looks-too-good",),
    "suspicious": ("looks-too-good",),
    "snoop": ("many-tries",),
    "tries": ("many-tries",),
    "trials": ("many-tries",),
    "multiple": ("many-tries",),
    "mining": ("many-tries",),
    "drop": ("drawdown",),
    "crash": ("drawdown",),
    "worst": ("drawdown",),
    "losing": ("drawdown",),
    "risk": ("risk-adjusted", "drawdown"),
    "sharpe": ("risk-adjusted", "return-range"),
    "sortino": ("risk-adjusted",),
    "range": ("return-range",),
    "interval": ("return-range",),
    "confidence": ("return-range",),
    "uncertain": ("return-range",),
    "year": ("works-only-sometimes",),
    "window": ("works-only-sometimes",),
    "period": ("works-only-sometimes",),
    "sometimes": ("works-only-sometimes",),
    "stretch": ("works-only-sometimes",),
    "regime": ("calm-or-turbulent",),
    "calm": ("calm-or-turbulent",),
    "turbulen": ("calm-or-turbulent",),
    "volatil": ("calm-or-turbulent",),
    "change": ("behaviour-change",),
    "shift": ("behaviour-change",),
    "break": ("behaviour-change",),
    "few": ("few-trades",),
    "small": ("few-trades",),
    "handful": ("lucky-trades",),
    "concentrat": ("lucky-trades",),
    "outlier": ("lucky-trades",),
    "best": ("lucky-trades",),
    "streak": ("trade-streaks",),
    "cluster": ("trade-streaks",),
    "alternat": ("trade-streaks",),
    "depend": ("trade-streaks",),
    "long": ("long-vs-short",),
    "short": ("long-vs-short",),
    "side": ("long-vs-short",),
    "cost": ("cost-fragile",),
    "fee": ("cost-fragile",),
    "slippage": ("cost-fragile",),
    "commission": ("cost-fragile",),
    "spread": ("cost-fragile",),
    "market": ("just-the-market",),
    "beta": ("just-the-market",),
    "benchmark": ("just-the-market",),
    "hold": ("just-the-market",),
    "sample": ("out-of-sample",),
    "walk": ("out-of-sample",),
    "unseen": ("out-of-sample",),
    "future": ("out-of-sample",),
    "feed": ("data-doubt",),
    "noise": ("data-doubt",),
    "gap": ("data-doubt",),
    "dirty": ("data-doubt",),
    "bet": ("bet-size",),
    "stake": ("bet-size",),
    "kelly": ("bet-size",),
    "sizing": ("bet-size",),
    "leverage": ("bet-size",),
    "tail": ("tail-loss",),
    "var": ("tail-loss",),
    "ruin": ("tail-loss",),
    "loss": ("tail-loss",),
    "history": ("enough-history",),
    "enough": ("enough-history",),
    "track": ("enough-history",),
    "trend": ("return-patterns",),
    "revers": ("return-patterns",),
    "momentum": ("return-patterns",),
    "autocorrel": ("return-patterns",),
    "random": ("return-patterns",),
    "weekday": ("weekday-month",),
    "monday": ("weekday-month",),
    "friday": ("weekday-month",),
    "month": ("weekday-month",),
    "season": ("weekday-month",),
    "calendar": ("weekday-month",),
    "tax": ("real-fills",),
    "fill": ("real-fills",),
    "realistic": ("real-fills",),
    "execution": ("real-fills",),
    "capacity": ("trade-size",),
    "liquid": ("trade-size",),
    "volume": ("trade-size",),
    "size": ("trade-size", "bet-size"),
}
# Situations with no toolbox check yet: the existing commands that do answer them.
POINTERS: dict[Situation, str] = {
    "out-of-sample": "No toolbox check yet. `alpha test` reports the out-of-sample numbers.",
    "data-doubt": "No toolbox check yet. `alpha data health <ASSET>` reports the data's faults.",
}
INPUT_WORDS: dict[InputKind, str] = {
    "run_returns": "the daily returns of a stored rule-test run",
    "run_positions": "the positions of a stored rule-test run",
    "stored_equity": "the stored equity curve of a rule-test run",
    "stored_benchmark": "the stored buy-and-hold benchmark of a rule-test run",
    "run_trades": "the stored trades of a rule-test run",
    "run_bars": "the price bars of the run's asset",
    "study_events": "the stored events of a setup study",
    "factor_panel": "a stored factor panel",
    "run_set": "several stored runs together",
    "asset_bars": "the price bars of another asset",
    "reference_factors": "the stored published factor returns (a later-published data set)",
}


@dataclass(frozen=True)
class Hit:
    tool_id: str
    score: int
    answers: tuple[str, ...]
    cost: str
    command: str
    sets: tuple[str, ...]
    needs: tuple[str, ...]
    situations: tuple[Situation, ...]


def _stem(word: str) -> str:
    for suffix in ("ing", "ed", "s"):
        if word.endswith(suffix) and len(word) - len(suffix) >= 4:
            return word[: -len(suffix)]
    return word


def _stems(text: str) -> set[str]:
    return {_stem(w) for w in re.findall(r"[a-z0-9]+", text.casefold()) if w not in STOP}


def _tags(query: str) -> set[Situation]:
    words = re.findall(r"[a-z0-9]+", query.casefold())
    stems = {_stem(w) for w in words}
    tags = {
        tag
        for word in words
        for key, hit in SYNONYMS.items()
        if word.startswith(key)
        for tag in hit
    }
    tags |= {tag for tag in SITUATIONS if {_stem(p) for p in tag.split("-")} <= stems}
    return tags


def _score(spec: ToolSpec, tags: set[Situation], words: set[str]) -> int:
    name = _stems(spec.id.replace(".", " ").replace("_", " "))
    said = _stems(" ".join(spec.answers))
    return (
        TAG_SCORE * len(tags & set(spec.situations))
        + NAME_SCORE * len(words & name)
        + WORD_SCORE * len(words & said)
    )


def _hit(spec: ToolSpec, score: int) -> Hit:
    return Hit(
        spec.id,
        score,
        spec.answers,
        spec.cost,
        f"alpha tool run {spec.id} <run_id>",
        tuple(name for name, members in SETS.items() if spec.id in members),
        tuple(INPUT_WORDS[kind] for kind in spec.needs),
        spec.situations,
    )


def find(query: str) -> list[Hit]:
    """Ranked checks for plain words; empty when no word points at any check."""
    tags, words = _tags(query), _stems(query)
    scored = [(_score(spec, tags, words), position, spec) for position, spec in enumerate(SPECS)]
    ranked = sorted(
        (item for item in scored if item[0] > 0),
        key=lambda item: (-item[0], COST_RANK[item[2].cost], item[1]),
    )
    return [_hit(spec, score) for score, _, spec in ranked]


def index() -> dict[Situation, list[ToolSpec]]:
    """Situation -> its checks, cheapest first, describing before testing."""
    order = sorted(
        enumerate(SPECS), key=lambda p: (COST_RANK[p[1].cost], LOOK_RANK[p[1].look], p[0])
    )
    return {tag: [spec for _, spec in order if tag in spec.situations] for tag in SITUATIONS}


def pointers_for(query: str) -> list[str]:
    return [
        f"{SITUATIONS[tag]}: {POINTERS[tag]}"
        for tag in SITUATIONS
        if tag in POINTERS and tag in _tags(query)
    ]


def render_hits(query: str, hits: list[Hit]) -> str:
    if not hits:
        pointed = pointers_for(query)
        if pointed:
            return "\n".join([f"No toolbox check matches {query!r}.", *pointed])
        return "\n".join(
            [f"No check matches {query!r}. Situations to start from:", *situation_lines()]
        )
    lines = [f"{len(hits)} checks fit {query!r}, best first:"]
    for hit in hits:
        lines += [f"{hit.tool_id}  [{hit.cost}]", *(f"  Answers: {a}" for a in hit.answers)]
        lines += [f"  Needs: {', '.join(hit.needs)}", f"  Run: {hit.command}"]
        lines.append(
            "  In set: " + ", ".join(f"{s} (alpha tool run-set {s} <run_id>)" for s in hit.sets)
            if hit.sets
            else "  In no named set."
        )
    lines += pointers_for(query)
    return "\n".join(lines)


def situation_lines() -> list[str]:
    return [f"  {label}  [{tag}]" for tag, label in SITUATIONS.items()]


def render_index() -> str:
    lines = []
    for tag, specs in index().items():
        shown = ", ".join(f"{s.id} ({s.cost})" for s in specs) or POINTERS[tag]
        lines += [f"{SITUATIONS[tag]}  [{tag}]", f"  {shown}"]
    return "\n".join(lines)


def markdown_index() -> str:
    """The list pasted into research/tools/toolbox-by-situation.md; a test keeps it equal."""
    items = []
    for tag, specs in index().items():
        shown = ", ".join(f"`{s.id}`" for s in specs) or POINTERS[tag]
        items.append(
            textwrap.fill(
                f"{SITUATIONS[tag]}: {shown}",
                width=158,
                initial_indent="- ",
                subsequent_indent="  ",
                break_long_words=False,
                break_on_hyphens=False,
            )
        )
    return "\n".join(items)
