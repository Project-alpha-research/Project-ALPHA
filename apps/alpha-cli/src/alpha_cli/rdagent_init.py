"""`alpha rdagent init`: write a config with every path filled in; report what is missing."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

from alpha_cli import rdagent_defaults
from alpha_cli.rdagent_run_config import RdagentConfigError
from alpha_core.atomic import write_text
from alpha_core.config import AlphaSettings

HEADER = """\
# RD-Agent config written by `alpha rdagent init`. Every path below was worked out for this machine.
# Change a path only if you keep that item somewhere else. A key you delete gets its default again.
# Optional keys (loop_n, discuss, chat_route, universe, key_file and others) are listed in
# research/examples/rdagent.example.toml. Leave them out to keep the launcher's own defaults.
"""


def write_init(path: Path, environ: Mapping[str, str]) -> dict[str, Path]:
    """Write the config; never replace a file. Returns the default path for each setting."""
    if path.exists():
        raise RdagentConfigError(f"The config file already exists: {path}. Edit it, or delete it.")
    home = AlphaSettings().data_dir.expanduser().resolve()
    paths = rdagent_defaults.default_paths(home, environ, rdagent_defaults.find_checkout())
    order = (
        "working_directory",
        "data_dir",
        "gateway_data_dir",
        "trial_ledger",
        "rdagent_source",
        "factor_python",
    )
    lines = [f'{key} = "{paths[key]}"' for key in order if key in paths]
    path.parent.mkdir(parents=True, exist_ok=True)
    write_text(path, HEADER + "\n".join(lines) + "\n")
    return paths


def init_text(path: Path, paths: Mapping[str, Path]) -> str:
    missing = rdagent_defaults.missing_defaults(paths)
    lines = [f"Wrote {path}."]
    lines += [
        f"Found: {k} = {p}"
        for k, p in paths.items()
        if k in rdagent_defaults.FIXES and (k, p) not in missing
    ]
    if "working_directory" not in paths:
        lines.append(f"Not found: working_directory. {rdagent_defaults.FIXES['working_directory']}")
    lines += [f"Not found: {k} ({p}). {rdagent_defaults.FIXES[k]}" for k, p in missing]
    lines.append("ALPHA makes the gateway and ledger folders when a run starts.")
    lines.append("Check it with: alpha rdagent run --dry-run")
    return "\n".join(lines)
