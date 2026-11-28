"""Launch checks of the ALPHA-judged factor loop: refusals before any folder or process exists.

Standard library only. ``factor_loop_launch.py`` calls ``validate`` first; it stops on a refusal.
"""

from __future__ import annotations

import argparse
import math
import subprocess
from pathlib import Path

MAX_CALLS = 60
SETUP_HINT = "bash scripts/setup_rdagent.sh --with-factor-runtime"
# The paid route's settings reach only the gateway process, never another child.
GATEWAY_SECRETS = ("ALPHA_GATEWAY_API_KEY", "ALPHA_GATEWAY_API_BASE")


class LaunchError(Exception):
    """A refusal or failed step, with a plain message."""


def _inside_git(path: Path) -> bool:
    probe = path
    while not probe.exists():
        probe = probe.parent
    result = subprocess.run(
        ["git", "-C", str(probe), "rev-parse", "--is-inside-work-tree"],
        env={"PATH": "/usr/bin:/bin", "LANG": "C"},
        capture_output=True,
        text=True,
        check=False,
    )
    return result.returncode == 0 and result.stdout.strip() == "true"


def validate(args: argparse.Namespace, environ: dict[str, str]) -> dict[str, Path]:
    if not 1 <= args.coder_max_loop <= 3:
        raise LaunchError("--coder-max-loop must be 1, 2 or 3")
    if not 1 <= args.loop_n <= 3:
        raise LaunchError("--loop-n must be 1, 2 or 3")
    if not 1 <= args.run_max_calls <= MAX_CALLS:
        raise LaunchError(f"--run-max-calls must be between 1 and {MAX_CALLS}")
    if args.discuss_wait_minutes < 0:
        raise LaunchError("--discuss-wait-minutes must be non-negative")
    if args.wall_seconds <= 0:
        raise LaunchError("--wall-seconds must be positive")
    if not 0 < args.api_timeout <= 900:
        raise LaunchError("--api-timeout must be between 0 and 900 seconds")
    if not 0 <= args.provider_retries <= 3:
        raise LaunchError("--provider-retries must be 0, 1, 2 or 3")
    if args.family_switch_after < 1:
        raise LaunchError("--family-switch-after must be at least 1")
    if args.coding_reasoning_tokens is not None:
        raise LaunchError(
            "--coding-reasoning-tokens is unset until the provider request field is confirmed"
        )
    if args.universe is not None and not args.universe.is_absolute():
        raise LaunchError("--universe must be an absolute path")
    if args.chat_route == "api":
        if not args.api_model or not args.api_price_in_per_mtok or not args.api_price_out_per_mtok:
            raise LaunchError(
                "--chat-route api needs --api-model, --api-price-in-per-mtok and "
                "--api-price-out-per-mtok"
            )
        if any(not environ.get(key) for key in GATEWAY_SECRETS):
            raise LaunchError(
                "--chat-route api needs ALPHA_GATEWAY_API_BASE and ALPHA_GATEWAY_API_KEY in the "
                "launcher's environment (load the owner's file in the same command; never print it)"
            )
    if args.embedding_route == "provider":
        price = args.provider_embed_usd_per_mtok
        if not args.provider_embed_model or price is None or not math.isfinite(price) or price <= 0:
            raise LaunchError(
                "--embedding-route provider needs --provider-embed-model and a positive "
                "--provider-embed-usd-per-mtok"
            )
        if any(not environ.get(key) for key in GATEWAY_SECRETS):
            raise LaunchError(
                "--embedding-route provider needs ALPHA_GATEWAY_API_BASE and ALPHA_GATEWAY_API_KEY"
            )
    for name in ("data_dir", "run_dir", "gateway_data_dir", "trial_ledger"):
        if not getattr(args, name).is_absolute():
            raise LaunchError(f"--{name.replace('_', '-')} must be an absolute path")
    if args.run_dir.exists():
        raise LaunchError(f"run directory already exists: {args.run_dir}")
    if not args.trial_ledger.parent.is_dir():
        raise LaunchError("the trial ledger's parent directory must exist")
    for name in ("run_dir", "gateway_data_dir", "trial_ledger"):
        if _inside_git(getattr(args, name)):
            raise LaunchError(f"--{name.replace('_', '-')} must be outside every git work tree")
    # Memory is checked after the trial ledger, whose folder gives its default location, so a
    # relative --trial-ledger is reported as such rather than as a bad --memory-dir.
    if not args.no_memory:
        args.memory_dir = args.memory_dir or args.trial_ledger.parent / "research-memory"
        if not args.memory_dir.is_absolute():
            raise LaunchError("--memory-dir must be an absolute path")
        if _inside_git(args.memory_dir.resolve()):
            raise LaunchError("--memory-dir must be outside every git work tree")
    paths = {}
    for key in ("ALPHA_RDAGENT_SOURCE", "ALPHA_FACTOR_PYTHON"):
        value = environ.get(key, "")
        if not value or not Path(value).exists():
            raise LaunchError(f"{key} is not set or missing; run: {SETUP_HINT}")
        paths[key] = Path(value)
    return paths
