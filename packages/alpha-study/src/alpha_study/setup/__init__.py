"""Daily setup specifications and causal candidate inspection (no execution authority)."""

from alpha_study.setup.evaluate import find_candidates, summarise
from alpha_study.setup.expr import CompiledExpr, compile_expr
from alpha_study.setup.spec import SetupSpec

__all__ = ["CompiledExpr", "SetupSpec", "compile_expr", "find_candidates", "summarise"]
