"""One audited path from requested settings to a cached or freshly computed result."""

from __future__ import annotations

from pathlib import Path
from time import monotonic
from typing import Any

from alpha_cli._seeds import semantic_seed
from alpha_cli.spine.errors import SpineError, tool_error
from alpha_cli.spine.ledger import append_trial
from alpha_cli.spine.stores import _stores
from alpha_cli.toolbox import inputs, store
from alpha_cli.toolbox.contract import ToolSpec
from alpha_cli.toolbox.registry import get


def parameters(spec: ToolSpec, raw: list[str], audit: dict[str, Any]) -> dict[str, Any]:
    definitions = {p.name: p for p in spec.params}
    requested = {}
    for pair in raw:
        name, _, value = pair.partition("=")
        requested[name] = value
    audit["settings"] = {p.name: p.default for p in spec.params} | requested
    values = {}
    for pair in raw:
        name, sep, value = pair.partition("=")
        if not sep or name in values or name not in definitions:
            raise SpineError(
                "INVALID_PARAM",
                f"Invalid or repeated parameter {pair!r}.",
                f"Run alpha tool describe {spec.id}.",
                list(definitions),
            )
        param = definitions[name]
        try:
            values[name] = param.type(value)
        except ValueError as exc:
            raise SpineError(
                "INVALID_PARAM",
                f"{name} requires {param.type.__name__}.",
                f"Run alpha tool describe {spec.id}.",
            ) from exc
        if param.allowed is not None and values[name] not in param.allowed:
            raise SpineError(
                "INVALID_PARAM",
                f"Value {value!r} is outside the allowed settings for {name}.",
                f"Run alpha tool describe {spec.id}.",
                [str(v) for v in param.allowed],
            )
    return {p.name: values.get(p.name, p.default) for p in spec.params}


def run(
    home: Path,
    tool_id: str,
    target: str,
    raw: list[str] | None = None,
    seed: int = 0,
    *,
    set_name: str | None = None,
) -> dict[str, Any]:
    with store.target_lock(home, target):
        started = monotonic()
        base: dict[str, Any] = {
            "kind": f"tool:{tool_id}",
            "run_id": target,
            "verdict": None,
            "params_requested": raw or [],
            "seed": seed,
            "set": set_name,
            "labels": [] if set_name else ["ad-hoc"],
        }
        attempt = None
        try:
            spec = get(tool_id)
            settings = parameters(spec, raw or [], base)
            # A seeded entry's seed is a setting like any other: a re-rolled seed is labelled.
            tried = {**settings, "seed": seed} if spec.seeded else settings
            base.update(settings=tried, version=spec.version, look=spec.look, tool_kind=spec.kind)
            if any(settings[p.name] != p.default for p in spec.params) or (spec.seeded and seed):
                base["labels"].append("non-default-params")
            resolved = inputs.resolve(home, target)
            base.update(resolved.ledger_fields())
            market, hashes = resolved.prepare(home, spec.needs, settings)
            key = {"inputs": hashes, "params": settings, "seed": seed, "version": spec.version}
            file = store.output_path(target, spec, key)
            rows = store.history(home, target)
            hit = store.cached(home, file, key, rows)
            if hit is not None:
                return hit
            attempt = append_trial(home, {**base, "outcome": "attempted"})
            series = inputs.load_run(home, resolved)
            if spec.compute is None:
                raise SpineError(
                    "STORED_TOOL", "The gauntlet stores this output.", "Run alpha results cite."
                )
            from numpy.random import default_rng

            effective_seed = (
                spec.legacy_seed
                if seed == 0 and spec.legacy_seed is not None
                else semantic_seed(seed, file)
            )
            rng = default_rng(effective_seed) if spec.seeded else None
            result = spec.compute(inputs.Inputs(series, market, effective_seed), settings, rng)
            labels = list(
                dict.fromkeys(
                    [*resolved.labels, *base["labels"], *series.reserve_labels(), *result.labels]
                )
            )
            document = store.publish(
                series,
                file,
                spec,
                result,
                key,
                labels,
                store.settings_tried([*rows, attempt], tool_id),
                monotonic() - started,
            )
            outcome = append_trial(
                home,
                {
                    **base,
                    "attempt": attempt["trial_index"],
                    "outcome": "ok",
                    "tool_output": file,
                    "labels": labels,
                    "params": document["params"],
                },
            )
        except Exception as exc:
            if attempt is None:
                attempt = append_trial(home, {**base, "outcome": "attempted"})
            error = tool_error(exc)
            append_trial(
                home,
                {
                    **base,
                    "outcome": "error",
                    "attempt": attempt["trial_index"],
                    "error_code": error.payload["code"],
                },
            )
            if error.payload["code"] == "UNKNOWN_ASSET" and not error.payload["known"]:
                error.payload["known"] = list(_stores(home))
            if error is exc:
                raise
            raise error from exc
        return {**document, "file": file, "trials_total": outcome["total_trials"]}
