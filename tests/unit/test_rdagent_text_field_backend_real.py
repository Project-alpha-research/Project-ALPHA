"""The RD-Agent hypothesis step against the pinned upstream code, with a fake model reply.

The upstream proposer asks its backend for ``dict[str, str]``. A model sometimes answers a text
field with a nested object, and upstream then fails the run. ``text_field_backend`` keeps such a
value as JSON text. ``APIBackend`` upstream is a factory function, not a class, so the wrapper
must work on what the factory builds. This test runs the real upstream call path in RD-Agent's
own Python runtime; it is skipped where that runtime is not installed.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]

_PROBE = """
import json, sys
sys.path[:0] = [sys.argv[1], sys.argv[2]]
from rdagent.oai import llm_utils
from rdagent.oai.backend.base import APIBackend as Base
import alpha_factor_judge

assert not isinstance(llm_utils.APIBackend, type), "upstream APIBackend is a factory function"

class Fake(Base):
    use_chat_cache = False
    dump_chat_cache = False

    def __init__(self, *args, **kwargs):
        self.retry_wait_seconds = 0

    def _create_chat_completion_inner_function(self, messages, **kwargs):
        reply = {"hypothesis": "h", "specific_task": {"factor_name": "x", "why": ["a"]}}
        return json.dumps(reply), "stop"

    def supports_response_schema(self):
        return False

    def _calculate_token_from_messages(self, messages):
        return 1

    def _create_embedding_inner_function(self, *args, **kwargs):
        return []

    @property
    def chat_token_limit(self):
        return 100000

def factory(*args, **kwargs):
    return Fake()

backend = alpha_factor_judge.text_field_backend(factory)()
print(backend._try_create_chat_completion_or_embedding(
    chat_completion=True, max_retry=1, messages=[{"role": "user", "content": "q"}],
    json_mode=True, json_target_type=dict[str, str],
))
"""


def test_a_nested_text_field_passes_the_real_upstream_type_check() -> None:
    python = os.environ.get("ALPHA_FACTOR_PYTHON")
    source = os.environ.get("ALPHA_RDAGENT_SOURCE")
    if not python or not source:
        pytest.skip("the RD-Agent runtime and the pinned source are not configured")
    done = subprocess.run(
        [python, "-c", _PROBE, source, str(ROOT / "workers" / "rdagent")],
        capture_output=True,
        text=True,
        timeout=300,
        check=False,
    )
    assert done.returncode == 0, done.stderr[-2000:]
    reply = json.loads(done.stdout.strip().splitlines()[-1])
    assert reply["hypothesis"] == "h"
    assert json.loads(reply["specific_task"]) == {"factor_name": "x", "why": ["a"]}
