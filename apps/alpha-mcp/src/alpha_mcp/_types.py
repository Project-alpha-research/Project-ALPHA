"""Stable structured-output contracts for Workstation v3 MCP tools.

The CLI remains authoritative at runtime.  These ``TypedDict`` declarations make FastMCP publish
bounded, named output schemas instead of an opaque ``dict[str, Any]`` contract.
"""

from __future__ import annotations

from typing import Any, Literal, TypedDict

type JsonObject = dict[str, Any]
type BoundedJsonValue = (
    None | bool | int | float | str | list[BoundedJsonValue] | dict[str, BoundedJsonValue]
)
type LegacyRunManifestOut = dict[str, BoundedJsonValue]
type JobStatus = Literal["queued", "running", "succeeded", "failed", "cancelled"]


class LegacyRunSummaryOut(TypedDict):
    run_id: str
    command: str | None
    label: str | None


class DataInventoryOut(TypedDict):
    symbols: list[str]


class DataCandlesOut(TypedDict):
    symbol: str
    snapshot_id: str | None
    provenance: JsonObject
    bars: list[JsonObject]
    truncated: bool


class SnapshotListOut(TypedDict):
    snapshots: list[JsonObject]


class ProviderRegistryOut(TypedDict):
    providers: list[JsonObject]


class ControlJobOut(TypedDict):
    job_id: str
    kind: str
    status: JobStatus
    project_id: str | None
    experiment_id: str | None
    request: JsonObject
    created_at: str
    updated_at: str
    heartbeat_at: str
    result_run_id: str | None
    terminal_error: str | None
    last_sequence: int


class ControlJobEventOut(TypedDict):
    job_id: str
    sequence: int
    event_type: Literal[
        "created", "status", "heartbeat", "progress", "log", "result", "cancel_requested"
    ]
    occurred_at: str
    payload: JsonObject


class ControlJobDetailOut(ControlJobOut):
    events: list[ControlJobEventOut]
    event_total: int
    events_has_more: bool
    events_truncated: bool
    event_limit: int
    event_offset: int
    event_tail: bool


class ControlJobPageOut(TypedDict):
    items: list[ControlJobOut]
    limit: int
    offset: int
    has_more: bool


class JobCancellationOut(TypedDict):
    job_id: str
    status: Literal["cancellation_requested", "already_terminal"]


class JobReconciliationOut(TypedDict):
    items: list[ControlJobOut]
    count: int


ChartBarOut = TypedDict(  # noqa: UP013 - wire key `l` is required and E741 rejects a class field.
    "ChartBarOut",
    {"t": float, "o": float, "h": float, "l": float, "c": float, "v": float},
)


class EquitySeriesOut(TypedDict):
    ts: list[float]
    equity: list[float]
    drawdown: list[float]


class ChartTradeOut(TypedDict):
    instrument_id: str
    side: str
    quantity: float
    entry_price: float
    exit_price: float
    entry_ts: float
    exit_ts: float
    realized_pnl: float
    realized_return: float


class ChartTraceEventOut(TypedDict):
    sequence_id: int
    event_type: Literal["decision", "order", "fill", "trade"]
    ts: float
    parent_sequence_id: int | None
    instrument_id: str
    side: str | None
    quantity: float | None
    filled_quantity: float | None
    price: float | None
    status: str | None
    signal: int | None
    decision_reason: str | None
    entry_ts: float | None
    exit_ts: float | None
    entry_price: float | None
    exit_price: float | None
    realized_pnl: float | None
    realized_return: float | None


class ChartIndicatorOut(TypedDict):
    sequence_id: int
    decision_sequence_id: int | None
    ts: float
    instrument_id: str
    name: str
    value: float
    unit: str


class ChartAnnotationAnchorOut(TypedDict):
    anchor_index: int
    ts: float
    value: float


class ChartAnnotationOut(TypedDict):
    annotation_id: int
    decision_sequence_id: int | None
    kind: Literal["line", "polyline", "zone"]
    label: str
    unit: str
    reason: str
    anchors: list[ChartAnnotationAnchorOut]


class ChartFoldOut(TypedDict):
    fold: int
    semantics: Literal["fixed_rule_evaluation_no_refit", "fold_by_fold_refit"]
    train_start: float | int
    train_end: float | int
    validation_start: float | int | None
    validation_end: float | int | None
    test_start: float | int
    test_end: float | int


class ForecastSeriesOut(TypedDict):
    history: list[float]
    forecast: list[float]
    p10: list[float]
    q25: list[float]
    q75: list[float]
    p90: list[float]
    mean: list[float]
    history_ts: list[float]
    forecast_ts: list[float]


class ChartProvenanceOut(TypedDict):
    command: str | None
    symbol: str | None
    symbols: list[str] | None
    snapshot_id: str | None
    snapshot_hash: str | None
    timezone: Literal["UTC"]
    price_unit: Literal["native_quote"]
    artifact_contract_version: int | None
    as_of: float | None
    artifact_sha256: dict[str, str]


class ChartTruncationOut(TypedDict):
    bars: bool
    equity: bool
    trades: bool
    trace: bool
    indicators: bool
    annotations: bool


class ChartBundleOut(TypedDict):
    run_id: str
    trace_status: Literal["available", "trace_unavailable"]
    bars_status: Literal["available", "snapshot_unavailable", "not_applicable"]
    provenance: ChartProvenanceOut
    bars: list[ChartBarOut]
    equity: EquitySeriesOut
    trades: list[ChartTradeOut]
    trace: list[ChartTraceEventOut]
    decisions: list[ChartTraceEventOut]
    orders: list[ChartTraceEventOut]
    fills: list[ChartTraceEventOut]
    indicators: list[ChartIndicatorOut]
    annotations: list[ChartAnnotationOut]
    folds: list[ChartFoldOut]
    forecast: ForecastSeriesOut | None
    truncated: ChartTruncationOut


class PortfolioAllocationOut(TypedDict):
    start_ts: float
    ts: float
    symbol: str
    weight: float
    leg_return: float
    contribution: float
    leg_gross_exposure: float
    leg_net_exposure: float
    weighted_gross_exposure: float
    weighted_net_exposure: float


class PortfolioCorrelationOut(TypedDict):
    asset_a: str
    asset_b: str
    metric_name: Literal["pearson_correlation"]
    metric_unit: Literal["coefficient"]
    correlation: float | None
    sample_count: int
    aligned_oos: Literal[True]
    frequency: Literal["1d"]
    oos_start: str | None
    oos_end: str | None
    association_not_causation: Literal[True]


class PortfolioExposureOut(TypedDict):
    start_ts: float
    end_ts: float
    gross_exposure: float | None
    net_exposure: float | None
    turnover: float | None
    exposure_available: bool
    turnover_available: bool
    exposure_unavailable_reason: str | None
    turnover_unavailable_reason: str | None


class PortfolioProjectionBoundOut(TypedDict):
    original: int
    returned: int
    truncated: bool
    sampling: Literal["all", "endpoint_uniform", "canonical_prefix"]


class PortfolioAnalyticsBoundsOut(TypedDict):
    timestamp_limit: int
    symbol_limit: int
    allocation_timestamps: PortfolioProjectionBoundOut
    symbols: PortfolioProjectionBoundOut


class PortfolioAnalyticsProvenanceOut(TypedDict):
    source_run_id: str
    source_command: Literal["backtest_portfolio"]
    snapshot_id: str | None
    snapshot_hash: str | None
    research_cutoff: str | None
    as_of: float | None
    timezone: Literal["UTC"]
    frequency: Literal["1d"]
    metric_namespace: Literal["alpha_validation.portfolio"]
    correlation_alignment: Literal["exact_pairwise_oos_timestamp_intersection"]
    allocation_semantics: Literal["causal_sleeve_weight_at_interval_start"]
    association_label: Literal["association, not causation"]
    artifact_contract_version: int | None
    artifact_sha256: dict[str, str]


class PortfolioAnalyticsOut(TypedDict):
    symbols: list[str]
    allocations: list[PortfolioAllocationOut]
    correlations: list[PortfolioCorrelationOut]
    exposure: list[PortfolioExposureOut]
    provenance: PortfolioAnalyticsProvenanceOut
    bounds: PortfolioAnalyticsBoundsOut


class RunMetricOut(TypedDict):
    name: str
    value: float
    unit: str
    source_artifact: Literal["manifest.json"]
    source_field: str


class RunComparisonRowOut(TypedDict):
    run_id: str
    command: str | None
    symbol: str | None
    symbols: list[str] | None
    snapshot_id: str | None
    snapshot_hash: str | None
    passed: bool | None
    metrics: list[RunMetricOut]


class RunComparisonOut(TypedDict):
    run_ids: list[str]
    same_snapshot_hash: bool
    rows: list[RunComparisonRowOut]


__all__ = [
    "ControlJobDetailOut",
    "ControlJobOut",
    "ControlJobPageOut",
    "JobCancellationOut",
    "JobReconciliationOut",
    "LegacyRunManifestOut",
    "LegacyRunSummaryOut",
    "ChartBundleOut",
    "PortfolioAnalyticsOut",
    "RunComparisonOut",
]
