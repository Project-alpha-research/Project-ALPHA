"""Where each RD-Agent path is, when the owner wrote no config.

Every path has one rule: the data home for what ALPHA writes, the checkout for what the worker
setup script installs, and the two environment variables the script prints for the worker paths.
Nothing here reads a key file, starts a process or writes a file.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

LAUNCHER = Path("workers/rdagent/factor_loop_launch.py")
SETUP_HINT = "bash scripts/setup_rdagent.sh --with-factor-runtime"
# Ask the setup script's own variables first; they are what it tells the owner to export.
SOURCE_VARIABLE = "ALPHA_RDAGENT_SOURCE"
PYTHON_VARIABLE = "ALPHA_FACTOR_PYTHON"
RUNTIME = Path(".alpha/state/runtime")
# The fix for each setting, in one sentence.
FIXES: dict[str, str] = {
    "working_directory": "Run this from inside the Project-ALPHA folder, or set working_directory.",
    "data_dir": "Set ALPHA_DATA_DIR to your data folder, or set data_dir.",
    "rdagent_source": f"Run `{SETUP_HINT}`, or set {SOURCE_VARIABLE}, or set rdagent_source.",
    "factor_python": f"Run `{SETUP_HINT}`, or set {PYTHON_VARIABLE}, or set factor_python.",
}


def find_checkout() -> Path | None:
    """The Project-ALPHA folder this code runs from: the nearest parent that holds the launcher."""
    for folder in Path(__file__).resolve().parents:
        if (folder / LAUNCHER).is_file():
            return folder
    return None


def default_paths(home: Path, environ: Mapping[str, str], checkout: Path | None) -> dict[str, Path]:
    """The default for each path setting. A setting is left out when it cannot be derived."""
    found: dict[str, Path] = {
        "data_dir": home,
        "gateway_data_dir": home / "rdagent" / "gateway-state",
        "trial_ledger": home / "rdagent" / "trial-ledger" / "rdagent-factor-trials.jsonl",
    }
    if checkout is not None:
        found["working_directory"] = checkout
        found["rdagent_source"] = checkout / RUNTIME / "rdagent-source"
        found["factor_python"] = checkout / RUNTIME / "rdagent-factor-py311/venv/bin/python"
    if environ.get(SOURCE_VARIABLE):
        found["rdagent_source"] = Path(environ[SOURCE_VARIABLE])
    if environ.get(PYTHON_VARIABLE):
        found["factor_python"] = Path(environ[PYTHON_VARIABLE])
    return found


def missing_defaults(paths: Mapping[str, Path]) -> list[tuple[str, Path]]:
    """The settings whose default path is not there yet. Folders ALPHA creates are not listed."""
    return [(k, p) for k, p in paths.items() if k in FIXES and not p.exists()]
