"""``/api/rules`` — the owner's saved rule strategies via ``alpha rules``."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException

from alpha_web import _rules
from alpha_web._catalog import _run_json
from alpha_web.api._common import data_dir
from alpha_web.api.errors import safe_message
from alpha_web.api.models import RuleList
from alpha_web.api.rule_evaluation_models import RuleEvaluationRequest, RuleEvaluationResponse

router = APIRouter(prefix="/api", tags=["rules"])


@router.post("/rules/evaluate", response_model=RuleEvaluationResponse)
def evaluate_rule(body: RuleEvaluationRequest) -> dict[str, Any]:
    """Relay canonical condition results; never infer a signal or execute a strategy."""
    args = ["rules", "explain", body.rules_id, body.symbol, "--json"]
    if body.as_of is not None:
        args += ["--as-of", body.as_of]
    try:
        result: dict[str, Any] = _run_json(args, data_dir=data_dir())
        if isinstance(result.get("error"), str):
            result["error"] = safe_message(result["error"], fallback="rule evaluation failed")
        return result
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.get("/rules", response_model=RuleList)
def list_rules() -> dict[str, Any]:
    """Every saved rule set (a hand-edited invalid file is listed with its error, never hidden)."""
    return _rules.list_rules(data_dir=data_dir())
