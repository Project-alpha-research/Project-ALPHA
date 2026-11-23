"""Owner rule strategies via the CLI (``alpha rules … --json``): list.

Every call is a subprocess of the audited CLI; the web layer never parses a rule itself. It confers no authority.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from alpha_web._catalog import _run_json


def list_rules(*, data_dir: Path) -> dict[str, Any]:
    result: dict[str, Any] = _run_json(["rules", "list", "--json"], data_dir=data_dir)
    return result
