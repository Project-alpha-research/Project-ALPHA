"""Offline-testable retrieval comparison; CLI calls only an explicitly supplied gateway."""

from __future__ import annotations

import argparse
import json
import math
import os
import urllib.error
import urllib.request
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

PROXY_RULE = (
    "Relevance proxy, not ground truth: entries with the same idea family and symbol set "
    "are relevant to each other, excluding the query entry itself. Outcomes do not affect labels."
)


class InputRefused(Exception):
    """An embedding service explicitly refused this input; other errors must propagate."""


@dataclass
class EmbeddedInput:
    vector: list[float]
    split_inputs: int = 0
    model: str | None = None


def unit_vector(vector: Sequence[float], dimension: int | None = None) -> list[float]:
    if not vector or (dimension is not None and len(vector) != dimension):
        raise ValueError("embedding dimension differs or is empty")
    if any(type(x) not in (float, int) or not math.isfinite(x) for x in vector):
        raise ValueError("embedding must be finite numbers")
    norm = math.hypot(*vector)
    if norm == 0 or not math.isfinite(norm):
        raise ValueError("embedding has invalid norm")
    return [x / norm for x in vector]


def evaluate(
    entries: list[dict[str, Any]],
    queries: list[dict[str, Any]],
    embed: Callable[[str], EmbeddedInput | list[float]],
    *,
    relevance_rule: str = "Explicit relevance labels supplied by the caller.",
) -> dict[str, Any]:
    """Macro recall and MRR using cosine similarity, ties broken by entry id.

    Refused corpus entries remain in recall denominators; refused queries score zero.
    Every vector is freshly obtained from the callable, so stored models are never mixed.
    """
    ids = [entry["id"] for entry in entries]
    if any(not isinstance(i, str) or not i for i in ids) or len(set(ids)) != len(ids):
        raise ValueError("entry ids must be unique nonempty strings")
    if not queries:
        raise ValueError("at least one query is required")
    for query in queries:
        relevant = set(query["relevant_ids"])
        excluded = set(query.get("exclude_ids", []))
        if not relevant or not relevant <= set(ids) or relevant & excluded:
            raise ValueError("relevant ids must exist, be nonempty and not excluded")
    counts = {"inputs_refused": 0, "inputs_split": 0}
    dimension: int | None = None
    model: str | None = None

    def vector(text: str) -> list[float] | None:
        nonlocal dimension, model
        if not isinstance(text, str):
            raise ValueError("embedding input must be text")
        try:
            result = embed(text)
        except InputRefused:
            counts["inputs_refused"] += 1
            return None
        if isinstance(result, EmbeddedInput):
            if model is not None and result.model != model:
                raise ValueError("embedding model changed during evaluation")
            model = result.model
            if type(result.split_inputs) is not int or result.split_inputs not in (0, 1):
                raise ValueError("split_inputs must be zero or one for one input")
            counts["inputs_split"] += result.split_inputs
            raw = result.vector
        else:
            raw = result
        normalised = unit_vector(raw, dimension)
        dimension = len(normalised)
        return normalised

    corpus = [(entry["id"], vector(entry["text"])) for entry in entries]
    scores: list[tuple[float, float, float]] = []
    for query in queries:
        query_vector = vector(query["text"])
        relevant, excluded = set(query["relevant_ids"]), set(query.get("exclude_ids", []))
        ranked = (
            []
            if query_vector is None
            else sorted(
                (
                    (name, math.fsum(a * b for a, b in zip(query_vector, values, strict=True)))
                    for name, values in corpus
                    if values is not None and name not in excluded
                ),
                key=lambda item: (-item[1], item[0]),
            )
        )
        hits = [rank for rank, (name, _) in enumerate(ranked, 1) if name in relevant]
        scores.append(
            (
                sum(rank <= 3 for rank in hits) / len(relevant),
                sum(rank <= 5 for rank in hits) / len(relevant),
                1 / hits[0] if hits else 0.0,
            )
        )
    return {
        "recall_at_3": math.fsum(s[0] for s in scores) / len(scores),
        "recall_at_5": math.fsum(s[1] for s in scores) / len(scores),
        "mean_reciprocal_rank": math.fsum(s[2] for s in scores) / len(scores),
        "embedding_model": model,
        **counts,
        "entries": len(entries),
        "queries": len(queries),
        "relevance_rule": relevance_rule,
    }


def build_labelled_set(
    ledger: list[dict[str, Any]], memory: list[dict[str, Any]]
) -> dict[str, Any]:
    """Join exported memory to labelled ledger rows by id (or code_sha256).

    Family and symbols must be explicit; missing labels are never guessed from an outcome.
    A raw ledger may use instruments/status for symbols/outcome. Export its idea_family first.
    """
    labels = {row.get("id", row.get("code_sha256")): row for row in ledger}
    entries = []
    for entry in memory:
        key = entry.get("id", entry.get("code_sha256"))
        row = labels[key]
        family = row.get("idea_family", entry.get("idea_family"))
        symbols = row.get(
            "symbols", row.get("instruments", entry.get("symbols", entry.get("instruments")))
        )
        if (
            not isinstance(family, str)
            or not family
            or not isinstance(symbols, list)
            or not symbols
            or any(not isinstance(s, str) for s in symbols)
        ):
            raise ValueError("proxy labels require explicit idea_family and symbols")
        entries.append(
            {
                **entry,
                "id": key,
                "idea_family": family,
                "symbols": sorted(set(symbols)),
                "outcome": row.get("outcome", row.get("status")),
            }
        )
    queries = []
    for entry in entries:
        relevant = sorted(
            other["id"]
            for other in entries
            if other["id"] != entry["id"]
            and (other["idea_family"], other["symbols"]) == (entry["idea_family"], entry["symbols"])
        )
        if relevant:
            queries.append(
                {"text": entry["text"], "relevant_ids": relevant, "exclude_ids": [entry["id"]]}
            )
    return {"entries": entries, "queries": queries, "relevance_rule": PROXY_RULE}


def gateway_callable(base_url: str) -> Callable[[str], EmbeddedInput]:
    # Gateway session token only; this process never reads the paid provider key/base.
    token = os.environ.get("ALPHA_GATEWAY_SESSION_TOKEN", "")

    def embed(text: str) -> EmbeddedInput:
        request = urllib.request.Request(
            base_url.rstrip("/") + "/v1/embeddings",
            data=json.dumps(
                {"model": "alpha-embed", "input": text, "report_embedding_stats": True}
            ).encode(),
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {token}"},
        )
        try:
            with urllib.request.urlopen(request, timeout=180) as response:
                body = json.load(response)
        except urllib.error.HTTPError as error:
            body = json.loads(error.read())
            code = body.get("error", {}).get("code")
            if code == "embedding_input_refused":
                raise InputRefused(code) from None
            raise RuntimeError(f"gateway embedding failed: {code}") from None
        return EmbeddedInput(
            body["data"][0]["embedding"], int(body.get("chunked_inputs", 0)), body["model"]
        )

    return embed


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Compare retrieval by running once per gateway/model; no provider access."
    )
    parser.add_argument("--entries", type=Path, required=True)
    parser.add_argument("--queries", type=Path)
    parser.add_argument("--ledger", type=Path)
    parser.add_argument("--gateway-url", required=True)
    args = parser.parse_args(argv)
    entries = json.loads(args.entries.read_text())
    rule = "Explicit relevance labels supplied by the caller."
    if args.ledger:
        ledger = [json.loads(line) for line in args.ledger.read_text().splitlines() if line.strip()]
        labelled = build_labelled_set(ledger, entries)
        entries, queries, rule = (
            labelled["entries"],
            labelled["queries"],
            labelled["relevance_rule"],
        )
    elif args.queries:
        queries = json.loads(args.queries.read_text())
    else:
        parser.error("supply --queries or --ledger")
    result = evaluate(entries, queries, gateway_callable(args.gateway_url), relevance_rule=rule)
    print(json.dumps(result, sort_keys=True, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
