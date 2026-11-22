"""``/api/ml-runs``: stored ML runs for the Machine learning window. Read-only; trains nothing."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from alpha_web import _ml_runs
from alpha_web.api._common import data_dir
from alpha_web.api.models.ml_runs import MlRunList

router = APIRouter(prefix="/api", tags=["ml"])


@router.get("/ml-runs", response_model=MlRunList)
def list_ml_runs() -> dict[str, Any]:
    """The newest stored runs made by ``alpha ml run``, each with its split, model and folds."""
    return _ml_runs.ml_runs(data_dir=data_dir())
