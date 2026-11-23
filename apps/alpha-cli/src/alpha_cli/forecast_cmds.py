"""``alpha forecast run`` / ``alpha forecast eval``: Kronos forecasting for one symbol.

``run`` samples future OHLCV paths over the trailing ``--context`` bars (outcome-cone
artifacts under ``data_dir/forecast/<run_id>/``); ``eval`` scores the forecaster at rolling
origins against realized outcomes and random-walk/bootstrap baselines, split pre/post the
assumed pretraining cutoff. ``--model fake`` selects the deterministic offline double used
by tests/demos. Pre-cutoff model inputs get a loud pretrain-overlap warning + manifest
flag (ADR-0009).
"""

from __future__ import annotations

import dataclasses
import math
from pathlib import Path
from typing import Any

import polars as pl
import typer

from alpha_cli import _artifacts, _forecast, _forecast_eval, _runner
from alpha_cli._artifacts import sanitize
from alpha_cli._progress import heartbeat
from alpha_cli.spine import reserve
from alpha_core import DataError
from alpha_core.config import AlphaSettings

FEW_ORIGINS = 30  # fewer scored dates than this cannot show whether the bands cover
QUICK_ORIGINS = 6  # the default eval scores the latest few origins: minutes, not hours, on a CPU

forecast_app = typer.Typer(
    help="Kronos foundation-model forecasting (probabilistic outcome cones)."
)

# A forecast run is forward use: it reads the latest bars on purpose and holds nothing back. The
# marker is a manifest field, not part of the run id, so stored runs keep their ids.
FORWARD_USE = "forward"
_load_bars = _runner.load_bars  # module seam: monkeypatched in tests

# shared with the strategy signal-cache precompute (alpha_cli._forecast_cache)
_forecaster_factory = _forecast._forecaster_factory
_provenance = _forecast._provenance


@forecast_app.command()
def run(
    symbol: str = typer.Argument(..., help="symbol in the store (run `alpha data pull` first)"),
    horizon: int = typer.Option(21, help="forecast steps (sessions)"),
    samples: int = typer.Option(100, help="Monte-Carlo sample paths"),
    context: int | None = typer.Option(
        None, help="trailing bars fed to the model (default: settings.forecast_context)"
    ),
    temperature: float = 1.0,
    top_p: float = 0.9,
    top_k: int = 0,
    model: str | None = typer.Option(
        None, help="HF id | local checkpoint path | 'fake' (default: settings.forecast_model)"
    ),
    model_revision: str | None = None,
    tokenizer: str | None = None,
    tokenizer_revision: str | None = None,
    device: str | None = typer.Option(
        None, help="cpu (bit-reproducible) | mps | cuda (default: settings.forecast_device)"
    ),
    as_of: str | None = typer.Option(
        None, "--as-of", help="ISO date: use only bars at/before this date (point-in-time)"
    ),
    seed: int | None = None,
    snapshot: str | None = None,
) -> None:
    """Sample future OHLCV paths for SYMBOL and write the outcome-cone artifacts."""
    settings = AlphaSettings()
    (resolved_model, resolved_model_rev, resolved_tokenizer, resolved_tokenizer_rev) = (
        _forecast.resolved_model(settings, model, model_revision, tokenizer, tokenizer_revision)
    )
    resolved_device = device if device is not None else settings.forecast_device
    master_seed = seed if seed is not None else settings.random_seed
    sampling_seed = _forecast.forecast_seed(master_seed)

    try:
        as_of_dt = _runner.parse_as_of(as_of)
        bars, snapshot_id = _load_bars(
            symbol,
            data_dir=settings.data_dir,
            snapshot_id=snapshot,
            as_of=as_of_dt,
        )
        resolved_context, lowered = _forecast.fit_context(
            context, default=settings.forecast_context, available=len(bars), what="bars"
        )
    except DataError as exc:
        raise typer.BadParameter(str(exc)) from exc
    forecaster = _forecaster_factory(
        model=resolved_model,
        model_revision=resolved_model_rev,
        tokenizer=resolved_tokenizer,
        tokenizer_revision=resolved_tokenizer_rev,
        device=resolved_device,
        hub_cache=settings.forecast_hub_cache,
        local_files_only=settings.forecast_local_only,
    )
    expected = _forecast.calibrated_seconds(
        forecaster,
        bars,
        context=resolved_context,
        horizon=horizon,
        rows=samples,
        model=resolved_model,
    )
    _say(_forecast.trading_day_line(as_of_dt, bars[-1].ts), lowered)
    _say(_forecast.expected_time_line(resolved_model, expected))

    try:
        with heartbeat("Forecast", expected=expected):
            out = _forecast.run_forecast(
                bars,
                forecaster=forecaster,
                context=resolved_context,
                horizon=horizon,
                sample_count=samples,
                temperature=temperature,
                top_p=top_p,
                top_k=top_k,
                seed=sampling_seed,
                as_of=as_of_dt,
                cutoff=settings.forecast_pretrain_cutoff,
            )
    except DataError as exc:
        raise typer.BadParameter(str(exc)) from exc

    # The id pins everything the sampled paths depend on — incl. the model input recency
    # (context_last_ts), so a grown store cannot silently shift a fixed --as-of run.
    payload: dict[str, Any] = {
        "command": "forecast_run",
        "symbol": symbol,
        "snapshot": snapshot,
        "model": resolved_model,
        "model_revision": resolved_model_rev,
        "tokenizer": resolved_tokenizer,
        "tokenizer_revision": resolved_tokenizer_rev,
        "device": resolved_device,
        "context": resolved_context,
        "horizon": horizon,
        "samples": samples,
        "temperature": temperature,
        "top_p": top_p,
        "top_k": top_k,
        "seed": master_seed,
        "as_of": as_of,
        "last_bar_ts": out.context_last_ts.isoformat(),
    }
    identity = _runner.run_identity_for(
        payload,
        source_fingerprint=_runner.source_fingerprint(bars),
        snapshot_hash=_runner.verified_snapshot_hash(settings.data_dir, snapshot_id),
    )
    run_id = identity.run_id
    rdir = settings.data_dir / "forecast" / run_id

    prov = _provenance(forecaster, model=resolved_model)
    manifest = sanitize(
        {
            "schema_version": 1,
            "run_id": run_id,
            "command": "forecast_run",
            "symbol": symbol,
            "snapshot_id": snapshot_id,
            "research_cutoff": as_of,
            "use": FORWARD_USE,
            "model": prov,
            "params": {
                "context": resolved_context,
                "horizon": horizon,
                "samples": samples,
                "temperature": temperature,
                "top_p": top_p,
                "top_k": top_k,
                "seed": master_seed,
                "sampling_seed": sampling_seed,
            },
            "origin": {
                "origin_ts": out.result.origin_ts.isoformat(),
                "n_context": out.n_context,
                "first_ts": out.context_first_ts.isoformat(),
                "last_ts": out.context_last_ts.isoformat(),
                "as_of": as_of,
            },
            "pretrain": out.pretrain,
            "summary": {
                "median_end_return": out.median_end_return,
                "p05_end_return": out.p05_end_return,
                "p95_end_return": out.p95_end_return,
                "prob_up": out.prob_up,
            },
            **identity.manifest_fields(),
        }
    )
    _forecast.write_forecast_run(rdir, manifest=manifest, out=out, history=bars)
    pictures = _cone_pictures(run_id, rdir, settings.data_dir)

    _announce(symbol, run_id, out, (horizon, samples), prov, rdir, pictures)


def _announce(
    symbol: str,
    run_id: str,
    out: Any,
    shape: tuple[int, int],
    prov: dict[str, Any],
    rdir: Path,
    pictures: tuple[str, str],
) -> None:
    """Print the one-screen forecast summary, then the pretraining-overlap warning if any."""
    horizon, samples = shape
    typer.echo(
        f"forecast {symbol} -> run {run_id}: median {out.median_end_return:+.2%} "
        f"[p05 {out.p05_end_return:+.2%}, p95 {out.p95_end_return:+.2%}] over {horizon} steps "
        f"({samples} paths), P(up) {out.prob_up:.0%}\n"
        f"  model {prov.get('model_id')}@{prov.get('model_revision')} "
        f"device={prov.get('device')} determinism={prov.get('determinism')}\n"
        f"  manifest at {rdir / 'manifest.json'} (forward use: nothing held back)\n"
        f"  Picture: {pictures[0]}\n"
        f"  Picture with notes: {pictures[1]}"
    )
    if out.pretrain["overlap"]:
        typer.secho(
            f"WARNING: context bars overlap the assumed Kronos pretraining window "
            f"(<= {out.pretrain['cutoff']}) — results may be memorized, not predicted "
            f"(ADR-0009)",
            fg=typer.colors.YELLOW,
        )


def _say(*lines: str | None) -> None:
    for line in lines:
        if line is not None:
            typer.echo(line)


def _cone_pictures(run_id: str, rdir: Path, data_dir: Path) -> tuple[str, str]:
    """Draw the outcome cone, plain and with notes, into the figure cache."""
    from alpha_cli.figures_cmds import _render_one, _with_plain_name

    manifest = _artifacts.read_manifest(rdir)
    drawn = [
        _with_plain_name(
            _render_one(
                "forecast_fan",
                run_id=run_id,
                rdir=rdir,
                manifest=manifest,
                data_dir=data_dir,
                fmt="png",
                force=False,
                variant=variant,
            ),
            variant,
        )["path"]
        for variant in ("plain", "annotated")
    ]
    return str(drawn[0]), str(drawn[1])


def _skill_sentence(skill: float, baseline: str) -> str:
    """One plain sentence for a skill number; the statistic itself is unchanged."""
    if not math.isfinite(skill):
        return f"    Skill vs {baseline}: not measured, because the baseline error was zero."
    ratio = 1.0 - skill
    reading = (
        f"the model's error was {ratio:.1f} times the {baseline}'s"
        if skill < 0
        else f"the model's error was {skill:.0%} smaller than the {baseline}'s"
    )
    return (
        f"    Skill vs {baseline}: the model's error (CRPS) against the {baseline} forecast. "
        f"Above 0% the model did better; below 0% it did worse. Here {reading}."
    )


def _summary_line(summary: Any) -> str:
    return (
        f"CRPS {summary.crps_mean:.4f} (skill vs RW {summary.skill_vs_rw:+.1%}, "
        f"vs bootstrap {summary.skill_vs_bootstrap:+.1%}), coverage 50/80/90 "
        f"{summary.coverage50:.0%}/{summary.coverage80:.0%}/{summary.coverage90:.0%}, "
        f"hit rate {summary.hit_rate:.0%}"
    )


def _explained(summary: Any) -> str:
    """The summary line, then one plain sentence for each number in it."""
    return (
        f"{_summary_line(summary)}\n"
        "    RW is a random walk: it expects tomorrow to equal today, plus the recent average "
        "drift, with the recent day-to-day spread.\n"
        f"{_skill_sentence(summary.skill_vs_rw, 'random walk')}\n"
        "    Bootstrap re-draws blocks of the recent daily returns to build its paths.\n"
        f"{_skill_sentence(summary.skill_vs_bootstrap, 'bootstrap')}\n"
        "    Coverage: how often the real outcome fell inside the model's 50%, 80% and 90% "
        "ranges. Near 50/80/90 is well calibrated.\n"
        "    Hit rate: how often the median path pointed the same way (up or down) as the "
        "real move."
    )


def _origins_frame(out: _forecast_eval.ForecastEvalOutput) -> pl.DataFrame:
    """One row per scored origin."""
    return pl.DataFrame(
        [
            {
                "origin_index": o.origin_index,
                "origin_ts": o.origin_ts,
                "pre_cutoff": o.pre_cutoff,
                **dataclasses.asdict(o.score),
            }
            for o in out.origins
        ]
    )


@forecast_app.command(name="eval")
def evaluate(
    symbol: str = typer.Argument(..., help="symbol in the store (run `alpha data pull` first)"),
    horizon: int = typer.Option(21, help="forecast steps per origin (sessions)"),
    stride: int = typer.Option(21, help="bars between rolling origins"),
    origins: int = typer.Option(
        QUICK_ORIGINS, min=0, help="score only the latest N origins; 0 scores every origin"
    ),
    samples: int = typer.Option(20, help="Monte-Carlo sample paths per origin"),
    context: int | None = typer.Option(
        None, help="trailing bars fed to the model (default: settings.forecast_context)"
    ),
    temperature: float = 1.0,
    top_p: float = 0.9,
    top_k: int = 0,
    mean_block: float = typer.Option(5.0, help="stationary-bootstrap mean block (baseline)"),
    model: str | None = typer.Option(
        None, help="HF id | local checkpoint path | 'fake' (default: settings.forecast_model)"
    ),
    model_revision: str | None = None,
    tokenizer: str | None = None,
    tokenizer_revision: str | None = None,
    device: str | None = None,
    seed: int | None = None,
    snapshot: str | None = None,
    as_of: str | None = typer.Option(None, "--as-of", help="inclusive research cutoff YYYY-MM-DD"),
) -> None:
    """Score SYMBOL's forecaster at rolling origins vs realized outcomes + baselines."""
    settings = AlphaSettings()
    (resolved_model, resolved_model_rev, resolved_tokenizer, resolved_tokenizer_rev) = (
        _forecast.resolved_model(settings, model, model_revision, tokenizer, tokenizer_revision)
    )
    resolved_device = device if device is not None else settings.forecast_device
    master_seed = seed if seed is not None else settings.random_seed
    try:
        # The reserved period is held back: cut the symbol.
        held = reserve.hold(symbol, data_dir=settings.data_dir, as_of=as_of, snapshot_id=snapshot)
        bars, snapshot_id = _load_bars(
            symbol,
            data_dir=settings.data_dir,
            snapshot_id=snapshot,
            as_of=held.as_of,
        )
        resolved_context, lowered = _forecast.fit_context(
            context,
            default=settings.forecast_context,
            available=len(bars) - horizon,
            what="bars before the last outcome",
        )
        every = _forecast_eval.origin_indices(
            len(bars), context=resolved_context, horizon=horizon, stride=stride
        )
    except DataError as exc:
        raise typer.BadParameter(str(exc)) from exc
    forecaster = _forecaster_factory(
        model=resolved_model,
        model_revision=resolved_model_rev,
        tokenizer=resolved_tokenizer,
        tokenizer_revision=resolved_tokenizer_rev,
        device=resolved_device,
        hub_cache=settings.forecast_hub_cache,
        local_files_only=settings.forecast_local_only,
    )

    scored = len(every) if origins == 0 else min(origins, len(every))
    expected = _forecast.calibrated_seconds(
        forecaster,
        bars,
        context=resolved_context,
        horizon=horizon,
        rows=samples,
        model=resolved_model,
        scale=scored,
    )
    per_origin = expected / max(scored, 1)
    _say(_forecast.trading_day_line(held.as_of if as_of else None, bars[-1].ts), lowered)
    _say(_forecast.expected_time_line(resolved_model, expected))
    try:
        with heartbeat("Forecast evaluation", expected=expected):
            out = _forecast_eval.run_forecast_eval(
                bars,
                forecaster=forecaster,
                context=resolved_context,
                horizon=horizon,
                stride=stride,
                sample_count=samples,
                temperature=temperature,
                top_p=top_p,
                top_k=top_k,
                seed=master_seed,
                cutoff=settings.forecast_pretrain_cutoff,
                mean_block=mean_block,
                max_origins=scored,
            )
    except DataError as exc:
        raise typer.BadParameter(str(exc)) from exc

    payload: dict[str, Any] = {
        "command": "forecast_eval",
        "symbol": symbol,
        "snapshot": snapshot,
        "model": resolved_model,
        "model_revision": resolved_model_rev,
        "tokenizer": resolved_tokenizer,
        "tokenizer_revision": resolved_tokenizer_rev,
        "device": resolved_device,
        "context": resolved_context,
        "horizon": horizon,
        "stride": stride,
        "origins": origins,
        "samples": samples,
        "temperature": temperature,
        "top_p": top_p,
        "top_k": top_k,
        "mean_block": mean_block,
        "seed": master_seed,
        **held.identity(),
        "first_origin_ts": out.origins[0].origin_ts.isoformat(),
        "last_origin_ts": out.origins[-1].origin_ts.isoformat(),
    }
    identity = _runner.run_identity_for(
        payload,
        source_fingerprint=_runner.source_fingerprint(bars),
        snapshot_hash=_runner.verified_snapshot_hash(settings.data_dir, snapshot_id),
    )
    run_id = identity.run_id
    rdir = settings.data_dir / "forecast" / run_id
    rdir.mkdir(parents=True, exist_ok=True)

    prov = _provenance(forecaster, model=resolved_model)
    manifest_payload: dict[str, Any] = {
        "schema_version": 1,
        "run_id": run_id,
        "command": "forecast_eval",
        "symbol": symbol,
        "snapshot_id": snapshot_id,
        "research_cutoff": held.research_cutoff,
        "model": prov,
        "params": {
            "context": resolved_context,
            "horizon": horizon,
            "stride": stride,
            "origins": origins,
            "samples": samples,
            "temperature": temperature,
            "top_p": top_p,
            "top_k": top_k,
            "mean_block": mean_block,
            "seed": master_seed,
        },
        "origins": {
            "n": len(out.origins),
            "first_ts": out.origins[0].origin_ts.isoformat(),
            "last_ts": out.origins[-1].origin_ts.isoformat(),
        },
        "pretrain": out.pretrain,
        "summary": dataclasses.asdict(out.summary),
        "summary_pre_cutoff": (
            dataclasses.asdict(out.summary_pre) if out.summary_pre is not None else None
        ),
        "summary_post_cutoff": (
            dataclasses.asdict(out.summary_post) if out.summary_post is not None else None
        ),
        "n_origins_pre": out.n_pre,
        "n_origins_post": out.n_post,
        **identity.manifest_fields(),
    }
    held.stamp(manifest_payload)
    manifest = sanitize(manifest_payload)
    origins_frame = _origins_frame(out)
    _artifacts.publish_artifact(rdir / "origins.parquet", origins_frame.write_parquet)
    _artifacts.write_manifest(rdir, manifest)

    typer.echo(
        f"forecast-eval {symbol} -> run {run_id}: {len(out.origins)} origins, "
        f"{_explained(out.summary)}\n"
        f"  model {prov.get('model_id')}@{prov.get('model_revision')} "
        f"device={prov.get('device')} determinism={prov.get('determinism')}\n"
        f"  manifest at {rdir / 'manifest.json'}"
    )
    if scored < len(every):
        typer.echo(
            f"  This was a quick look at the latest {scored} of {len(every)} origins. For the "
            f"full history add --origins 0 ({_forecast.say_time(per_origin * len(every))} on a "
            "desktop CPU)."
        )
    if held.held_back:
        typer.echo(held.say())
    if out.summary_pre is not None:
        typer.echo(f"  pre-cutoff  ({out.n_pre} origins): {_summary_line(out.summary_pre)}")
    if out.summary_post is not None:
        typer.echo(f"  post-cutoff ({out.n_post} origins): {_summary_line(out.summary_post)}")
    else:
        cutoff = out.pretrain["cutoff"]
        if held.held_back:
            reason = (
                f"every origin falls before the end of the model's assumed training period "
                f"({cutoff}), so every skill number may overlap what the model saw in training; "
                "later bars are stored but held back for your confirmation, so this test did "
                "not use them"
            )
        else:
            reason = (
                "every skill number overlaps the assumed Kronos pretraining window (ADR-0009); "
                f"extend the data past {cutoff} for an honest read"
            )
        typer.secho(f"WARNING: no post-cutoff origins: {reason}", fg=typer.colors.YELLOW)
    if len(out.origins) < FEW_ORIGINS:
        typer.echo(
            f"  {len(out.origins)} dates is too few to judge coverage; use --origins N for more."
        )
