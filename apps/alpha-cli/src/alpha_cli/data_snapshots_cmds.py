"""`alpha data snapshots` and `alpha data verify`: list and re-hash immutable snapshots."""

from __future__ import annotations

import hashlib
import json

import typer

from alpha_core import DataError
from alpha_data.snapshot import snapshot_timeframe, verify_snapshot
from alpha_data.snapshot_reuse import content_hash, read_manifests, shared_content, total_bytes


def snapshots(
    json_out: bool = typer.Option(False, "--json", help="emit JSON"),
    with_content: bool = typer.Option(
        False, "--with-content", help="with --json: add content hashes and the total size"
    ),
) -> None:
    """List every immutable snapshot's manifest summary in deterministic id order.

    The plain list also shows each content hash and the snapshots that share it, and the total
    size on disk. `--json` keeps its shape (the workstation reads it) unless `--with-content`.
    """
    from alpha_cli.data_cmds import _snaps_root

    root = _snaps_root()
    manifests = read_manifests(root)
    shared = shared_content(manifests)
    rows: list[dict[str, object]] = []
    for _, raw, manifest in manifests:
        symbols_entry = manifest.get("symbols")
        held = symbols_entry if isinstance(symbols_entry, dict) else {}
        held_content = {
            name: {
                "sha256": content_hash(entry),
                "shared_with": [
                    other
                    for other in shared.get((name, content_hash(entry)), [])
                    if other != manifest.get("snapshot_id")
                ],
            }
            for name, entry in sorted(held.items())
            if isinstance(entry, dict)
        }
        rows.append(
            {
                "snapshot_id": manifest.get("snapshot_id"),
                "created_at": manifest.get("created_at"),
                "source": manifest.get("source"),
                "adapter_version": manifest.get("adapter_version"),
                "parser_version": manifest.get("parser_version"),
                "symbols": sorted(held),
                "manifest_sha256": hashlib.sha256(raw).hexdigest(),
                "content": held_content,
            }
        )
    size = total_bytes(root)
    if json_out:
        if with_content:
            body: dict[str, object] = {"snapshots": rows, "total_bytes": size}
        else:
            body = {"snapshots": [{k: v for k, v in r.items() if k != "content"} for r in rows]}
        typer.echo(json.dumps(body, sort_keys=True, allow_nan=False))
        return
    if not rows:
        typer.echo("no snapshots")
        return
    for row in rows:
        listed = row["symbols"]
        names = ",".join(str(item) for item in listed) if isinstance(listed, list) else ""
        typer.echo(f"{row['snapshot_id']} {row['source']} {names}")
        content = row["content"]
        for name, info in content.items() if isinstance(content, dict) else []:
            twins = ", ".join(info["shared_with"]) or "none"
            typer.echo(f"  {name} content {info['sha256'][:12]} also held by: {twins}")
    typer.echo(
        f"{len(rows)} snapshots, {size / 1024:.0f} KB in total. "
        "They are never deleted automatically; removing old ones is the owner's decision."
    )


def verify(snapshot_id: str) -> None:
    """Re-hash a snapshot and confirm it matches its manifest."""
    from alpha_cli.data_cmds import _snaps_root

    try:
        snapshot_dir = _snaps_root() / snapshot_id
        verify_snapshot(snapshot_dir, timeframe=snapshot_timeframe(snapshot_dir))
    except DataError as exc:  # missing snapshot or a hash mismatch (corruption)
        raise typer.BadParameter(str(exc)) from exc
    typer.echo(f"snapshot {snapshot_id}: integrity OK")
