"""The plan pointer in _crypto_backfill.py is a link at the tag pre-thin-2026-11-14.

docs/work/ was thinned away at that tag, so a bare local path under docs/work/ points
nowhere; the source comment must name the plan as a GitHub link at the tag instead.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "apps" / "alpha-cli" / "src" / "alpha_cli" / "_crypto_backfill.py"
TAG_PREFIX = "https://github.com/tradingsystem1880-eng/Project-ALPHA/blob/pre-thin-2026-11-14/"
PLAN = "docs/work/archive/2026-11/2026-11-14-prove-crypto-backfill/02-plan.md"


def test_backfill_source_names_plan_as_link_at_tag() -> None:
    text = SOURCE.read_text(encoding="utf-8")
    assert TAG_PREFIX + PLAN in text


def test_backfill_source_has_no_bare_local_work_path() -> None:
    text = SOURCE.read_text(encoding="utf-8")
    bare = []
    for line in text.splitlines():
        for match in re.finditer(r"docs/work/", line):
            before = line[: match.start()]
            if not before.endswith("/pre-thin-2026-11-14/"):
                bare.append(line.strip())
    assert bare == [], f"bare docs/work/ paths remain: {bare}"


def test_backfill_module_still_imports() -> None:
    from alpha_cli import _crypto_backfill

    assert callable(_crypto_backfill.run_backfill)
    assert callable(_crypto_backfill.plan_windows)
