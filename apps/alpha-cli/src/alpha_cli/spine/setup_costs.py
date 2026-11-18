"""One per-asset cost policy for setup studies and trades."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from alpha_cli.spine.spec import Costs
from alpha_cli.spine.stores import ResolvedAsset, resolve_asset

SHORT_BORROW_BPS_PER_YEAR = 50
SHORT_CARRY_BPS_PER_DAY = 3
SHORT_COST_RULE = (
    f"Stocks assume {SHORT_BORROW_BPS_PER_YEAR} bps annual borrow divided by 365. "
    f"Crypto assumes {SHORT_CARRY_BPS_PER_DAY} bps per calendar day for perpetual funding. "
    "Carry includes weekends and the exit day when held beyond its open."
)
CRYPTO_FEE_BPS = 10.0
CRYPTO_SLIPPAGE_BPS = 5.0
# The store's own adapters (packages/alpha-data/src/alpha_data/adapters).
CRYPTO_PROVIDERS = frozenset({"binance", "bybit", "ccxt"})
EQUITY_PROVIDERS = frozenset({"alpaca", "tiingo", "stooq", "yfinance"})


def setup_market(resolved_asset: ResolvedAsset) -> str | None:
    """Use the resolved store's dataset identity, then legacy pair/provider identity."""
    from alpha_data.store import ParquetStore

    path = ParquetStore(resolved_asset.data_dir / "store")._provenance_path(resolved_asset.symbol)
    if path.exists():
        provenance = json.loads(path.read_text())
        dataset = provenance.get("dataset")
        if isinstance(dataset, dict):
            market = dataset.get("asset_class")
            if market == "crypto":
                return "crypto"
            if market in {"equity", "stock", "etf"}:
                return "equity"
            return None
    # The existing engine recognises slash pairs as crypto. Legacy stock providers have
    # no dataset identity; an unknown provider/symbol combination gets the higher costs.
    # Provider names may carry a venue ("ccxt:binance"): every part is checked.
    parts = set(resolved_asset.source.lower().split(":"))
    if "/" in resolved_asset.symbol or parts & CRYPTO_PROVIDERS:
        return "crypto"
    if parts & EQUITY_PROVIDERS:
        return "equity"
    return None


def setup_costs(resolved_asset: ResolvedAsset) -> Costs:
    return _market_costs(setup_market(resolved_asset))


def _market_costs(market: str | None) -> Costs:
    return (
        Costs()
        if market == "equity"
        else Costs(fee_bps=CRYPTO_FEE_BPS, slippage_bps=CRYPTO_SLIPPAGE_BPS)
    )


def asset_costs(
    home: Path, assets: list[str], *, direction: str = "long"
) -> tuple[dict[str, Any], list[str]]:
    values = {}
    labels = ["short-costs-assumed"] if direction == "short" else []
    for asset in assets:
        market = setup_market(resolve_asset(asset, data_dir=home))
        cost = _market_costs(market).model_dump()
        if direction == "short":
            if market == "equity":
                cost["short_borrow_bps_per_year"] = SHORT_BORROW_BPS_PER_YEAR
            else:
                cost["short_carry_bps_per_day"] = SHORT_CARRY_BPS_PER_DAY
                if market == "crypto" and "short-needs-perpetual" not in labels:
                    labels.append("short-needs-perpetual")
        values[asset] = cost
        if market is None and "costs-assumed-high" not in labels:
            labels.append("costs-assumed-high")
    return values, labels


def daily_carry(costs: dict[str, Any]) -> float:
    if "short_borrow_bps_per_year" in costs:
        return float(costs["short_borrow_bps_per_year"]) / 10000 / 365
    return float(costs.get("short_carry_bps_per_day", 0)) / 10000


def round_trip(costs: dict[str, Any]) -> float:
    return 2 * (float(costs["fee_bps"]) + float(costs["slippage_bps"])) / 10000
