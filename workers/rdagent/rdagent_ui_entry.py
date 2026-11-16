"""Streamlit script that runs RD-Agent's own log viewer (``rdagent/log/ui/app.py``) unmodified.

Started by ``rdagent_viewer.py`` with the hash-pinned UI runtime. It verifies the pinned source,
imports RD-Agent through the same narrow finder as the factor loop (the source root is never on
``sys.path``), makes ALPHA's worker classes importable so pickled ALPHA scenarios load, then runs
the upstream app module. Streamlit re-executes this file on every interaction; the source is
verified once per process.
"""

from __future__ import annotations

import os
import runpy
import sys
from pathlib import Path

WORKER = Path(__file__).resolve().parent
if str(WORKER) not in sys.path:
    sys.path.insert(0, str(WORKER))

from stock_fixture_entry import SourceFinder  # noqa: E402

if not any(isinstance(finder, SourceFinder) for finder in sys.meta_path):
    from source_pin import verify_source

    source = Path(os.environ["ALPHA_RDAGENT_SOURCE"])
    verify_source(source)
    sys.meta_path.insert(0, SourceFinder(source))

runpy.run_module("rdagent.log.ui.app", run_name="__main__")
