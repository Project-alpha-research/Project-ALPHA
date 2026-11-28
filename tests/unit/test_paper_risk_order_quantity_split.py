"""PaperRiskLimits and normalize_order_quantity leave base.py for their own modules, unchanged."""

from __future__ import annotations

import importlib
from pathlib import Path

import pytest

from alpha_core import DataError

BASE = (
    Path(__file__).resolve().parents[2]
    / "packages"
    / "alpha-strategies"
    / "src"
    / "alpha_strategies"
    / "base.py"
)


def _limits_kwargs() -> dict[str, object]:
    return {
        "max_order_notional": 1_000.0,
        "max_position_notional": 2_000.0,
        "max_gross_notional": 3_000.0,
        "daily_loss_fraction": 0.05,
        "max_open_orders": 2,
        "max_quote_age_seconds": 5.0,
        "intent_id": "a" * 64,
    }


def test_paper_risk_limits_is_defined_in_paper_risk() -> None:
    module = importlib.import_module("alpha_strategies.paper_risk")
    limits_cls = module.PaperRiskLimits
    assert limits_cls.__module__ == "alpha_strategies.paper_risk"
    limits = limits_cls(**_limits_kwargs())
    assert limits.max_order_notional == pytest.approx(1_000.0)
    assert limits.account_id is None
    bad = _limits_kwargs()
    bad["max_order_notional"] = 5_000.0
    with pytest.raises(DataError, match="max order notional"):
        limits_cls(**bad)
    bad = _limits_kwargs()
    bad["intent_id"] = "not-a-hash"
    with pytest.raises(DataError, match="SHA-256"):
        limits_cls(**bad)


def test_normalize_order_quantity_is_defined_in_order_quantity() -> None:
    module = importlib.import_module("alpha_strategies.order_quantity")
    normalize = module.normalize_order_quantity
    assert normalize.__module__ == "alpha_strategies.order_quantity"
    lots = normalize(2.6, size_precision=0, size_increment=1.0)
    assert lots is not None
    assert float(lots) == pytest.approx(3.0)
    assert normalize(-0.4, size_precision=0, size_increment=1.0) is None
    fractional = normalize(0.157, size_precision=2, size_increment=0.05)
    assert fractional is not None
    assert float(fractional) == pytest.approx(0.15)
    assert normalize(0.01, size_precision=2, size_increment=0.05) is None
    with pytest.raises(DataError, match="size_increment"):
        normalize(1.0, size_precision=2, size_increment=0.0)


def test_base_no_longer_defines_the_moved_names() -> None:
    text = BASE.read_text(encoding="utf-8")
    assert "class PaperRiskLimits" not in text
    assert "def normalize_order_quantity" not in text
    assert len(text.splitlines()) < 800


def test_vol_target_strategy_stays_in_base() -> None:
    base = importlib.import_module("alpha_strategies.base")
    assert base.VolTargetStrategy.__module__ == "alpha_strategies.base"
    assert hasattr(base.VolTargetStrategy, "configure_paper_risk")
