"""Suite-wide terminal determinism for CLI assertions, plus the alpha/platform tier marker.

``typer.rich_utils`` forces a colour terminal at import time whenever ``GITHUB_ACTIONS``,
``FORCE_COLOR`` or ``PY_COLORS`` is set (it does not honour ``NO_COLOR``), so on GitHub
runners help and error panels carry ANSI sequences and plain-token assertions fail
CI-only. This conftest runs before any test module imports typer: it strips the forcing
variables and sets ``NO_COLOR`` so the suite renders identically on every terminal.

``pytest_collection_modifyitems`` applies the ``platform`` marker from ``tests/_tiers.py`` so the
fast gate can run ``-m "not platform"`` (the alpha tier) without touching any test file.
"""

import os
from pathlib import Path

import pytest
from run_owned_test import require_test_owner

from tests._tiers import classify_platform

os.environ["NO_COLOR"] = "1"
for _name in ("GITHUB_ACTIONS", "FORCE_COLOR", "PY_COLORS"):
    os.environ.pop(_name, None)

_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def owned_test_process() -> None:
    """Reject unsupported orphan tests before their bodies launch processes."""
    try:
        require_test_owner()
    except RuntimeError as exc:
        pytest.fail(str(exc), pytrace=False)


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    for item in items:
        rel = Path(str(item.fspath)).resolve().relative_to(_ROOT).as_posix()
        if classify_platform(rel):
            item.add_marker(pytest.mark.platform)


def pytest_unconfigure(config: pytest.Config) -> None:  # TEMPORARY m159 probe
    import sys
    import time

    if hasattr(config, "workerinput"):
        return
    try:
        owner = int(os.environ.get("ALPHA_TEST_OWNER", "0:0").split(":")[0])
    except ValueError:
        return
    me = os.getpid()
    for _ in range(4):
        time.sleep(0.5)
        for entry in Path("/proc").iterdir():
            if not entry.name.isdecimal() or int(entry.name) == me:
                continue
            try:
                fields = (entry / "stat").read_text().rsplit(")", 1)[1].split()
                cmd = (entry / "cmdline").read_bytes().replace(b"\0", b" ")[:200]
            except OSError:
                continue
            if fields[1] in (str(owner), str(me)) and fields[0] != "Z":
                print(f"M159-PROBE pid={entry.name} ppid={fields[1]} state={fields[0]} {cmd!r}", file=sys.stderr)
