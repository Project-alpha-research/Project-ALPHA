"""Explicit sandbox-only development-candidate commands."""

from __future__ import annotations

import json
from datetime import date

import typer

from alpha_cli import _runner
from alpha_cli.crypto_data_cmds import crypto_hedged_basis_observations
from alpha_cli.research_crypto_data import snapshot_held_back_rows
from alpha_cli.spine import reserve
from alpha_cli.strategy_candidate import hedged_basis_paper_preflight
from alpha_cli.strategy_candidate_runtime import run_hedged_basis_candidate
from alpha_core import DataError
from alpha_core.config import AlphaSettings

strategy_candidate_app = typer.Typer(
    help="Sandbox-only multi-leg candidate evaluation; no paper or order authority."
)


@strategy_candidate_app.command("run")
def run(
    snapshot_id: str,
    research_contract_id: str = typer.Option(...),
    analysis: str = typer.Option("baseline", help="registered candidate analysis"),
    source_run_id: str | None = typer.Option(None, help="exact upstream validation run"),
    holdout_start: str | None = typer.Option(None, help="sealed holdout start YYYY-MM-DD"),
    holdout_end: str | None = typer.Option(None, help="sealed holdout end YYYY-MM-DD"),
    holdout_spec_hash: str | None = typer.Option(None, help="exact sealed holdout contract"),
    as_of: str | None = typer.Option(None, help="inclusive pre-holdout cutoff YYYY-MM-DD"),
    json_out: bool = typer.Option(False, "--json"),
) -> None:
    """Evaluate a frozen candidate stream; never constructs either venue adapter."""
    settings = AlphaSettings()
    try:
        user = _runner.parse_as_of(as_of)
        # A candidate holdout reads its own sealed window on purpose; that window may lie past
        # the reserved day, which is an open question for the owner (reserved-period.md).
        sealed = analysis == "holdout"
        early = user is not None and user <= reserve.CUTOFF
        cutoff = user if sealed or early else reserve.CUTOFF
        n = 0 if sealed or early else snapshot_held_back_rows(snapshot_id, hedged=True, until=user)
        held = reserve.Hold(cutoff, reserve.CUTOFF_DATE if n else as_of, n, "rows")
        start = None if holdout_start is None else date.fromisoformat(holdout_start)
        end = None if holdout_end is None else date.fromisoformat(holdout_end)
        observations = crypto_hedged_basis_observations(snapshot_id, before_reserved=not sealed)
        manifest = run_hedged_basis_candidate(
            settings.data_dir,
            snapshot_id=snapshot_id,
            snapshot_hash=str(_runner.verified_snapshot_hash(settings.data_dir, snapshot_id)),
            research_contract_id=research_contract_id,
            observations=observations,
            analysis=analysis,
            source_run_id=source_run_id,
            holdout_start=start,
            holdout_end=end,
            holdout_spec_hash=holdout_spec_hash,
            research_cutoff=held.research_cutoff,
            as_of=cutoff,
            held=held,
        )
    except (DataError, ValueError) as exc:
        raise typer.BadParameter(str(exc)) from exc
    if json_out:
        typer.echo(json.dumps(manifest, sort_keys=True, allow_nan=False))
        return
    typer.echo(f"hedged basis {analysis} -> run {manifest['run_id']} (SANDBOX ONLY)")
    held.announce()


@strategy_candidate_app.command("paper-preflight")
def paper_preflight(json_out: bool = typer.Option(False, "--json")) -> None:
    """Report the permanent unsupported multi-venue paper boundary without connecting."""
    result = hedged_basis_paper_preflight()
    if json_out:
        typer.echo(json.dumps(result, sort_keys=True, allow_nan=False))
        return
    typer.echo(
        f"{result['code']}: deterministic sandbox evaluation remains available; "
        "no broker connection or order was attempted."
    )


__all__ = ["strategy_candidate_app"]
