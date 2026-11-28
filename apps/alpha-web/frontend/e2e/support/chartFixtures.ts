// Chart-bundle and tearsheet fixtures the e2e harness serves for the heavy and causal runs.

export const HEAVY_RUN_ID = '0123456789abcdef'
export const HEAVY_BAR_COUNT = 25_000
const HEAVY_ANNOTATION_COUNT = 200
const HEAVY_START_TS = Date.UTC(1957, 0, 1) / 1_000

export function heavyChartBundle(): unknown {
  const bars = Array.from({ length: HEAVY_BAR_COUNT }, (_, index) => {
    const baseline = 100 + index * 0.002 + Math.sin(index / 17)
    const open = baseline + Math.sin(index / 5) * 0.12
    const close = baseline + Math.cos(index / 7) * 0.12
    return {
      t: HEAVY_START_TS + index * 86_400,
      o: open,
      h: Math.max(open, close) + 0.3,
      l: Math.min(open, close) - 0.3,
      c: close,
      v: 1_000_000 + (index % 97) * 10_000,
    }
  })
  const annotations = Array.from({ length: HEAVY_ANNOTATION_COUNT }, (_, index) => {
    const barIndex = Math.floor((index * (HEAVY_BAR_COUNT - 2)) / (HEAVY_ANNOTATION_COUNT - 1))
    return {
      annotation_id: index + 1,
      decision_sequence_id: null,
      kind: index % 5 === 0 ? 'zone' : 'line',
      label: `LEVEL ${String(index + 1).padStart(3, '0')}`,
      unit: 'price',
      reason: 'deterministic performance fixture',
      anchors: [
        { anchor_index: 0, ts: bars[barIndex]!.t, value: bars[barIndex]!.c },
        { anchor_index: 1, ts: bars[barIndex + 1]!.t, value: bars[barIndex + 1]!.c },
      ],
    }
  })
  return {
    run_id: HEAVY_RUN_ID,
    trace_status: 'available',
    bars_status: 'available',
    provenance: {
      command: 'backtest_run',
      symbol: 'SPY',
      symbols: null,
      snapshot_id: 'performance-fixture',
      snapshot_hash: 'a'.repeat(64),
      timezone: 'UTC',
      price_unit: 'native_quote',
      artifact_contract_version: 3,
      as_of: bars.at(-1)!.t,
      artifact_sha256: {},
    },
    bars,
    equity: { ts: [], equity: [], drawdown: [] },
    trades: [],
    trace: [],
    decisions: [],
    orders: [],
    fills: [],
    indicators: [],
    annotations,
    folds: [],
    forecast: null,
    truncated: {
      bars: false,
      equity: false,
      trades: false,
      trace: false,
      indicators: false,
      annotations: false,
    },
  }
}

export const CAUSAL_START_TS = Date.UTC(2025, 0, 1) / 1_000
export const CAUSAL_TRADES = [
  {
    instrument_id: 'AAPL.SIM',
    side: 'BUY',
    quantity: 10,
    entry_price: 192.25,
    exit_price: 201.5,
    entry_ts: new Date((CAUSAL_START_TS + 92 * 86_400) * 1_000).toISOString(),
    exit_ts: new Date((CAUSAL_START_TS + 100 * 86_400) * 1_000).toISOString(),
    realized_pnl: 92.5,
    realized_return: 0.048114,
  },
]

function traceEvent(sequenceId: number, ts: number): Record<string, unknown> {
  return {
    sequence_id: sequenceId,
    event_type: 'decision',
    ts,
    parent_sequence_id: null,
    instrument_id: 'AAPL.SIM',
    side: 'BUY',
    quantity: 10,
    filled_quantity: null,
    price: null,
    status: null,
    signal: 1,
    decision_reason: `causal decision ${sequenceId}`,
    entry_ts: null,
    exit_ts: null,
    entry_price: null,
    exit_price: null,
    realized_pnl: null,
    realized_return: null,
  }
}

export function causalChartBundle(traceAvailable = true): unknown {
  const bars = Array.from({ length: 205 }, (_, index) => ({
    t: CAUSAL_START_TS + index * 86_400,
    o: 100 + index,
    h: 102 + index,
    l: 99 + index,
    c: 101 + index,
    v: 1_000 + index,
  }))
  const decisions = Array.from({ length: 90 }, (_, index) =>
    traceEvent(index + 1, bars[index]!.t + 23 * 60 * 60),
  )
  const trade = {
    ...traceEvent(91, bars[100]!.t),
    event_type: 'trade',
    status: 'CLOSED',
    signal: null,
    decision_reason: null,
    price: 201.5,
    entry_ts: bars[92]!.t,
    exit_ts: bars[100]!.t,
    entry_price: 192.25,
    exit_price: 201.5,
    realized_pnl: 92.5,
    realized_return: 0.048114,
  }
  const trace = traceAvailable ? [...decisions, trade] : []
  return {
    run_id: HEAVY_RUN_ID,
    trace_status: traceAvailable ? 'available' : 'trace_unavailable',
    bars_status: 'available',
    provenance: {
      command: 'backtest_run',
      symbol: 'AAPL',
      symbols: null,
      snapshot_id: 'causal-fixture',
      snapshot_hash: 'f'.repeat(64),
      timezone: 'UTC',
      price_unit: 'native_quote',
      artifact_contract_version: traceAvailable ? 3 : null,
      as_of: bars.at(-1)!.t,
      artifact_sha256: {},
    },
    bars,
    equity: { ts: [], equity: [], drawdown: [] },
    trades: traceAvailable ? [{ ...CAUSAL_TRADES[0], entry_ts: bars[92]!.t, exit_ts: bars[100]!.t }] : [],
    trace,
    decisions: traceAvailable ? decisions : [],
    orders: [],
    fills: [],
    indicators: [],
    annotations: [],
    folds: [],
    forecast: null,
    truncated: {
      bars: true,
      equity: false,
      trades: false,
      trace: traceAvailable,
      indicators: false,
      annotations: false,
    },
  }
}

export function denseCausalChartBundle(): unknown {
  const bundle = causalChartBundle() as Record<string, unknown>
  const bars = bundle.bars as Array<{ t: number }>
  const decisions = Array.from({ length: 90 }, (_, index) =>
    traceEvent(index * 2 + 1, bars[index]!.t + 23 * 60 * 60),
  )
  const fills = decisions.map((decision, index) => ({
    ...decision,
    sequence_id: index * 2 + 2,
    event_type: 'fill',
    ts: bars[index + 1]!.t,
    filled_quantity: 10,
    price: 101 + index,
    status: 'FILLED',
    signal: null,
    decision_reason: null,
  }))
  return {
    ...bundle,
    trace: decisions.flatMap((decision, index) => [decision, fills[index]]),
    decisions,
    fills,
    trades: [],
  }
}

export const EMPTY_NATIVE_TEARSHEET = {
  available: false,
  calendar_returns: [],
  yearly_returns: [],
  histogram: [],
  qq: [],
  rolling: [],
  exposure_turnover: [],
  benchmark: [],
  trade_statistics: [],
  exposure_available: false,
  turnover_available: false,
  benchmark_available: false,
  trade_statistics_available: false,
  provenance: {
    run_id: HEAVY_RUN_ID,
    metric_namespace: 'alpha_validation',
    artifact_contract_version: 3,
    artifact_sha256: {},
  },
  bounds: {
    point_limit: 2_000,
    qq: { original: 0, returned: 0, truncated: false, sampling: 'all' },
    rolling: { original: 0, returned: 0, truncated: false, sampling: 'all' },
    exposure_turnover: { original: 0, returned: 0, truncated: false, sampling: 'all' },
    benchmark: { original: 0, returned: 0, truncated: false, sampling: 'all' },
  },
}
