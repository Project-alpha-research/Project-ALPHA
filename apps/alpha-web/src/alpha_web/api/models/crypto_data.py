"""Crypto data contracts."""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from ._base import StrictModel
from .projects import JsonObject

type CryptoFamilyValue = Literal[
    "market_bars",
    "trades",
    "aggregate_trades",
    "book_snapshots",
    "market_membership",
    "instrument_catalog",
    "derivative_bars",
    "derivative_trades",
    "derivative_book_snapshots",
    "funding",
    "open_interest",
    "long_short_ratio",
    "mark_bars",
    "index_bars",
    "premium_bars",
    "option_instruments",
    "option_quotes",
    "historical_volatility",
    "asset_metadata",
    "market_reference",
    "protocol_tvl",
    "stablecoin_supply",
    "yield_pools",
    "yield_history",
    "onchain_catalog",
    "onchain_metrics",
    "dex_pools",
    "dex_ohlcv",
    "dex_transactions",
    "comparison_bars",
    "defi_tvl",
]
type CryptoProviderValue = Literal[
    "binance",
    "bybit",
    "coingecko",
    "geckoterminal",
    "coinmetrics",
    "defillama",
    "ccxt:coinbase",
]
type CryptoQualificationStateValue = Literal[
    "unverified", "unavailable", "qualified", "warning", "quarantined"
]


class CryptoAuthorityRow(StrictModel):
    family: CryptoFamilyValue
    provider: str
    role: Literal["primary_acquisition", "diagnostic_comparison"]


class CryptoCatalogResponse(StrictModel):
    families: list[CryptoAuthorityRow]
    automatic_fallback: Literal[False]
    execution_authority: Literal[False]
    next_action: str


class CryptoCapabilityItem(StrictModel):
    schema_version: Literal[1]
    provider: str
    family: CryptoFamilyValue
    authentication: Literal["none", "demo_key"]
    earliest: str | None
    latest: str | None
    frequencies: list[str]
    limits: list[str]
    verification_state: Literal["not_verified", "receipt_verified"]
    qualification_state: CryptoQualificationStateValue


class CryptoCapabilitiesResponse(StrictModel):
    items: list[CryptoCapabilityItem]
    count: int = Field(ge=0)
    receipt_verified_count: int = Field(ge=0)
    qualified_count: int = Field(ge=0)
    provider_probe_performed: Literal[False]
    automatic_fallback: Literal[False]
    execution_authority: Literal[False]
    canonical_next_action: str


class CryptoMarketCatalogItem(StrictModel):
    pair: str
    provider_symbol: str
    base_asset: str
    quote_asset: str
    status: str


class CryptoMarketCatalogResponse(StrictModel):
    state: Literal["available", "unavailable"]
    venue: Literal["binance"]
    market_type: Literal["spot"]
    as_of: str | None
    stale: bool
    total_matches: int = Field(ge=0)
    markets: list[CryptoMarketCatalogItem]
    next_action: str


class CryptoStorageResponse(StrictModel):
    verification: Literal["not_checked", "metadata_only", "artifact_verified"] = "not_checked"
    identity_backend: Literal["macos_volume_uuid", "cloud_root_identity"] | None = None
    state: Literal["ready", "blocked"]
    blocker: str | None
    bulk_root_label: str
    manifest_count: int = Field(ge=0)
    next_action: str
    free_bytes: int | None = Field(default=None, ge=0)
    total_bytes: int | None = Field(default=None, ge=0)
    reserve_fraction: float | None = Field(default=None, ge=0, lt=1)
    minimum_free_bytes: int | None = Field(default=None, ge=0)
    cache_bytes: int = Field(ge=0)


class CryptoStorageInventoryResponse(StrictModel):
    manifest_count: int = Field(ge=0)
    snapshot_count: int = Field(ge=0)
    counts_by_kind: dict[str, int]
    bytes_by_kind: dict[str, int]
    cache_bytes: int = Field(ge=0)
    staging_count: int = Field(ge=0)
    private_paths_exposed: Literal[False]
    next_action: str


class CryptoStorageVerifyResponse(StrictModel):
    state: Literal["verified"]
    manifest_count: int = Field(ge=0)
    snapshot_count: int = Field(ge=0)
    research_eligible_snapshot_count: int = Field(ge=0)
    asset_master_count: int = Field(ge=0)
    cache_bytes: int = Field(ge=0)
    private_paths_exposed: Literal[False]
    next_action: str


class CryptoCacheCleanRequest(StrictModel):
    confirm: Literal[True]


class CryptoCacheCleanResponse(StrictModel):
    state: Literal["cleaned"]
    removed_bytes: int = Field(ge=0)
    immutable_artifacts_removed: Literal[0]
    private_paths_exposed: Literal[False]
    next_action: str


class CryptoEstimateRequest(StrictModel):
    family: CryptoFamilyValue
    instruments: int = Field(default=1, ge=1, le=250)
    days: int = Field(default=30, ge=1, le=3_650)
    frequency: Literal[
        "1d", "3d", "1w", "12h", "8h", "6h", "4h", "2h", "1h", "30m", "15m", "5m", "1m", "tick"
    ] = "1d"


class CryptoEstimateResponse(StrictModel):
    family: CryptoFamilyValue
    provider: str
    instruments: int
    days: int
    frequency: str
    estimated_rows: int = Field(ge=0)
    estimated_bytes: int = Field(ge=0)
    bounded: Literal[True]
    estimate_only: Literal[True]
    next_action: str


class CryptoCoverageItem(StrictModel):
    manifest_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    provider: str
    venue: str
    market_type: Literal["spot", "linear", "inverse", "option", "dex", "network", "reference"]
    family: CryptoFamilyValue
    instrument: str
    base_asset: str | None
    quote_asset: str | None
    frequency: str
    units: str
    timestamp_convention: str
    state: CryptoQualificationStateValue
    failures: list[str]
    warnings: list[str]
    observed_start: str | None
    observed_end: str | None
    row_count: int = Field(ge=0)
    artifact_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    method_version: str
    fetched_at: str | None


class CryptoCoverageResponse(StrictModel):
    verification: Literal["not_checked", "metadata_only", "artifact_verified"] = "not_checked"
    items: list[CryptoCoverageItem]
    count: int = Field(ge=0)
    canonical_next_action: str
    automatic_fallback: Literal[False]
    execution_authority: Literal[False]


class CryptoQualityReportResponse(StrictModel):
    schema_version: Literal[1]
    dataset_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    method_version: str
    state: CryptoQualificationStateValue
    failures: list[str]
    warnings: list[str]
    observed_start: str | None
    observed_end: str | None
    row_count: int = Field(ge=0)
    correction_lineage: list[str]


class CryptoDatasetIdentityResponse(StrictModel):
    provider: str
    venue: str
    market_type: Literal["spot", "linear", "inverse", "option", "dex", "network", "reference"]
    family: CryptoFamilyValue
    instrument: str
    base_asset: str | None
    quote_asset: str | None
    frequency: str
    units: str
    timestamp_convention: str


class CryptoQualityResponse(StrictModel):
    manifest_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    dataset: CryptoDatasetIdentityResponse
    quality: CryptoQualityReportResponse
    next_action: str


type CryptoFeatureNameValue = Literal[
    "funding",
    "open_interest_change",
    "basis",
    "volatility_surface",
    "liquidity",
    "onchain_change",
    "defi_tvl_residual",
]


class CryptoFeatureCreateRequest(StrictModel):
    feature_name: CryptoFeatureNameValue
    inputs: dict[str, str] = Field(min_length=1, max_length=3)


class CryptoFeatureResponse(StrictModel):
    manifest_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    feature_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    feature_name: CryptoFeatureNameValue
    method_version: str
    available_at: str
    row_count: int = Field(ge=1)
    artifact_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    input_count: int = Field(ge=1, le=3)
    state: Literal["frozen", "verified"]
    research_authority: Literal[False]
    execution_authority: Literal[False]
    next_action: str | None = None


class CryptoFeatureListResponse(StrictModel):
    items: list[CryptoFeatureResponse]
    count: int = Field(ge=0)
    research_authority: Literal[False]
    execution_authority: Literal[False]
    next_action: str


type CryptoCoverageCadenceValue = Literal["daily", "hourly", "five_minute", "funding_interval"]


class CryptoAcquisitionRequest(StrictModel):
    provider: CryptoProviderValue
    family: CryptoFamilyValue
    instrument: str = Field(min_length=1, max_length=160, pattern=r"^[A-Za-z0-9._:/-]+$")
    base: str = Field(min_length=1, max_length=32, pattern=r"^[A-Za-z0-9._-]+$")
    quote: str = Field(min_length=1, max_length=32, pattern=r"^[A-Za-z0-9._-]+$")
    category: Literal["spot", "linear", "inverse", "option"] = "linear"
    frequency: Literal[
        "1d",
        "3d",
        "1w",
        "12h",
        "8h",
        "6h",
        "4h",
        "2h",
        "1h",
        "30m",
        "15m",
        "5m",
        "1m",
        "catalog_snapshot",
    ] = "1h"
    period: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}$")
    network: str | None = Field(default=None, max_length=80, pattern=r"^[A-Za-z0-9._-]+$")
    pool_address: str | None = Field(default=None, max_length=160, pattern=r"^[A-Za-z0-9._:-]+$")
    metrics: list[str] = Field(default_factory=list, max_length=32)
    start: str | None = Field(default=None, max_length=64)
    end: str | None = Field(default=None, max_length=64)
    case_id: str | None = Field(default=None, min_length=1, max_length=80)
    expected_case_revision: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    reason: str | None = Field(default=None, min_length=1, max_length=500)


class CryptoSnapshotCreateRequest(StrictModel):
    manifest_ids: list[str] = Field(min_length=1, max_length=128)
    asset_master_version: str = Field(
        default="reviewed-native-v1", pattern=r"^(?:reviewed-native-v1|[0-9a-f]{64})$"
    )


class CryptoSnapshotCreateResponse(StrictModel):
    snapshot_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    member_count: int = Field(ge=1)
    families: list[CryptoFamilyValue]
    providers: list[str]
    asset_master_version: str
    state: Literal["frozen"]
    next_action: str
    execution_authority: Literal[False]


class CryptoAssetMasterCreateRequest(StrictModel):
    coingecko_manifest_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    geckoterminal_manifest_ids: list[str] = Field(min_length=1, max_length=5)


class CryptoAssetMasterResponse(StrictModel):
    asset_master_version: str = Field(pattern=r"^[0-9a-f]{64}$")
    identity_count: int = Field(ge=2)
    contract_identity_count: int = Field(ge=0)
    ticker_join_allowed: Literal[False]
    state: Literal["frozen", "verified"]
    next_action: str
    source_manifest_ids: list[str] | None = None


class CryptoAssetMasterListItem(StrictModel):
    asset_master_version: str
    identity_count: int = Field(ge=2)
    contract_identity_count: int = Field(ge=0)
    builtin: bool
    state: Literal["verified"]


class CryptoAssetMasterListResponse(StrictModel):
    items: list[CryptoAssetMasterListItem]
    count: int = Field(ge=1)
    ticker_join_allowed: Literal[False]
    next_action: str


class CryptoSnapshotVerifyRequest(StrictModel):
    required_families: list[CryptoFamilyValue] = Field(default_factory=list, max_length=20)
    purpose: Literal["research", "validation", "execution_price"] = "research"


class CryptoSnapshotVerifyResponse(StrictModel):
    snapshot_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    eligible: bool
    purpose: Literal["research", "validation", "execution_price"]
    qualified_families: list[CryptoFamilyValue]
    supplemental_families: list[CryptoFamilyValue]
    blockers: list[str]
    next_action: str
    execution_authority: Literal[False]


class CryptoSnapshotRegisterRequest(StrictModel):
    symbol: str = Field(min_length=1, max_length=32, pattern=r"^[A-Za-z0-9-]+$")


class CryptoSnapshotRegisterResponse(StrictModel):
    ref_id: str = Field(pattern=r"^rd_[0-9a-f]{64}$")
    dataset_kind: Literal["snapshot"]
    instrument: str
    provider: Literal["crypto-data-house"]
    start_ts: str
    end_ts: str
    bar_duration_minutes: int | None
    origin: JsonObject
    research_only: Literal[True]
    registered_by: str
    registered_at: str
