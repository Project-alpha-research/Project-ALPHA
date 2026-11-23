"""One fail-closed resolver for empirical Workstation launch context."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

type RequestedRunContextKind = Literal["governed_project", "standalone_sandbox"]


@dataclass(frozen=True, slots=True)
class RunContextDenied(Exception):
    status_code: int
    detail: str


def resolve_run_context(
    *,
    kind: RequestedRunContextKind,
    project_id: str | None,
    data_dir: Path,
) -> dict[str, object]:
    """Resolve a caller request to the canonical context inherited by an empirical child."""
    if kind == "standalone_sandbox":
        if project_id is not None:
            raise RunContextDenied(422, "standalone run context cannot name a project")
        return {
            "schema_version": 1,
            "kind": "standalone_sandbox",
            "watermark": "STANDALONE_UNQUALIFIED",
        }
    raise RunContextDenied(422, "governed-project run context is no longer available")
