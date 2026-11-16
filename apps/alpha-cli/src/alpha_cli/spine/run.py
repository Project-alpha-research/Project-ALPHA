"""Compose plain rule trials using the existing validation execution and publication seams."""

from __future__ import annotations

import dataclasses
import hashlib
import json
import math
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from alpha_cli import _artifacts, _gauntlet, _runner
from alpha_cli._identity import RunIdentity
from alpha_cli.spine.deflation import count_snapshot, family_sharpes, spine_snapshot
from alpha_cli.spine.diagnose import write_diagnostics
from alpha_cli.spine.errors import SpineError
from alpha_cli.spine.facts import build_facts, read_json
from alpha_cli.spine.ledger import append_trial
from alpha_cli.spine.spec import IdeaSpec
from alpha_cli.spine.stores import periods_per_year, resolve_asset
from alpha_cli.validate_cmds import write_validation_run
from alpha_core import Bar, CorporateAction, DataError


def _fields(obj: Any) -> dict[str, Any]:
    """Instance fields of a dataclass, by declared field name."""
    return {field.name: getattr(obj, field.name) for field in dataclasses.fields(obj)}


def assemble_run_spec(idea: IdeaSpec, symbol: str, ppy: int, n_bars: int) -> _runner.RunSpec:
    """Use the minimum strategy warm-up and near-annual folds covering almost all history."""
    params = idea.rule.params
    spec = _runner.RunSpec(
        lookback=params.get("lookback", 252),
        skip=params.get("skip", 21),
        vol_window=63,
        target_vol=0.15,
        rebalance_every=1,
        max_leverage=1.0,
        allow_short=False,
        periods_per_year=ppy,
        fee_bps=idea.costs.fee_bps,
        slippage_bps=idea.costs.slippage_bps,
        starting_cash=1_000_000.0,
        account_type="MARGIN" if "/" in symbol else "CASH",
        train_size=1,
        test_size=1,
        embargo=5,
        anchored=True,
        strategy_name=idea.rule.strategy,
        strategy_params=tuple(sorted((key, float(value)) for key, value in params.items()))
        if idea.rule.kind != "tsmom"
        else (),
        sizing="all_in",
    )
    warmup = spec.min_train
    if n_bars < warmup + 60:
        raise DataError(f"{symbol}: need at least warm-up + 60 bars ({warmup + 60}), got {n_bars}")
    available = n_bars - 1 - warmup - spec.embargo
    return replace(
        spec, train_size=warmup, test_size=available // max(1, math.ceil(available / ppy))
    )


@dataclass(frozen=True)
class Prepared:
    bars: list[Bar]
    dividends: list[CorporateAction]
    spec: _runner.RunSpec
    identity: RunIdentity


def _prepare(
    idea: IdeaSpec, asset: str, home: Path, knobs: _gauntlet.GauntletParams, result: dict[str, Any]
) -> Prepared:
    resolved = resolve_asset(asset, data_dir=home)
    result.update(symbol=resolved.symbol, store=resolved.store_name, source=resolved.source)
    if resolved.defaulted:
        result["labels"].append("source-defaulted")
    bars, snapshot_id = _runner.load_bars(resolved.symbol, data_dir=resolved.data_dir)
    dividends = _runner.load_dividends(resolved.symbol, data_dir=resolved.data_dir)
    result.update(
        first_ts=bars[0].ts.isoformat(), last_ts=bars[-1].ts.isoformat(), n_bars=len(bars)
    )
    if (bars[-1].ts - bars[0].ts).total_seconds() < 3 * 365.25 * 86400:
        result["labels"].append("short-history")
    ppy = periods_per_year([bar.ts for bar in bars])
    result["periods_per_year"] = ppy
    spec = assemble_run_spec(idea, resolved.symbol, ppy, len(bars))
    identity = _runner.run_identity_for(
        {
            "command": "validate",
            "symbol": resolved.symbol,
            "snapshot_id": snapshot_id,
            "research_cutoff": None,
            **_fields(spec),
            **{key: value for key, value in _fields(knobs).items() if key != "max_workers"},
            "spec_sha256": idea.spec_sha256,
            "source": resolved.source,
            "store": resolved.store_name,
            "labels": result["labels"],
        },
        source_fingerprint=_runner.source_fingerprint(bars, dividends=dividends),
    )
    result.update(run_id=identity.run_id, run_dir=str(_artifacts.run_dir(home, identity.run_id)))
    return Prepared(bars, dividends, spec, identity)


def _execute(
    idea: IdeaSpec,
    prepared: Prepared,
    home: Path,
    knobs: _gauntlet.GauntletParams,
    test_id: str,
    result: dict[str, Any],
) -> None:
    rdir = Path(result["run_dir"])
    if (rdir / "manifest.json").exists():
        manifest = _artifacts.read_manifest(rdir)
        result["labels"].append("repeat")
    else:
        snapshot = spine_snapshot(home)
        count = count_snapshot(snapshot, idea.rule.kind)
        out = _gauntlet.run_gauntlet(
            prepared.bars,
            prepared.spec,
            knobs,
            run_id=prepared.identity.run_id,
            snapshot_id=None,
            dividends=prepared.dividends,
            trial_sharpes=family_sharpes(snapshot, count.family_id, prepared.spec.periods_per_year),
            trial_family=count.family_id,
            trial_count=count.prior_trials + 1 + count.unknown_rows,
        )
        _artifacts.publish_artifact(
            rdir / "spec.json",
            lambda path: path.write_text(
                json.dumps(
                    {**idea.model_dump(mode="json"), "spec_sha256": idea.spec_sha256},
                    sort_keys=True,
                    separators=(",", ":"),
                    allow_nan=False,
                ),
                encoding="utf-8",
            ),
        )
        if "no-diagnostics" not in result["labels"]:
            out = write_diagnostics(
                idea,
                prepared.bars,
                prepared.dividends,
                prepared.spec,
                out,
                prepared.identity,
                home,
                result,
                snapshot=snapshot,
            )
        _, manifest = write_validation_run(
            home,
            prepared.bars,
            prepared.spec,
            out,
            prepared.identity,
            extra_manifest={
                "source": result["source"],
                "spine": {
                    "test_id": test_id,
                    "spec_sha256": idea.spec_sha256,
                    "name": idea.name,
                    "idea": idea.idea,
                    "rule": idea.rule.model_dump(),
                    "store": result["store"],
                    "deflation": result.get("deflation"),
                    "labels": list(result["labels"]),
                },
            },
        )
    verdict = manifest.get("verdict")
    dsr = manifest.get("dsr")
    result.update(
        verdict=verdict.get("overall") if isinstance(verdict, dict) else None,
        oos_sharpe=manifest.get("oos_metrics", {}).get("sharpe"),
        benchmark_sharpe=manifest.get("oos_metrics", {}).get("benchmark_sharpe"),
        dsr=dsr.get("dsr") if isinstance(dsr, dict) else None,
    )
    diagnostics = read_json(rdir / "diagnostics.json")
    result.update(
        flags=diagnostics.get("flags", []),
        benchmark_sharpe=diagnostics.get("benchmark", {}).get("sharpe"),
        variants_evaluated=diagnostics.get("variants_evaluated", 0),
        facts=build_facts(rdir),
    )


def run_idea(
    idea: IdeaSpec, *, home: Path, seed: int = 7, quick: bool = False, no_diagnose: bool = False
) -> dict[str, Any]:
    """Run assets independently; ledger failures remain fatal rather than losing trial history."""
    knobs = _gauntlet.GauntletParams(seed=seed)
    if quick:
        knobs = replace(
            knobs, tier1_paths=20, tier2_paths=4, tier3_paths=4, n_resamples=50, max_workers=1
        )
    results: list[dict[str, Any]] = []
    prepared: list[Prepared | None] = []
    for asset in idea.assets:
        result: dict[str, Any] = dict.fromkeys(
            (
                "symbol",
                "store",
                "source",
                "run_id",
                "run_dir",
                "periods_per_year",
                "verdict",
                "oos_sharpe",
                "benchmark_sharpe",
                "dsr",
                "error",
                "first_ts",
                "last_ts",
                "n_bars",
            )
        )
        result.update(
            asset=asset,
            labels=[
                "all-in",
                "dev-machine-data",
                *(["quick"] if quick else []),
                *(["no-diagnostics"] if no_diagnose else []),
            ],
            flags=[],
            facts=[],
            variants_evaluated=0,
        )
        try:
            prepared.append(_prepare(idea, asset, home, knobs, result))
        except (
            Exception
        ) as exc:  # Each asset failure is reported explicitly; other assets continue.
            result["error"] = f"{type(exc).__name__}: {exc}"
            prepared.append(None)
        results.append(result)
    ids = sorted(item.identity.run_id for item in prepared if item is not None)
    test_id = hashlib.sha256((idea.spec_sha256 + "".join(ids)).encode()).hexdigest()[:16]
    total = 0
    for result, item in zip(results, prepared, strict=True):
        if item is not None:
            try:
                _execute(idea, item, home, knobs, test_id, result)
            except SpineError as exc:
                if exc.payload["code"] == "LEDGER_UNREADABLE":
                    raise
                result["error"] = f"{type(exc).__name__}: {exc}"
            except Exception as exc:  # Preserve the failed attempt as well as successful results.
                result["error"] = f"{type(exc).__name__}: {exc}"
        if result["error"] is not None:
            result["labels"].append("error")
        row = append_trial(
            home,
            {
                "test_id": test_id,
                "name": idea.name,
                "idea": idea.idea,
                "spec_sha256": idea.spec_sha256,
                "rule": idea.rule.kind,
                "params": idea.rule.params,
                "costs": idea.costs.model_dump(),
                **{
                    key: value
                    for key, value in result.items()
                    if key not in {"asset", "run_dir", "error", "facts"}
                },
            },
        )
        result["labels"] = row["labels"]
        total = row["total_trials"]
        for key in ("first_ts", "last_ts", "n_bars"):
            result.pop(key)
    return {
        "test_id": test_id,
        "spec_sha256": idea.spec_sha256,
        "name": idea.name,
        "trials_total": total,
        "results": results,
    }
