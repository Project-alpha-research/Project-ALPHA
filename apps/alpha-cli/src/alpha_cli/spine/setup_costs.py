"""One per-asset cost policy for setup studies and trades."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from alpha_cli.spine.spec import Costs
from alpha_cli.spine.stores import ResolvedAsset, resolve_asset

CRYPTO_FEE_BPS = 10.0
CRYPTO_SLIPPAGE_BPS = 5.0


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
    if "/" in resolved_asset.symbol or resolved_asset.source.lower() in {
        "binance",
        "bybit",
        "ccxt",
    }:
        return "crypto"
    if resolved_asset.source.lower() in {"alpaca", "tiingo", "stooq"}:
        return "equity"
    return None


def setup_costs(resolved_asset: ResolvedAsset) -> Costs:
    return (
        Costs()
        if setup_market(resolved_asset) == "equity"
        else Costs(fee_bps=CRYPTO_FEE_BPS, slippage_bps=CRYPTO_SLIPPAGE_BPS)
    )


def asset_costs(home: Path, assets: list[str]) -> tuple[dict[str, Any], list[str]]:
    values, labels = {}, []
    for asset in assets:
        resolved = resolve_asset(asset, data_dir=home)
        values[asset] = setup_costs(resolved).model_dump()
        if setup_market(resolved) is None and "costs-assumed-high" not in labels:
            labels.append("costs-assumed-high")
    return values, labels


def round_trip(costs: dict[str, Any]) -> float:
    return 2 * (float(costs["fee_bps"]) + float(costs["slippage_bps"])) / 10000
