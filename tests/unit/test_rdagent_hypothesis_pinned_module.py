"""The pinned upstream gen reads APIBackend from rdagent.components.proposal globals."""

from __future__ import annotations

from typing import Any


def test_pinned_gen_reads_backend_from_components_proposal() -> None:
    from tests.unit._rdagent_support import upstream_class

    namespace: dict[str, Any] = {}
    cls = upstream_class("components/proposal/__init__.py", "LLMHypothesisGen", {"gen"}, namespace)
    assert "APIBackend" in cls.gen.__code__.co_names, (
        "upstream gen no longer reads APIBackend in rdagent.components.proposal; "
        "AlphaFactorHypothesisGen.gen swaps the wrong module"
    )
