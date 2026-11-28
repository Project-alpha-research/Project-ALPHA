import AxeBuilder from '@axe-core/playwright'
import { expect, test, type Page, type Route } from '@playwright/test'
import { readFile } from 'node:fs/promises'
import type { components } from '../../src/api/generated'
import {
  CAUSAL_START_TS,
  CAUSAL_TRADES,
  causalChartBundle,
  denseCausalChartBundle,
  EMPTY_NATIVE_TEARSHEET,
  HEAVY_BAR_COUNT,
  HEAVY_RUN_ID,
  heavyChartBundle,
} from './chartFixtures'
import { studySeries } from './technicalFixture'

/** A CLI refusal the API relays as 400 with its message (e.g. a study longer than the window). */
class Refusal { readonly detail: string; constructor(detail: string) { this.detail = detail } }

// The market-neutral documents every profile can open (shell/documents.ts), reached from the
// View menu, the Navigator or the toolbar rather than from a fixed tab strip.
const DOCUMENTS = [
  { title: 'Chart', id: 'chart' },
  { title: 'Strategy Performance Report', id: 'report' },
  { title: 'Compare', id: 'compare' },
  { title: 'Forecast', id: 'forecast' },
  { title: 'Jobs', id: 'jobs' },
] as const

/** Open a workflow task and wait until its task tab is active. */
export async function openDocument(page: Page, title: string): Promise<void> {
  const routes: Record<string, [string, string]> = {
    'Chart': ['Data & Assets', 'Price'], 'Research': ['Research', 'Research Case'],
    'Strategy Performance Report': ['Results', 'Report'],
    'Compare': ['Results', 'Compare'], 'Forecast': ['Results', 'Forecast'], 'Machine learning': ['Results', 'ML lab'],
    'Jobs': ['Operations', 'Jobs'],
    'Funding': ['Data & Assets', 'Funding'],
    'Corporate actions': ['Data & Assets', 'Data downloads'],
  }
  const [section, task] = routes[title]
  await page.getByRole('menuitem', { name: 'View', exact: true }).click()
  await page.getByRole('menuitem', { name: `${section} › ${task}`, exact: true }).click()
  await expect(page.locator('.document-tabs').getByRole('tab', { name: task === 'Report' ? /^Report(?: ·|$)/ : task, exact: true })).toHaveAttribute('aria-selected', 'true')

}

function documentTab(page: Page, title: string) {
  const titles: Record<string, string> = { Research: 'Research Case', Chart: 'Price', Jobs: 'Jobs' }
  return page.locator('.document-tabs').getByRole('tab', { name: titles[title] ?? /^Report(?: ·|$)/, exact: true })
}

/** The Navigator leaf for a backtest, by its server display name. */
function backtestLeaf(page: Page, displayName: string) {
  return page.getByRole('tree', { name: 'Navigator' }).locator('.tree-leaf').filter({ hasText: displayName })
}

async function switchProfile(page: Page, profile: 'crypto' | 'equities'): Promise<void> {
  await page.getByLabel('Market profile').selectOption(profile)
  await expect(page.locator('html')).toHaveAttribute('data-profile', profile)
}

const EMPTY_PAGE = { items: [], limit: 50, offset: 0, has_more: false }
const PROJECT_VIEWPORTS: Record<string, { width: number; height: number }> = {
  'chromium-minimum': { width: 1280, height: 720 },
  'chromium-reference': { width: 1585, height: 991 },
  'chromium-wide': { width: 1920, height: 1080 },
}

const ML_EXCHANGE_ID = 'a'.repeat(32)
const ML_EXPERIMENT = {
  experiment_id: ML_EXCHANGE_ID,
  project_id: null,
  status: 'trained',
  universe_size: 20,
  aligned_sessions: 756,
  feature_recipe: 'alpha158',
  model: 'lightgbm',
  folds: 1,
  snapshot_hash: 'b'.repeat(64),
  config_hash: 'c'.repeat(64),
  replay_run_id: null,
  diagnostic_only: true,
  counterfactual_refit: false,
  metrics: { ic: 0.042, rank_ic: 0.051, turnover: 0.08, costed_return: 0.11 },
}
const ML_DIAGNOSTIC_TEARSHEET = {
  available: true,
  exchange_id: ML_EXCHANGE_ID,
  authority: 'qlib_diagnostic_only',
  label: 'OOS replay validated — model not recomputed under counterfactual',
  counterfactual_refit: false,
  versions: { worker: 'worker-1', pyqlib: '0.9.7', lightgbm: '4.6.0' },
  feature_recipe: {
    name: 'Alpha158-style',
    feature_count: 2,
    names: ['KMID', 'KLEN'],
    vwap_source: 'causal daily OHLCV',
  },
  label_recipe: {
    name: 'next_session_open_to_open',
    definition: 'next-session open-to-open return',
    decision: 'close_t',
    entry: 'open_t_plus_1',
  },
  score_distribution: {
    min: -0.8,
    max: 0.9,
    mean: 0.04,
    std: 0.22,
    q05: -0.34,
    q25: -0.12,
    q50: 0.03,
    q75: 0.17,
    q95: 0.41,
  },
  ic: {
    mean: 0.042,
    rank_mean: 0.051,
    by_target: [
      { target_ts: '2025-01-02T00:00:00Z', ic: 0.03, rank_ic: 0.04, sample_count: 20 },
      { target_ts: '2025-01-03T00:00:00Z', ic: 0.054, rank_ic: 0.062, sample_count: 20 },
    ],
  },
  quantile_returns: [
    { quantile: 1, mean_return: -0.002, observations: 8 },
    { quantile: 2, mean_return: -0.0005, observations: 8 },
    { quantile: 3, mean_return: 0.0002, observations: 8 },
    { quantile: 4, mean_return: 0.0011, observations: 8 },
    { quantile: 5, mean_return: 0.0024, observations: 8 },
  ],
  portfolio: {
    selection: 'long_only_top_quintile_equal_weight',
    declared_costs: { fee_bps: 1, slippage_bps: 2 },
    periods: 2,
    gross_total_return: 0.013,
    costed_total_return: 0.011,
    benchmark_total_return: 0.004,
    costed_excess_total_return: 0.007,
    mean_turnover: 0.08,
    timeline: [
      { target_ts: '2025-01-02T00:00:00Z', gross_return: 0.006, costed_return: 0.005, benchmark_return: 0.002, excess_return: 0.003, turnover: 0.07, gross_equity: 1.006, costed_equity: 1.005, benchmark_equity: 1.002 },
      { target_ts: '2025-01-03T00:00:00Z', gross_return: 0.007, costed_return: 0.006, benchmark_return: 0.002, excess_return: 0.004, turnover: 0.09, gross_equity: 1.013, costed_equity: 1.011, benchmark_equity: 1.004 },
    ],
  },
  feature_importance: [
    { feature: 'KMID', mean_gain: 0.61, mean_split_count: 31 },
    { feature: 'KLEN', mean_gain: 0.39, mean_split_count: 19 },
  ],
  feature_importance_truncated: false,
  folds: [{
    fold: 0,
    fit_count: 1,
    train_rows: 10_000,
    validation_rows: 2_000,
    test_rows: 2_000,
    best_iteration: 2,
    model_hash: 'd'.repeat(64),
    normalization: {
      method: 'train_only_median_then_zscore',
      statistics_hash: 'e'.repeat(64),
      all_missing_train_features: 0,
    },
    training_history: {
      train: { l2: [0.4, 0.3] },
      valid: { l2: [0.45, 0.34] },
    },
    boundaries: {
      train_start: '2022-01-03T00:00:00Z',
      train_end: '2023-12-29T00:00:00Z',
      validation_start: '2024-01-02T00:00:00Z',
      validation_end: '2024-06-28T00:00:00Z',
      test_start: '2024-07-01T00:00:00Z',
      test_end: '2024-12-31T00:00:00Z',
    },
  }],
  timeline_total: 2,
  timeline_offset: 0,
  timeline_limit: 500,
  timeline_has_more: false,
}

// spec §15 / ADR-0026 (R6g): a run launched under an owner research-gate override permanently
// carries this marker; the SPA relays it on the run browser, run story, and tear sheet, and the
// Operations desk lists every active override.
const RESEARCH_GATE_WATERMARK = 'EXPLORATORY / RESEARCH GATE NOT COMPLETED'
const WATERMARKED_RUN_ID = 'fade0000000000ab'

const WATERMARKED_RUN_ITEM: components['schemas']['RunListItem'] = {
  run_id: WATERMARKED_RUN_ID,
  kind: 'portfolio',
  command: 'backtest_portfolio',
  label: 'SPY, TLT',
  display_name: 'backtest_portfolio D1 — SPY, TLT · run fade0000',
  market: 'unknown',
  symbol: null,
  symbols: ['SPY', 'TLT'],
  snapshot_id: null,
  snapshot_hash: null,
  passed: null,
  verdict: null,
  evidence: null,
  research_gate_watermark: RESEARCH_GATE_WATERMARK,
  run_context_kind: 'governed_project',
  run_context_project_id: 'project-overridden',
  run_context_watermark: RESEARCH_GATE_WATERMARK,
  rule_test_labels: null,
  mtime: 1,
}

const WATERMARKED_RUN_DETAIL: components['schemas']['RunDetail'] = {
  run_id: WATERMARKED_RUN_ID,
  kind: 'portfolio',
  mtime: 1,
  display_name: 'backtest_portfolio D1 — SPY, TLT · run fade0000',
  market: 'unknown',
  manifest: {
    command: 'backtest_portfolio',
    symbols: ['SPY', 'TLT'],
    research_gate: { state: 'overridden', watermark: RESEARCH_GATE_WATERMARK },
    run_context: {
      schema_version: 1,
      kind: 'governed_project',
      project_id: 'project-overridden',
      research_gate_state: 'overridden',
      watermark: 'EXPLORATORY',
    },
  },
  research_gate_watermark: RESEARCH_GATE_WATERMARK,
  run_context_kind: 'governed_project',
  run_context_project_id: 'project-overridden',
  run_context_watermark: RESEARCH_GATE_WATERMARK,
  rule_test: null,
  has_equity: false,
  has_trades: false,
  has_tearsheet: false,
  has_forecast: false,
  has_nulls: false,
  has_trials: false,
  has_forecast_paths: false,
  has_propfirm_paths: false,
  has_origins: false,
  has_portfolio_analytics: false,
}

const CRYPTO_MANIFEST_ID = '6'.repeat(64)
const CRYPTO_OPTION_MANIFEST_ID = '7'.repeat(64)
const CRYPTO_QUARANTINED_ID = '8'.repeat(64)
const CRYPTO_SNAPSHOT_ID = '9'.repeat(64)
const CRYPTO_ASSET_MASTER_ID = 'd'.repeat(64)
const CRYPTO_COINGECKO_MANIFEST_ID = 'e'.repeat(64)
const CRYPTO_COINGECKO_DETAIL_MANIFEST_ID = '4'.repeat(64)
const CRYPTO_POOL_MANIFEST_ID = 'f'.repeat(64)
const CRYPTO_SOLANA_POOL_MANIFEST_ID = '0'.repeat(64)
const CRYPTO_COVERAGE: components['schemas']['CryptoCoverageResponse'] = {
  verification: 'metadata_only',
  items: [
    {
      manifest_id: CRYPTO_MANIFEST_ID,
      provider: 'bybit',
      venue: 'bybit',
      market_type: 'linear',
      family: 'funding',
      instrument: 'BTCUSDT',
      base_asset: 'BTC',
      quote_asset: 'USDT',
      frequency: 'funding_interval',
      units: 'dimensionless_rate',
      timestamp_convention: 'provider_event_utc',
      state: 'qualified',
      failures: [],
      warnings: [],
      observed_start: '2026-06-01T00:00:00Z',
      observed_end: '2026-08-14T16:00:00Z',
      row_count: 200,
      artifact_sha256: 'a'.repeat(64),
      method_version: 'crypto-quality-v1',
      fetched_at: '2026-08-15T00:00:00Z',
    },
    {
      manifest_id: CRYPTO_OPTION_MANIFEST_ID,
      provider: 'bybit',
      venue: 'bybit',
      market_type: 'option',
      family: 'option_quotes',
      instrument: 'BTC',
      base_asset: 'BTC',
      quote_asset: 'USDT',
      frequency: 'point_in_time_chain',
      units: 'provider_native',
      timestamp_convention: 'provider_event_utc',
      state: 'qualified',
      failures: [],
      warnings: [],
      observed_start: '2026-08-15T00:00:00Z',
      observed_end: '2026-08-15T00:00:00Z',
      row_count: 582,
      artifact_sha256: 'b'.repeat(64),
      method_version: 'crypto-quality-v1',
      fetched_at: '2026-08-15T00:00:00Z',
    },
    {
      manifest_id: CRYPTO_QUARANTINED_ID,
      provider: 'bybit',
      venue: 'bybit',
      market_type: 'option',
      family: 'option_quotes',
      instrument: 'BTC',
      base_asset: 'BTC',
      quote_asset: 'USD',
      frequency: 'point_in_time_chain',
      units: 'provider_native',
      timestamp_convention: 'provider_event_utc',
      state: 'quarantined',
      failures: ['quote_identity_mismatch'],
      warnings: [],
      observed_start: '2026-08-14T00:00:00Z',
      observed_end: '2026-08-14T00:00:00Z',
      row_count: 582,
      artifact_sha256: 'c'.repeat(64),
      method_version: 'crypto-quality-v1',
      fetched_at: null,
    },
    {
      manifest_id: CRYPTO_COINGECKO_DETAIL_MANIFEST_ID,
      provider: 'coingecko',
      venue: 'coingecko',
      market_type: 'reference',
      family: 'asset_metadata',
      instrument: 'bitcoin',
      base_asset: 'BTC',
      quote_asset: null,
      frequency: 'point_in_time_detail',
      units: 'reference_only',
      timestamp_convention: 'provider_observation_utc',
      state: 'qualified',
      failures: [],
      warnings: [],
      observed_start: '2026-08-15T00:01:00Z',
      observed_end: '2026-08-15T00:01:00Z',
      row_count: 1,
      artifact_sha256: '4'.repeat(64),
      method_version: 'crypto-quality-v1',
      fetched_at: '2026-08-15T00:01:00Z',
    },
    {
      manifest_id: CRYPTO_COINGECKO_MANIFEST_ID,
      provider: 'coingecko',
      venue: 'coingecko',
      market_type: 'reference',
      family: 'asset_metadata',
      instrument: 'all',
      base_asset: null,
      quote_asset: null,
      frequency: 'catalog_snapshot',
      units: 'metadata',
      timestamp_convention: 'fetch_knowledge_utc',
      state: 'qualified',
      failures: [],
      warnings: [],
      observed_start: '2026-08-15T00:00:00Z',
      observed_end: '2026-08-15T00:00:00Z',
      row_count: 20_000,
      artifact_sha256: 'd'.repeat(64),
      method_version: 'crypto-quality-v1',
      fetched_at: '2026-08-15T00:00:00Z',
    },
    {
      manifest_id: CRYPTO_POOL_MANIFEST_ID,
      provider: 'geckoterminal',
      venue: 'geckoterminal',
      market_type: 'dex',
      family: 'dex_pools',
      instrument: 'eth',
      base_asset: 'ETH',
      quote_asset: 'USD',
      frequency: 'catalog_snapshot',
      units: 'provider_native',
      timestamp_convention: 'fetch_knowledge_utc',
      state: 'qualified',
      failures: [],
      warnings: [],
      observed_start: '2026-08-15T00:00:00Z',
      observed_end: '2026-08-15T00:00:00Z',
      row_count: 100,
      artifact_sha256: 'e'.repeat(64),
      method_version: 'crypto-quality-v1',
      fetched_at: '2026-08-15T00:00:00Z',
    },
    {
      manifest_id: CRYPTO_SOLANA_POOL_MANIFEST_ID,
      provider: 'geckoterminal',
      venue: 'geckoterminal',
      market_type: 'dex',
      family: 'dex_pools',
      instrument: 'solana',
      base_asset: 'SOL',
      quote_asset: 'USD',
      frequency: 'catalog_snapshot',
      units: 'provider_native',
      timestamp_convention: 'fetch_knowledge_utc',
      state: 'qualified',
      failures: [],
      warnings: [],
      observed_start: '2026-08-15T00:00:00Z',
      observed_end: '2026-08-15T00:00:00Z',
      row_count: 100,
      artifact_sha256: 'f'.repeat(64),
      method_version: 'crypto-quality-v1',
      fetched_at: '2026-08-15T00:00:00Z',
    },
  ],
  count: 6,
  canonical_next_action: 'Select qualified families for a snapshot.',
  automatic_fallback: false,
  execution_authority: false,
}

// R6h (spec §15): an `open` research-required gate disables strategy-creation and
// optimisation affordances on the Develop desk with the reason and a link to the case;
// grandfathered (`not_required`) projects and non-research contexts stay fully enabled.
interface MockOptions {
  initialSymbol?: string | null
  /** Persisted `alpha.settings` written before the app boots (e.g. `{ chartStyle: 'default' }`). */
  settings?: Record<string, unknown>
  chartBundle?: unknown
  trades?: unknown[]
  mlDiagnostics?: boolean
  jobs?: unknown[]
  researchGateOverride?: boolean
  /** Opt-in so the screenshot baselines keep an empty, deterministic Library rail. */
  runs?: unknown[]
  capturedOwnerAction?: (body: Record<string, unknown>) => void
  /** Extra GET fixtures keyed by pathname, served before the built-in table. */
  extraGet?: Record<string, unknown>
  /** Sees every POST (pathname, body); a non-undefined return is served as the 200 JSON reply. */
  capturedPost?: (pathname: string, body: Record<string, unknown>) => unknown
  /** Opt-in: LIBRARY_RUN carries one drawable figure (catalogue, metadata and an SVG image). */
  figureCatalogue?: boolean
  /** Opt-in daily bars per symbol for the candles projection (Market Watch, Chart). */
  candles?: Record<string, components['schemas']['Candle'][]>
  /** Saved rule sets served by GET /api/rules. */
  rules?: components['schemas']['RuleSummary'][]
  /** Receives the query string of every `/api/overlays/{symbol}` request the chart makes. */
  capturedOverlays?: (query: string) => void
  /** Opt-in public tickers keyed `SYMBOL@exchange`; a missing key answers 422 like the CLI. */
  tickers?: Record<string, { last: number; ts: string }>
  /** Opt-in: the bulk-data volume is not mounted. */
  storageUnmounted?: boolean
}

const FIGURE_ITEM = {
  figure_id: 'equity_curve',
  section: 'performance',
  title: 'Equity curve',
  summary: 'Equity over the backtest period.',
  available: true,
  unavailable_reason: null,
  panel_count: 1,
} satisfies components['schemas']['FigureCatalogueItem']

const FIGURE_META = {
  figure_id: 'equity_curve',
  title: 'Equity curve',
  subtitle: 'SPY · ts_momentum',
  question: 'Did the equity grow, and how smoothly?',
  plain_language_answer: 'Equity rose steadily.',
  uncertainty: 'One path; no confidence band.',
  caveat: 'In-sample only.',
  caption: 'Equity curve of the run.',
  alt_text: 'Line chart of equity rising from 100,000 to 112,000.',
  x_label: 'Date',
  panels: [{ panel_id: 'equity', y_label: 'Equity', y_unit: 'USD', legend: ['equity'], note: null }],
  source_artifacts: ['equity_curve.parquet'],
  truncation_note: null,
  format: 'svg',
  width_in: 11,
  height_in: 5,
  renderer_version: 1,
  cache_key: 'figkey',
  etag: 'etag-1',
  image_url: '/api/runs/run-1/figures/equity_curve/image?fmt=svg&variant=plain&key=figkey',
  variant: 'plain',
  explanation: [
    'The horizontal axis is the date.',
    'The line is equity after costs.',
    'Look at how deep the dips go.',
    'The chart cannot tell you what comes next.',
  ],
} satisfies components['schemas']['FigureMetadata']

const FIGURE_SVG =
  '<svg xmlns="http://www.w3.org/2000/svg" width="440" height="200" viewBox="0 0 440 200">'
  + '<rect width="440" height="200" fill="#ffffff"/><polyline points="10,180 200,120 430,20" fill="none" stroke="#316ac5" stroke-width="3"/></svg>'

const LIBRARY_RUN = {
  run_id: 'abcdef0123456789',
  kind: 'runs',
  command: 'backtest run',
  display_name: 'ma_crossover D1 — SPY · 2020-01-01 → 2020-12-31 · run abcdef01',
  market: 'unknown',
  label: 'SPY · ts_momentum',
  symbol: 'SPY',
  strategy: 'ts_momentum',
  mtime: 1_700_000_000,
  passed: null,
  verdict: null,
  evidence: null,
}

export const HEAVY_LIBRARY_RUN: components['schemas']['RunListItem'] = {
  run_id: HEAVY_RUN_ID,
  kind: 'runs',
  command: 'backtest_run',
  label: 'AAPL · causal trace fixture',
  display_name: 'ma_crossover D1 — AAPL · causal-fixture · run ' + HEAVY_RUN_ID.slice(0, 8),
  market: 'unknown',
  symbol: 'AAPL',
  symbols: null,
  snapshot_id: 'causal-fixture',
  snapshot_hash: 'f'.repeat(64),
  passed: null,
  verdict: null,
  evidence: null,
  research_gate_watermark: null,
  run_context_kind: 'standalone_sandbox',
  run_context_project_id: null,
  run_context_watermark: 'STANDALONE_UNQUALIFIED',
  rule_test_labels: null,
  mtime: 1_700_000_100,
}

export async function openHeavyPrice(page: Page): Promise<void> {
  await openTask(page, 'Results', 'Run library')
  await backtestLeaf(page, 'causal-fixture').click()
  await openDocument(page, 'Chart')
}

function responseFor(route: Route, options: MockOptions): unknown {
  const url = new URL(route.request().url())
  if (options.extraGet && route.request().method() === 'GET' && url.pathname in options.extraGet) {
    return options.extraGet[url.pathname]
  }
  if (options.capturedPost && route.request().method() === 'POST') {
    const served = options.capturedPost(url.pathname, (route.request().postDataJSON() ?? {}) as Record<string, unknown>)
    if (served !== undefined) return served
  }
  if (url.pathname === '/api/owner-auth/actions/challenge') {
    options.capturedOwnerAction?.(route.request().postDataJSON() as Record<string, unknown>)
    return {
      challenge_id: '00000000-0000-4000-8000-000000000001',
      expires_at: '2026-08-13T02:01:00Z',
      confirmation_token: 'a'.repeat(64),
      binding: route.request().postDataJSON(),
      public_key: {
        challenge: 'AQID',
        rpId: 'localhost',
        timeout: 60_000,
        allowCredentials: [],
        userVerification: 'required',
      },
    }
  }
  if (url.pathname === '/api/owner-auth/actions/perform') {
    return { authorization: { receipt_id: 'receipt-1' }, result: { status: 'recorded' } }
  }
  if (url.pathname === '/api/crypto-data/catalog') {
    return {
      families: [
        { family: 'asset_metadata', provider: 'coingecko', role: 'primary_acquisition' },
        { family: 'funding', provider: 'bybit', role: 'primary_acquisition' },
        { family: 'instrument_catalog', provider: 'bybit', role: 'primary_acquisition' },
        { family: 'derivative_bars', provider: 'bybit', role: 'primary_acquisition' },
        { family: 'derivative_trades', provider: 'bybit', role: 'primary_acquisition' },
        { family: 'derivative_book_snapshots', provider: 'bybit', role: 'primary_acquisition' },
        { family: 'option_quotes', provider: 'bybit', role: 'primary_acquisition' },
        { family: 'comparison_bars', provider: 'ccxt:coinbase', role: 'diagnostic_comparison' },
      ],
      automatic_fallback: false,
      execution_authority: false,
      next_action: 'Check storage before estimating or acquiring data.',
    } satisfies components['schemas']['CryptoCatalogResponse']
  }
  if (url.pathname === '/api/crypto-data/capabilities') {
    return {
      items: [
        {
          schema_version: 1,
          provider: 'bybit',
          family: 'funding',
          authentication: 'none',
          earliest: '2026-06-01T00:00:00+00:00',
          latest: '2026-08-14T00:00:00+00:00',
          frequencies: ['funding_interval'],
          limits: ['bybit_page_200'],
          verification_state: 'receipt_verified',
          qualification_state: 'qualified',
        },
        {
          schema_version: 1,
          provider: 'bybit',
          family: 'option_quotes',
          authentication: 'none',
          earliest: '2026-08-14T00:00:00+00:00',
          latest: '2026-08-14T00:00:00+00:00',
          frequencies: ['point_in_time_chain'],
          limits: ['hourly_all_supported_underlyings'],
          verification_state: 'receipt_verified',
          qualification_state: 'qualified',
        },
      ],
      count: 2,
      receipt_verified_count: 2,
      qualified_count: 2,
      provider_probe_performed: false,
      automatic_fallback: false,
      execution_authority: false,
      canonical_next_action: 'Inspect qualified coverage and freeze an exact snapshot.',
    } satisfies components['schemas']['CryptoCapabilitiesResponse']
  }
  if (url.pathname === '/api/crypto-data/asset-masters' && route.request().method() === 'GET') {
    return {
      items: [
        {
          asset_master_version: 'reviewed-native-v1',
          identity_count: 2,
          contract_identity_count: 0,
          builtin: true,
          state: 'verified',
        },
        {
          asset_master_version: CRYPTO_ASSET_MASTER_ID,
          identity_count: 3,
          contract_identity_count: 1,
          builtin: false,
          state: 'verified',
        },
      ],
      count: 2,
      ticker_join_allowed: false,
      next_action: 'Build an exact contract identity map.',
    } satisfies components['schemas']['CryptoAssetMasterListResponse']
  }
  if (url.pathname === '/api/crypto-data/asset-masters' && route.request().method() === 'POST') {
    expect(route.request().postDataJSON()).toEqual({
      coingecko_manifest_id: CRYPTO_COINGECKO_MANIFEST_ID,
      geckoterminal_manifest_ids: [
        CRYPTO_POOL_MANIFEST_ID,
        CRYPTO_SOLANA_POOL_MANIFEST_ID,
      ],
    })
    return {
      asset_master_version: CRYPTO_ASSET_MASTER_ID,
      identity_count: 3,
      contract_identity_count: 1,
      source_manifest_ids: [
        CRYPTO_COINGECKO_MANIFEST_ID,
        CRYPTO_POOL_MANIFEST_ID,
        CRYPTO_SOLANA_POOL_MANIFEST_ID,
      ],
      ticker_join_allowed: false,
      state: 'frozen',
      next_action: 'Use this exact asset-master version when freezing a snapshot.',
    } satisfies components['schemas']['CryptoAssetMasterResponse']
  }
  if (url.pathname === `/api/crypto-data/asset-masters/${CRYPTO_ASSET_MASTER_ID}/verify`) {
    return {
      asset_master_version: CRYPTO_ASSET_MASTER_ID,
      identity_count: 3,
      contract_identity_count: 1,
      source_manifest_ids: null,
      ticker_join_allowed: false,
      state: 'verified',
      next_action: 'Freeze a snapshot bound to this exact asset-master version.',
    } satisfies components['schemas']['CryptoAssetMasterResponse']
  }
  if (url.pathname === '/api/crypto-data/storage') {
    if (options.storageUnmounted) {
      return {
        verification: 'metadata_only',
        state: 'blocked',
        blocker: 'bulk_volume_not_mounted',
        bulk_root_label: 'crypto-data',
        manifest_count: 0,
        next_action: 'Reconnect the bulk-data volume.',
        free_bytes: null,
        total_bytes: null,
        reserve_fraction: 0.15,
        minimum_free_bytes: 100_000_000_000,
        cache_bytes: 0,
      } satisfies components['schemas']['CryptoStorageResponse']
    }
    return {
      verification: 'metadata_only',
      state: 'ready',
      blocker: null,
      bulk_root_label: 'crypto-data',
      manifest_count: 6,
      next_action: 'Estimate one bounded dataset acquisition.',
      free_bytes: 1_800_000_000_000,
      total_bytes: 2_000_000_000_000,
      reserve_fraction: 0.15,
      minimum_free_bytes: 100_000_000_000,
      cache_bytes: 25_000_000,
    } satisfies components['schemas']['CryptoStorageResponse']
  }
  if (url.pathname === '/api/crypto-data/storage/inventory') {
    return {
      manifest_count: 6, snapshot_count: 1,
      counts_by_kind: { raw: 3, normalized: 3 },
      bytes_by_kind: { raw: 10_000_000, normalized: 20_000_000 },
      cache_bytes: 25_000_000, staging_count: 0,
      private_paths_exposed: false,
      next_action: 'Run storage-verify before relying on frozen snapshots.',
    } satisfies components['schemas']['CryptoStorageInventoryResponse']
  }
  if (url.pathname === '/api/crypto-data/storage/verify') {
    return {
      state: 'verified', manifest_count: 6, snapshot_count: 1,
      research_eligible_snapshot_count: 1, asset_master_count: 1, cache_bytes: 25_000_000,
      private_paths_exposed: false, next_action: 'Continue.',
    } satisfies components['schemas']['CryptoStorageVerifyResponse']
  }
  if (url.pathname === '/api/crypto-data/storage/cache/clean') {
    return {
      state: 'cleaned', removed_bytes: 25_000_000,
      immutable_artifacts_removed: 0, private_paths_exposed: false,
      next_action: 'Run storage-inventory to confirm current capacity.',
    } satisfies components['schemas']['CryptoCacheCleanResponse']
  }
  if (url.pathname === '/api/crypto-data/coverage') return CRYPTO_COVERAGE
  if (url.pathname === '/api/crypto-data/features' && route.request().method() === 'GET') {
    return {
      items: [], count: 0, research_authority: false, execution_authority: false,
      next_action: 'Create only a feature supported by exact qualified inputs.',
    } satisfies components['schemas']['CryptoFeatureListResponse']
  }
  if (url.pathname === '/api/crypto-data/features' && route.request().method() === 'POST') {
    return {
      manifest_id: '0'.repeat(64), feature_id: 'a'.repeat(64), feature_name: 'funding',
      method_version: 'crypto-features-v1', available_at: '2026-08-15T00:00:00Z',
      row_count: 200, artifact_sha256: 'b'.repeat(64), input_count: 1, state: 'frozen',
      research_authority: false, execution_authority: false,
      next_action: 'Bind this feature beside its exact frozen crypto snapshot.',
    } satisfies components['schemas']['CryptoFeatureResponse']
  }
  if (url.pathname === '/api/crypto-data/estimate') {
    return {
      family: 'option_quotes',
      provider: 'bybit',
      instruments: 1,
      days: 30,
      frequency: '1h',
      estimated_rows: 720,
      estimated_bytes: 345_600,
      bounded: true,
      estimate_only: true,
      next_action: 'Verify storage, then start one bounded acquisition.',
    } satisfies components['schemas']['CryptoEstimateResponse']
  }
  if (url.pathname === '/api/crypto-data/acquisitions') {
    return { job_id: 'crypto-job-1', status: 'running', session_id: null }
  }
  if (url.pathname === '/api/crypto-data/snapshots') {
    return {
      snapshot_id: CRYPTO_SNAPSHOT_ID,
      member_count: 1,
      families: ['option_quotes'],
      providers: ['bybit'],
      asset_master_version: CRYPTO_ASSET_MASTER_ID,
      state: 'frozen',
      next_action: 'Verify the snapshot for the exact research purpose.',
      execution_authority: false,
    } satisfies components['schemas']['CryptoSnapshotCreateResponse']
  }
  if (url.pathname === `/api/crypto-data/snapshots/${CRYPTO_SNAPSHOT_ID}/verify`) {
    return {
      snapshot_id: CRYPTO_SNAPSHOT_ID,
      eligible: true,
      purpose: 'research',
      qualified_families: ['option_quotes'],
      supplemental_families: [],
      blockers: [],
      next_action: 'Bind this snapshot to the exact research proposal.',
      execution_authority: false,
    } satisfies components['schemas']['CryptoSnapshotVerifyResponse']
  }
  if (url.pathname === `/api/crypto-data/quality/${CRYPTO_OPTION_MANIFEST_ID}`) {
    return {
      manifest_id: CRYPTO_OPTION_MANIFEST_ID,
      dataset: {
        provider: 'bybit', venue: 'bybit', market_type: 'option', family: 'option_quotes',
        instrument: 'BTC', base_asset: 'BTC', quote_asset: 'USDT',
        frequency: 'point_in_time_chain', units: 'provider_native',
        timestamp_convention: 'provider_event_utc',
      },
      quality: {
        schema_version: 1, dataset_sha256: 'b'.repeat(64),
        method_version: 'crypto-quality-v1', state: 'qualified', failures: [], warnings: [],
        observed_start: '2026-08-15T00:00:00Z', observed_end: '2026-08-15T00:00:00Z',
        row_count: 582, correction_lineage: [],
      },
      next_action: 'Select this dataset for a frozen snapshot.',
    } satisfies components['schemas']['CryptoQualityResponse']
  }
  if (options.mlDiagnostics && url.pathname === '/api/ml/experiments') {
    return { items: [ML_EXPERIMENT], limit: 50, offset: 0, has_more: false }
  }
  if (
    options.mlDiagnostics &&
    url.pathname === `/api/ml/exchanges/${ML_EXCHANGE_ID}/tear-sheet`
  ) {
    return ML_DIAGNOSTIC_TEARSHEET
  }
  if (/^\/api\/runs\/[a-f0-9]{16}\/equity$/.test(url.pathname)) return { ts: [], equity: [], drawdown: [] }
  if (/^\/api\/runs\/[a-f0-9]{16}\/series$/.test(url.pathname)) {
    const run_id = url.pathname.split('/')[3]
    return {
      run_id, ts: [], equity: [], drawdown: [], benchmark: null, exposure: null, trades: [],
      bands: { tradable: null, scored: null, folds: [] }, price: null,
      bounds: { points: { original: 0, returned: 0, truncated: false, sampling: 'all' }, trades: { original: 0, returned: 0, truncated: false, cap: 2000 } },
      provenance: { artifact_sha256: {} },
    }
  }
  if (options.chartBundle && url.pathname === `/api/runs/${HEAVY_RUN_ID}/chart-bundle`) {
    return options.chartBundle
  }
  if (options.chartBundle && url.pathname === `/api/runs/${HEAVY_RUN_ID}/figures`) {
    return { run_id: HEAVY_RUN_ID, kind: 'runs', figures: [] }
  }
  if (options.chartBundle && url.pathname === `/api/runs/${HEAVY_RUN_ID}`) {
    return {
      run_id: HEAVY_RUN_ID,
      kind: 'runs',
      mtime: 0,
      manifest: { command: 'backtest_run', symbol: 'SPY', schema_version: 3 },
      has_equity: false,
      has_trades: Boolean(options.trades?.length),
      has_tearsheet: false,
      has_forecast: false,
      has_nulls: false,
      has_trials: false,
      has_forecast_paths: false,
      has_propfirm_paths: false,
      has_origins: false,
      research_gate_watermark: null,
    }
  }
  if (options.chartBundle && url.pathname === `/api/runs/${HEAVY_RUN_ID}/native-tearsheet`) {
    return EMPTY_NATIVE_TEARSHEET
  }
  if (options.chartBundle && url.pathname === `/api/runs/${HEAVY_RUN_ID}/trades`) {
    return options.trades ?? []
  }
  if (options.researchGateOverride && url.pathname === `/api/runs/${WATERMARKED_RUN_ID}`) {
    return WATERMARKED_RUN_DETAIL
  }
  if (
    options.researchGateOverride
    && url.pathname === `/api/runs/${WATERMARKED_RUN_ID}/figures`
  ) {
    return { run_id: WATERMARKED_RUN_ID, kind: 'portfolio', figures: [] }
  }
  if (
    options.researchGateOverride
    && url.pathname === `/api/runs/${WATERMARKED_RUN_ID}/native-tearsheet`
  ) {
    return EMPTY_NATIVE_TEARSHEET
  }
  if (options.researchGateOverride && url.pathname === '/api/risk/scenario') {
    return {
      run_id: WATERMARKED_RUN_ID,
      confidence: 0.95,
      scenarios: [],
      provenance: {
        source_run_id: WATERMARKED_RUN_ID,
        source_command: 'backtest_portfolio',
        source_artifact: 'equity_curve.parquet',
        source_artifact_sha256: 'f'.repeat(64),
        snapshot_id: null,
        snapshot_hash: null,
        research_cutoff: null,
        as_of: null,
        timezone: 'UTC',
        derived_projection: true,
      },
    }
  }
  if (options.researchGateOverride && url.pathname === '/api/runs') {
    return { items: [WATERMARKED_RUN_ITEM], total: 1 }
  }
  if (url.pathname === '/api/runs') {
    const items = options.runs ?? []
    return { items, total: items.length }
  }
  if (url.pathname === `/api/runs/${LIBRARY_RUN.run_id}`) {
    return {
      run_id: LIBRARY_RUN.run_id,
      kind: 'runs',
      mtime: LIBRARY_RUN.mtime,
      display_name: LIBRARY_RUN.display_name,
      market: LIBRARY_RUN.market,
      manifest: { command: 'backtest_run', symbol: 'SPY', schema_version: 3 },
      has_equity: false,
      has_trades: false,
      has_tearsheet: false,
      has_forecast: false,
      has_nulls: false,
      has_trials: false,
      has_forecast_paths: false,
      has_propfirm_paths: false,
      has_origins: false,
    }
  }
  if (url.pathname === `/api/runs/${LIBRARY_RUN.run_id}/figures`) {
    return {
      run_id: LIBRARY_RUN.run_id,
      kind: 'runs',
      renderer_version: 1,
      items: options.figureCatalogue ? [FIGURE_ITEM] : [],
    }
  }
  if (url.pathname === `/api/runs/${LIBRARY_RUN.run_id}/figures/${FIGURE_ITEM.figure_id}`) {
    const variant = url.searchParams.get('variant') === 'annotated' ? 'annotated' : 'plain'
    return { ...FIGURE_META, variant }
  }
  if (url.pathname === '/api/chart-datasets') return { datasets: [], authority: 'none', state: 'unavailable' }
  if (url.pathname === '/api/symbols') return { symbols: Object.keys(options.candles ?? {}) }
  if (url.pathname === '/api/data/ticker') {
    const symbol = url.searchParams.get('symbol') ?? ''
    const exchange = url.searchParams.get('exchange') ?? ''
    const quote = options.tickers?.[`${symbol}@${exchange}`]
    if (!quote) return undefined
    return { symbol, exchange, last: quote.last, ts: quote.ts }
  }
  if (url.pathname.startsWith('/api/candles/')) {
    const symbol = decodeURIComponent(url.pathname.slice('/api/candles/'.length))
    const bars = options.candles?.[symbol]
    if (!bars) return undefined
    return {
      symbol,
      snapshot_id: null,
      bars,
            provenance: {
        symbol,
        source: 'ccxt:binance',
        timeframe: '1D',
        snapshot_id: null,
        receipt_id: null,
        knowledge_cutoff: null,
        quality_status: 'qualified',
      },
    }
  }
  if (url.pathname.startsWith('/api/overlays/')) {
    // A deterministic stand-in for `alpha chart overlays`: one line per requested indicator with
    // the first bar as warm-up, one confirmed swing low when swings are asked for.
    const symbol = decodeURIComponent(url.pathname.slice('/api/overlays/'.length))
    const bars = options.candles?.[symbol]
    if (!bars) return undefined
    options.capturedOverlays?.(url.search)
    const t = bars.map((row) => row.t)
    const indicators = []
    for (const id of url.searchParams.getAll('indicator')) {
      const result = studySeries(id, bars)
      if ('refusal' in result) return new Refusal(result.refusal)
      indicators.push(...result.series)
    }
    const annotations = url.searchParams.getAll('pattern').includes('swings')
      ? [
          {
            annotation_id: 1,
            decision_sequence_id: null,
            kind: 'marker',
            label: 'Swing low',
            unit: 'price',
            reason: 'fractal L=5; knowable from bar 1',
            anchors: [{ anchor_index: 0, ts: t[0], value: bars[0].l }],
          },
        ]
      : []
    return {
      symbol,
      snapshot_id: null,
      authority: 'none',
      provenance: {
        source: 'ccxt:binance',
        venue: 'binance',
        timeframe: '1D',
        snapshot_id: null,
        provenance_sha256: null,
        receipt_id: null,
        knowledge_cutoff: null,
        quality_status: 'qualified',
      },
      t,
      indicators,
      annotations,
    }
  }
  if (url.pathname === '/api/rules' && route.request().method() === 'GET') {
    return { rules: options.rules ?? [], authority: 'none' }
  }
  if (url.pathname === '/api/strategies' || url.pathname === '/api/commands') return []
  if (url.pathname === '/api/providers') return []
  if (url.pathname === '/api/recent-runs') return { total: 0, items: [] }
  if (url.pathname === '/api/ideas') return { cards: [], total: 0, truncated: false }
  if (url.pathname === '/api/market/overview') return { store: '1D', available_stores: ['1D'], bar_unit: 'day', window: 90, limit: 15, assets_in_store: 0, assets_scanned: 0, scan_cap: 200, bars_cap: 400, eligible_assets: 0, data_to: null, assets: [], too_few_bars: [], unreadable: [], generated_at: '2026-11-19T10:00:00+00:00' }
  if (url.pathname === '/api/follow/today') return { as_of: '2026-11-20T01:00:00+00:00', paper: true, followed: 0, behind: 0, markets: [], groups: [], rows: [], notice: 'Paper only. Forward use; not research. Not advice.' }
  if (url.pathname === '/api/jobs') return options.jobs ?? []
  if (url.pathname === '/api/ml/experiments') return EMPTY_PAGE
  if (url.pathname === '/api/ml/experiments/preflight') {
    return {
      schema_version: 1,
      experiment_id: null,
      snapshot_id: null,
      universe_count: 0,
      aligned_sessions: 0,
      active_job_id: null,
      ready: false,
      checks: [
        {
          check_id: 'experiment',
          state: 'blocked',
          message: 'No current immutable experiment is selected.',
          recovery_action: 'Create or select an experiment in Development Center.',
        },
      ],
    }
  }
  if (url.pathname === '/api/ml/capabilities') {
    return { schema_version: 1, qlib_version: '0.9.7', backends: [
      { name: 'lightgbm', status: 'available', reason: null, versions: { pyqlib: '0.9.7' } },
      { name: 'linear', status: 'available', reason: null, versions: { pyqlib: '0.9.7' } },
      { name: 'double_ensemble', status: 'available', reason: null, versions: { pyqlib: '0.9.7' } },
      { name: 'catboost', status: 'missing_dependency', reason: 'catboost is not installed', versions: {} },
      { name: 'xgboost', status: 'incompatible_dependency', reason: 'unsupported xgboost version', versions: {} },
    ] }
  }
  if (url.pathname === '/api/ml/status') {
    return {
      available: true,
      worker_ready: true,
      active_job_id: null,
      concurrency_limit: 1,
      min_symbols: 20,
      min_aligned_sessions: 756,
      isolation: 'separate locked worker',
      message: null,
    }
  }
  throw new Error(`unmocked API request: ${route.request().method()} ${url.pathname}`)
}

export async function preparePage(page: Page, options: MockOptions = {}): Promise<void> {
  await page.addInitScript(([initialSymbol, settings]: [string | null, Record<string, unknown> | null]) => {
    localStorage.clear()
    localStorage.setItem('alpha.workflow.context', JSON.stringify({ symbol: initialSymbol }))
    // The fixtures are crypto pairs: start on the Crypto market unless a test chooses another.
    localStorage.setItem('alpha.settings', JSON.stringify({ profile: 'crypto', ...(settings ?? {}), profileChosen: true }))

    class DeterministicEventSource extends EventTarget {
      static readonly CONNECTING = 0
      static readonly OPEN = 1
      static readonly CLOSED = 2
      readonly CONNECTING = 0
      readonly OPEN = 1
      readonly CLOSED = 2
      readonly url: string
      readonly withCredentials = false
      readyState = DeterministicEventSource.OPEN
      onopen: ((event: Event) => void) | null = null
      onmessage: ((event: MessageEvent) => void) | null = null
      onerror: ((event: Event) => void) | null = null

      constructor(url: string | URL) {
        super()
        this.url = String(url)
        // Tests push server events through this handle (`window.__alphaStream`).
        ;(window as unknown as { __alphaStream: EventTarget }).__alphaStream = this
        queueMicrotask(() => {
          this.dispatchEvent(new MessageEvent('snapshot', { data: '{"jobs_running":0}' }))
        })
      }

      close(): void {
        this.readyState = DeterministicEventSource.CLOSED
      }
    }

    Object.defineProperty(window, 'EventSource', {
      configurable: true,
      value: DeterministicEventSource,
    })

    class DeterministicAssertionResponse {
      readonly authenticatorData = new Uint8Array([1, 2, 3]).buffer
      readonly clientDataJSON = new Uint8Array([4, 5, 6]).buffer
      readonly signature = new Uint8Array([7, 8, 9]).buffer
      readonly userHandle = null
    }

    class DeterministicPublicKeyCredential {
      readonly id = 'test-owner-credential'
      readonly type = 'public-key'
      readonly rawId = new Uint8Array([10, 11, 12]).buffer
      readonly authenticatorAttachment = 'platform'
      readonly response = new DeterministicAssertionResponse()
      getClientExtensionResults(): AuthenticationExtensionsClientOutputs {
        return {}
      }
    }

    Object.defineProperty(window, 'AuthenticatorAssertionResponse', {
      configurable: true,
      value: DeterministicAssertionResponse,
    })
    Object.defineProperty(window, 'PublicKeyCredential', {
      configurable: true,
      value: DeterministicPublicKeyCredential,
    })
    Object.defineProperty(navigator, 'credentials', {
      configurable: true,
      value: {
        get: async () => new DeterministicPublicKeyCredential(),
      },
    })
  }, [options.initialSymbol === undefined ? 'XRP/USDT' : options.initialSymbol, options.settings ?? null] as [string | null, Record<string, unknown> | null])

  await page.route('**/*', async (route) => {
    const url = new URL(route.request().url())
    if (!['127.0.0.1', 'localhost'].includes(url.hostname)) {
      await route.abort('blockedbyclient')
      return
    }
    await route.continue()
  })
  await page.route('**/api/**', async (route) => {
    const url = new URL(route.request().url())
    if (url.pathname.endsWith(`/figures/${FIGURE_ITEM.figure_id}/image`)) {
      await route.fulfill({
        status: 200,
        contentType: url.searchParams.get('fmt') === 'png' ? 'image/png' : 'image/svg+xml',
        body: FIGURE_SVG,
      })
      return
    }
    const body = responseFor(route, options)
    if (body instanceof Refusal) {
      await route.fulfill({ status: 400, contentType: 'application/json', body: JSON.stringify({ schema_version: 1, code: 'bad_request', message: `Invalid value: ${body.detail}`, recovery_action: 'Review the request and try again.', field_errors: [], request_id: 'test' }) })
      return
    }
    await route.fulfill({
      status: body === undefined ? 404 : 200,
      contentType: 'application/json',
      body: JSON.stringify(body === undefined ? { detail: `No test fixture for ${url.pathname}` } : body),
    })
  })

  await page.goto('/#page=overview')
  await expect(page.getByRole('region', { name: 'Recent tests', exact: true })).toBeVisible()
}

async function expectReleaseAccessibility(page: Page): Promise<void> {
  const results = await new AxeBuilder({ page })
    .withTags(['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa', 'wcag22a', 'wcag22aa'])
    .analyze()
  const blocking = results.violations.filter(
    (violation) => violation.impact === 'serious' || violation.impact === 'critical',
  )
  expect(blocking, JSON.stringify(blocking, null, 2)).toEqual([])
}

export function registerWorkstationTests(): void {
for (const item of DOCUMENTS) {
  test(`${item.title} document renders and clears the accessibility release gate`, async ({
    page,
  }) => {
    await preparePage(page, { candles: { 'XRP/USDT': Array.from({ length: 60 }, (_, index) => ({ t: 1700000000 + index * 86400, o: 100 + index, h: 102 + index, l: 99 + index, c: 101 + index, v: 1000 })) } })
    await openDocument(page, item.title)
    await expect(page.getByText(/panel crashed/i)).toHaveCount(0)
    await expect(page.getByText(/SyntaxError|Unexpected end of JSON/i)).toHaveCount(0)
    if (item.id === 'chart') await expect(page.locator('.count')).toHaveText('60 bars')

    const expectedViewport = PROJECT_VIEWPORTS[test.info().project.name]
    expect(expectedViewport).toBeDefined()
    const viewport = page.viewportSize()
    expect(viewport).toEqual(expectedViewport)
    const shellBounds = await page.locator('.shell').boundingBox()
    expect(shellBounds?.width).toBe(expectedViewport.width)
    expect(shellBounds?.height).toBe(expectedViewport.height)
    // The page itself must never scroll sideways; wide content scrolls inside its own pane.
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(
      expectedViewport.width,
    )

    await expectReleaseAccessibility(page)
    if (
      test.info().project.name === 'chromium-reference' ||
      test.info().project.name === 'chromium-wide'
    ) {
      await page.evaluate(() => document.fonts.ready)
      try {
        await expect(page.locator('.shell')).toHaveScreenshot(`${item.id}-document.png`, {
          animations: 'disabled',
          caret: 'hide',
          maxDiffPixelRatio: 0.02,
        })
      } catch (error) {
        const layout = await page.evaluate(() => {
          const bounds = (element: Element) => {
            const rect = element.getBoundingClientRect()
            const style = getComputedStyle(element)
            return {
              tag: element.tagName,
              className: typeof element.className === 'string' ? element.className : '',
              left: rect.left,
              top: rect.top,
              width: rect.width,
              height: rect.height,
              clientWidth: (element as HTMLElement).clientWidth,
              clientHeight: (element as HTMLElement).clientHeight,
              cssWidth: style.width,
              cssHeight: style.height,
              overflow: `${style.overflowX}/${style.overflowY}`,
            }
          }
          return {
            viewport: { width: innerWidth, height: innerHeight, devicePixelRatio },
            shell: document.querySelector('.shell') && bounds(document.querySelector('.shell')!),
            priceChartWrap: [...document.querySelectorAll('.price-chart-canvas-wrap')].map(bounds),
            technicalHosts: [...document.querySelectorAll('.technical-host')].map(bounds),
            bokehRoots: [...document.querySelectorAll('.bk-root')].map(bounds),
            canvases: [...document.querySelectorAll('.technical-host canvas')].map(canvas => ({
              ...bounds(canvas),
              bitmapWidth: (canvas as HTMLCanvasElement).width,
              bitmapHeight: (canvas as HTMLCanvasElement).height,
            })),
          }
        })
        throw new Error(`${error instanceof Error ? error.message : String(error)}\nChart screenshot layout: ${JSON.stringify(layout)}`)
      }
    }
  })
}

test('classic menus and document tabs are keyboard operable', async ({ page }) => {
  await preparePage(page)
  const view = page.getByRole('menuitem', { name: 'View', exact: true })
  await view.focus(); await page.keyboard.press('ArrowDown')
  await page.getByRole('menuitem', { name: 'Data & Assets › Price', exact: true }).focus()
  await page.keyboard.press('Enter')
  const chart = page.getByRole('tab', { name: 'Price', exact: true })
  await expect(chart).toHaveAttribute('aria-selected', 'true')
  await page.keyboard.press('F1')
  await expect(page.getByPlaceholder('Open a document, a run, or a symbol…')).toBeVisible()
  await page.keyboard.press('Escape')
  await expect(page.getByPlaceholder('Open a document, a run, or a symbol…')).toHaveCount(0)
})

test('the Navigator lists backtests by display name and opens a report document', async ({ page }) => {
  await preparePage(page, { runs: [LIBRARY_RUN] })
  await openTask(page, 'Results', 'Run library')
  const navigator = page.getByRole('tree', { name: 'Navigator' })
  await expect(navigator).toBeVisible()
  await openTask(page, 'Results', 'Run library')
  const leaf = backtestLeaf(page, LIBRARY_RUN.display_name)
  await expect(leaf.locator('.tree-leaf-label')).toHaveText(LIBRARY_RUN.display_name)
  await expect(leaf.locator('.tree-leaf-sub')).toHaveText(LIBRARY_RUN.run_id.slice(0, 8))
  await leaf.click()
  // Opening a run adds a report document keyed by the run and makes it active.
  await expect(documentTab(page, LIBRARY_RUN.display_name)).toHaveAttribute('aria-selected', 'true')
  await expect(page).toHaveURL(new RegExp(`run=${LIBRARY_RUN.run_id}`))
})

test('both profiles filter market tasks without sending a profile', async ({ page }) => {
  await preparePage(page)
  const requests: string[] = []
  page.on('request', request => requests.push(`${request.url()} ${request.postData() ?? ''}`))
  await openTask(page, 'Data & Assets', 'Data downloads')
  await switchProfile(page, 'equities')
  await page.getByRole('menuitem', { name: 'View', exact: true }).click()
  await expect(page.getByRole('menuitem', { name: 'Data & Assets › Funding', exact: true })).toHaveCount(0)
  await page.keyboard.press('Escape')
  await expect(page.getByRole('combobox', { name: 'Download asset' })).toHaveValue('SPY')
  await switchProfile(page, 'crypto')
  await page.getByRole('menuitem', { name: 'View', exact: true }).click()
  await expect(page.getByRole('menuitem', { name: 'Data & Assets › Funding', exact: true })).toHaveCount(0)
  await page.keyboard.press('Escape')
  await expect(page.getByRole('combobox', { name: 'Download asset' })).toHaveValue('BTC/USDT')
  expect(requests.filter(entry => /profile/i.test(entry))).toEqual([])
})

test('the status bar shows the market, the clock and the hovered bar only', async ({ page }) => {
  await preparePage(page)
  const bar = page.getByRole('contentinfo', { name: 'Status bar' })
  await expect(bar.locator('.status-segment--help')).toHaveText('For Help, press F1')
  await expect(bar.locator('.status-segment--profile')).toHaveText('Market: Crypto')
  await expect(bar.locator('.status-segment--clock')).toHaveText(/\d{1,2} [A-Z][a-z]{2} \d{4}, \d{2}:\d{2} UTC/)
  await expect(bar.locator('.status-segment--ohlc')).toHaveText('O: — H: — L: — C: — V: —')
  await expect(bar.locator('.status-segment--bars')).toHaveText(/\d+ \/ \d+ bars/)
  await expect(bar.locator('.status-segment--ssd, .status-segment--paper, .status-segment--providers')).toHaveCount(0)
})

test('Insert › Indicators draws CLI-computed overlays and chart windows tile', async ({ page }) => {
  const bar = (t: number, c: number) => ({ t, o: c, h: c + 1, l: c - 1, c, v: 1 })
  const overlayQueries: string[] = []
  await preparePage(page, {
    candles: {
      // 25 bars: the stand-in refuses a study longer than the window, exactly like the CLI.
      'XRP/USDT': Array.from({ length: 25 }, (_, i) => bar(1_700_000_000 + i * 86_400, 100 + (i % 7))),
    },
    capturedOverlays: (query) => overlayQueries.push(query),
    // An owner who cleared the default studies template: nothing selected.
    settings: { chartTemplate: 1, overlays: { crypto: { indicators: [], patterns: [] } } },
  })
  await openDocument(page, 'Chart')
  const price = page.getByRole('region', { name: 'Price' })
  await expect(price.locator('.count')).toHaveText('25 bars')
  // Nothing selected: the chart asks the CLI for nothing.
  await expect(price.getByRole('button', { name: 'Indicators…', exact: true })).toBeVisible()
  expect(overlayQueries).toEqual([])
  // Insert › Indicators… opens the dialog; a typo never reaches the CLI.
  await page.getByRole('menuitem', { name: 'Insert', exact: true }).click()
  await page.getByRole('menuitem', { name: 'Indicators…', exact: true }).click()
  const dialog = page.getByRole('dialog', { name: 'Indicators' })
  await dialog.getByLabel('Custom indicator spec').fill('foo:1')
  await dialog.getByRole('button', { name: 'Add', exact: true }).click()
  await expect(dialog.getByRole('alert')).toContainText('unknown indicator "foo"')
  await dialog.getByRole('checkbox', { name: 'SMA 20 sma:20', exact: true }).check()
  await dialog.getByRole('checkbox', { name: /Swing highs/ }).check()
  await dialog.getByRole('button', { name: 'Done', exact: true }).click()
  await expect(dialog).toHaveCount(0)
  // The chart re-requested overlays for exactly that selection and draws what came back.
  await expect(price.getByRole('button', { name: 'Indicators… (2)', exact: true })).toBeVisible()
  await expect(price.locator('.overlay-legend')).toHaveText(
    'OVERLAYS · SMA 20 · 1 swings · computed by alpha chart overlays',
  )
  expect(overlayQueries.at(-1)).toBe('?indicator=sma%3A20&pattern=swings')
  await page.getByRole('button', { name: 'Duplicate panel primary', exact: true }).click()
  await expect(page.locator('.analytical-panel:not([data-panel-id=primary])')).toHaveCount(1)
  await expect(page.getByRole('region', { name: 'Price' })).toHaveCount(2)
})

test('Market Watch reads red/green and never invents a price', async ({ page }) => {
  const bar = (t: number, c: number) => ({ t, o: c, h: c, l: c, c, v: 1 })
  await preparePage(page, {
    candles: { 'BTC/USDT': [bar(1_700_000_000, 100), bar(1_700_086_400, 110)], 'ETH/USDT': [bar(1_700_000_000, 50), bar(1_700_086_400, 45)] },
  })
  await openTask(page, 'Data & Assets', 'Price')
  const table = page.getByRole('table', { name: 'Market Watch' })
  // One row per stored pair on one venue, using its exact symbol and last bar date.
  const btc = table.getByRole('row').filter({ hasText: 'BTC/USDT' })
  await expect(btc.getByRole('cell').nth(1)).toHaveText('Binance')
  await expect(btc.getByRole('cell').nth(3)).toHaveText('+10.00%')
  await expect(btc.getByRole('cell').nth(4)).toHaveAttribute('title', 'last stored bar 2023-11-15')
  await expect(btc).toHaveClass(/tone-up/)
  await expect(btc).toHaveClass(/stale/)
  const eth = table.getByRole('row').filter({ hasText: 'ETH/USDT' })
  await expect(eth.getByRole('cell').nth(3)).toHaveText('-10.00%')
  await expect(eth).toHaveClass(/tone-down/)
  const sol = table.getByRole('row').filter({ hasText: 'SOL/USDT' })
  await expect(sol).toHaveCount(0)
  // Details lists every stored quote of the selected base asset with its venue.
  await btc.getByRole('button', { name: 'BTC/USDT' }).click()
  await page.getByRole('tab', { name: 'Details', exact: true }).click()
  const related = page.getByRole('table', { name: 'Stored quotes for the selected asset' })
  await expect(related.getByRole('row').filter({ hasText: 'BTC/USDT' }).getByRole('cell').nth(1)).toHaveText('Binance')
  await page.getByRole('tab', { name: 'Symbols', exact: true }).click()
  // The add row opens the Data Manager on its symbol field.
  await table.getByRole('button', { name: '+ click to add…' }).click()
  await expect(page.locator('#data-manager-symbol')).toBeFocused()
})

test('Market Watch Live is opt-in, quotes each pair from its own venue, and falls back honestly', async ({ page }) => {
  const bar = (t: number, c: number) => ({ t, o: c, h: c, l: c, c, v: 1 })
  const tickerRequests: string[] = []
  page.on('request', (request) => {
    if (request.url().includes('/api/data/ticker')) tickerRequests.push(request.url())
  })
  await preparePage(page, {
    candles: { 'BTC/USDT': [bar(1_700_000_000, 100), bar(1_700_086_400, 110)], 'ETH/USDT': [bar(1_700_000_000, 50), bar(1_700_086_400, 45)] },
    tickers: { 'BTC/USDT@binance': { last: 112.5, ts: '2026-09-03T14:02:11+00:00' } },
  })
  await openTask(page, 'Data & Assets', 'Price')
  const table = page.getByRole('table', { name: 'Market Watch' })
  const btc = table.getByRole('row').filter({ hasText: 'BTC/USDT' })
  await expect(btc.getByRole('cell').nth(4)).toHaveAttribute('title', 'last stored bar 2023-11-15')
  expect(tickerRequests).toEqual([])
  await page.getByRole('checkbox', { name: 'Live' }).check()
  await expect(btc.getByRole('cell').nth(2)).toHaveText('112.5')
  await expect(btc.getByRole('cell').nth(4)).toHaveText('live')
  await expect(btc).not.toHaveClass(/stale/)
  // ETH's venue answered nothing: the stored close and its date stay, dated.
  const eth = table.getByRole('row').filter({ hasText: 'ETH/USDT' })
  await expect(eth.getByRole('cell').nth(2)).toHaveText('45')
  await expect(eth.getByRole('cell').nth(4)).toHaveAttribute('title', 'last stored bar 2023-11-15')
  expect(tickerRequests.every((url) => url.includes('exchange=binance'))).toBe(true)
  expect(tickerRequests.some((url) => url.includes('symbol=BTC%2FUSDT'))).toBe(true)
  await page.getByRole('checkbox', { name: 'Live' }).uncheck()
  await expect(btc.getByRole('cell').nth(4)).toHaveAttribute('title', 'last stored bar 2023-11-15')
})

}

export async function cryptoDataCenterJourney(page: Page): Promise<void> {
  await preparePage(page)

  await openDocument(page, 'Funding')
  const center = page.getByRole('region', { name: 'Crypto Data Center' })
  await expect(center.getByText('Select qualified datasets for one exact frozen snapshot.')).toBeVisible()
  await center.getByRole('tab', { name: 'Assets & Contracts', exact: true }).click()
  await expect(center.getByLabel('Dataset family')).toHaveValue('asset_metadata')
  await expect(center.getByLabel('Instrument')).toHaveValue('all')
  await center.getByRole('button', { name: 'Build from latest qualified catalogs', exact: true }).click()
  await expect(center.getByText('FROZEN · 1 contract mappings', { exact: true })).toBeVisible()
  await center.getByRole('button', { name: 'Verify identity map', exact: true }).click()
  await expect(center.getByText('VERIFIED · 1 contract mappings', { exact: true })).toBeVisible()
  await center.getByRole('tab', { name: 'CEX History', exact: true }).click()
  await center.getByLabel('Dataset family').selectOption('comparison_bars')
  await expect(center.getByLabel('Instrument')).toHaveValue('BTC/USD')
  await expect(center.getByLabel('Quote asset')).toHaveValue('USD')
  await expect(center.getByLabel('Market')).toHaveValue('spot')
  await expect(center.getByLabel('Frequency')).toHaveValue('1d')
  await expect(center.getByLabel('Start UTC')).toBeVisible()
  await center.getByRole('tab', { name: 'Derivatives & Funding', exact: true }).click()
  await center.getByLabel('Dataset family').selectOption('derivative_book_snapshots')
  await expect(center.getByLabel('Market').getByRole('option', { name: 'option' })).toHaveCount(1)
  await expect(center.getByLabel('Start UTC')).toHaveCount(0)
  await center.getByLabel('Dataset family').selectOption('instrument_catalog')
  await expect(center.getByLabel('Market').getByRole('option', { name: 'option' })).toHaveCount(1)
  await center.getByRole('tab', { name: 'Options & Volatility', exact: true }).click()
  await expect(center.getByLabel('Market')).toHaveValue('option')
  await expect(center.getByLabel('Market').getByRole('option')).toHaveCount(1)
  await expect(center.getByText('RECEIPT VERIFIED', { exact: true })).toBeVisible()
  await expect(center.getByLabel('Provider dataset capability')).toContainText(
    'Stored coverage: 2026-08-14T00:00:00+00:00',
  )
  await expect(center.getByText('option quotes · bybit/bybit').first()).toBeVisible()
  await expect(center.getByText('QUARANTINED', { exact: true })).toBeVisible()

  await center.getByRole('button', { name: 'Estimate storage', exact: true }).click()
  await expect(center.getByText(/720 rows · about/)).toBeVisible()
  await center.getByLabel('Frequency').selectOption('5m')
  await expect(center.getByText(/720 rows · about/)).toHaveCount(0)

  await center.getByRole('button', { name: 'Acquire & qualify', exact: true }).click()
  await expect(center.getByText(/Fetching one bounded provider response/)).toBeVisible()
  await expect(center.getByText(/normalized_manifest_id/)).toHaveCount(0)

  await center.getByLabel('Select qualified option_quotes BTC USDT').check()
  await expect(center.getByText('Freeze the 1 selected qualified dataset into a snapshot.')).toBeVisible()
  await center.getByRole('button', { name: 'Freeze selected snapshot', exact: true }).click()
  await expect(center.getByText('Frozen · 1 members', { exact: true })).toBeVisible()
  await center.getByRole('button', { name: 'Verify for research', exact: true }).click()
  await expect(center.getByText('ELIGIBLE', { exact: true })).toBeVisible()
  await expect(center.getByText(new RegExp(CRYPTO_SNAPSHOT_ID))).toBeHidden()

  const qualifiedOption = center.locator('.crypto-dataset').filter({ hasText: 'USDT' }).first()
  await qualifiedOption.getByRole('button', { name: 'Quality', exact: true }).click()
  await expect(center.getByText(/Mechanical quality · BTC · option quotes/)).toBeVisible()
  await center.getByRole('tab', { name: 'Derivatives & Funding', exact: true }).click()
  await center.getByLabel('Select qualified funding BTCUSDT USDT').check()
  await center.getByRole('tab', { name: 'Coverage & Quality', exact: true }).click()
  await expect(center.getByText('EXACT INPUTS READY', { exact: true })).toBeVisible()
  await center.getByRole('button', { name: 'Freeze selected feature', exact: true }).click()
  await expect(center.getByText('FROZEN AND VERIFIED · funding', { exact: true })).toBeVisible()

  await center.getByRole('tab', { name: 'Storage & Jobs', exact: true }).click()
  await expect(center.getByText('READY', { exact: true })).toBeVisible()
  await expect(center.getByText('1.8 TB free of 2.0 TB')).toBeVisible()
  await expect(center.getByText(/\/Volumes\//)).toHaveCount(0)
  await center.getByRole('button', { name: 'Inspect storage inventory', exact: true }).click()
  await expect(center.getByText(/6 manifests · 1 snapshots · 0 staged downloads/)).toBeVisible()
  await center.getByRole('button', { name: 'Verify all immutable data', exact: true }).click()
  await expect(center.getByText(/6 manifests and 1 snapshots re-hashed/)).toBeVisible()
  await center.getByRole('button', { name: 'Review cache cleanup', exact: true }).click()
  await expect(center.getByText('CONFIRM CACHE CLEANUP', { exact: true })).toBeVisible()
  await center.getByRole('button', { name: 'Confirm clean removable cache', exact: true }).click()
  await expect(center.getByText('CACHE CLEANED', { exact: true })).toBeVisible()
  await expect(center.getByText(/immutable artifacts removed: 0/)).toBeVisible()

  const overflow = await page.locator('.research-data-explorer').evaluate(
    (element) => element.scrollWidth - element.clientWidth,
  )
  expect(overflow).toBe(0)
  await expectReleaseAccessibility(page)
}

export function registerWorkstationFeatureTests(): void {
test('running jobs expose exact runtime, bounded ETA, progress, and live output', async ({ page }) => {
  await preparePage(page, {
    jobs: [
      {
        job_id: 'job-progress-fixture',
        command: 'forecast eval AMZN --horizon 21',
        command_path: 'forecast eval',
        kind: 'forecast',
        status: 'running',
        created_at: Date.now() / 1_000 - 120,
        finished_at: null,
        elapsed_seconds: 120,
        current_step: 'Evaluating rolling forecast origin 8 of 20',
        progress_mode: 'estimated',
        progress_fraction: 0.4,
        eta_seconds: 180,
        eta_sample_count: 3,
        run_id: null,
        session_id: null,
        returncode: null,
        n_lines: 14,
      },
    ],
  })
  // Jobs sit in the Toolbox under every document; its tab expands the collapsed strip.
  await openDocument(page, 'Jobs')

  const row = page.getByRole('row').filter({ hasText: 'forecast eval AMZN' })
  const cells = row.getByRole('cell')
  await expect(cells.nth(3)).toHaveText(/2m 0\ds/) // Elapsed
  await expect(cells.nth(4)).toHaveText('~3 min') // ETA
  await expect(cells.nth(6)).toHaveText('Evaluating rolling forecast origin 8 of 20') // Now
  const progress = page.getByRole('progressbar', { name: 'Job forecast eval progress' })
  await expect(progress).toHaveAttribute('aria-valuenow', /4\d/)
  await page.getByRole('button', { name: 'live log' }).click()
  await expect(page.getByText(/Waiting for process output/)).toBeVisible()
  await expect(page.getByRole('button', { name: 'hide log' })).toBeVisible()
  await expectReleaseAccessibility(page)
})

test('a failed job row shows the CLI error message, never a box border', async ({ page }) => {
  const message = 'No data for XRP/USDT on binance before 2018-05-04 (first listed). Start there? (--start 2018-05-04)'
  await preparePage(page, {
    jobs: [
      {
        job_id: 'job-failed-fixture',
        command: 'data pull XRP/USDT --source ccxt --exchange binance --start 2015-01-01 --end 2026-06-30',
        command_path: 'data pull',
        kind: null,
        status: 'failed',
        created_at: Date.now() / 1_000 - 30,
        finished_at: Date.now() / 1_000 - 20,
        elapsed_seconds: 10,
        current_step: message,
        progress_mode: 'terminal',
        progress_fraction: null,
        eta_seconds: null,
        eta_sample_count: 0,
        run_id: null,
        session_id: null,
        returncode: 2,
        n_lines: 3,
      },
    ],
  })
  await openDocument(page, 'Jobs')
  const row = page.getByRole('row').filter({ hasText: 'data pull XRP/USDT' })
  await expect(row.getByRole('cell').nth(6)).toHaveText(message)
  await expect(page.getByTitle(message)).toBeVisible()
  await expect(page.getByText(/[─│╭╮╰╯]/)).toHaveCount(0)
  await expectReleaseAccessibility(page)
})

test('causal chart paginates evidence, selects an event, and exports exact OHLCV', async ({ page }) => {
  await preparePage(page, {
    chartBundle: causalChartBundle(),
    trades: CAUSAL_TRADES,
    runs: [HEAVY_LIBRARY_RUN],
  })
  await openHeavyPrice(page)

  await expect(page.getByLabel('Price').getByText('205 bars', { exact: true })).toBeVisible()
  await expect(page.locator('.status-segment--bars')).toHaveText('205 / 205 bars')
  await expect(page.getByText(/1–80 \/ 91 RETURNED EVENTS/)).toBeVisible()
  await expect(page.getByText(/BACKEND PROJECTION TRUNCATED · MORE TRACE EVENTS EXIST/)).toBeVisible()
  await page.getByRole('button', { name: 'Next trace page' }).click()
  await expect(page.getByText(/81–91 \/ 91 RETURNED EVENTS/)).toBeVisible()

  // Selecting a trace event names it and draws its holding period on the chart. The
  // two-way link to the trade blotter is not asserted here: the blotter now lives inside
  // Run Detail on the Results screen, so the two are never on screen together.
  await page.locator('button.trace-event').filter({ hasText: '0091' }).click()
  await expect(page.getByText('trade · #91', { exact: true })).toBeVisible()
  await page.getByRole('button', { name: 'Previous trace page' }).click()
  await page.locator('button.trace-event').first().click()
  await expect(page.getByText('trade · #91', { exact: true })).toHaveCount(0)

  await page.getByText(/OHLCV TABLE AND EXACT CSV/i).click()
  await expect(page.getByText(/1–100 \/ 205 RETURNED BARS/)).toBeVisible()
  await page.getByRole('button', { name: 'Next OHLCV page' }).click()
  await expect(page.getByText(/101–200 \/ 205 RETURNED BARS/)).toBeVisible()

  const downloadEvent = page.waitForEvent('download')
  await page.getByRole('button', { name: 'Download exact returned OHLCV CSV' }).click()
  const download = await downloadEvent
  const downloadPath = await download.path()
  expect(downloadPath).not.toBeNull()
  const csv = await readFile(downloadPath!, 'utf8')
  const lines = csv.trimEnd().split('\n')
  expect(lines).toHaveLength(206)
  expect(lines[0]).toBe('timestamp_utc,open,high,low,close,volume')
  expect(lines[1]).toBe('2025-01-01T00:00:00.000Z,100,102,99,101,1000')
  expect(lines.at(-1)).toBe(
    `${new Date((CAUSAL_START_TS + 204 * 86_400) * 1_000).toISOString()},304,306,303,305,1204`,
  )
  await expectReleaseAccessibility(page)
})

test('dense causal chart layers cap visuals without hiding returned evidence', async ({ page }) => {
  await preparePage(page, { chartBundle: denseCausalChartBundle(), runs: [HEAVY_LIBRARY_RUN] })
  await openHeavyPrice(page)

  const executions = page.getByRole('button', { name: 'executions', exact: true })
  const decisions = page.getByRole('button', { name: 'decisions', exact: true })
  const all = page.getByRole('button', { name: 'all', exact: true })
  await expect(executions).toHaveAttribute('aria-pressed', 'true')
  await expect(page.getByText('90/180 markers shown', { exact: true })).toBeVisible()
  await decisions.click()
  await expect(decisions).toHaveAttribute('aria-pressed', 'true')
  await expect(page.getByText('90/180 markers shown', { exact: true })).toBeVisible()
  await all.click()
  await expect(all).toHaveAttribute('aria-pressed', 'true')
  await expect(page.getByText('140/180 markers shown', { exact: true })).toBeVisible()
  await expect(page.getByText(/1–80 \/ 180 RETURNED EVENTS/)).toBeVisible()
})

test('a figure maximises into a dialog with Save PNG, Save SVG, Copy and Esc', async ({ page }) => {
  await page.addInitScript(() => {
    Object.defineProperty(navigator, 'clipboard', {
      configurable: true,
      value: {
        write: async () => {
          ;(window as unknown as { __copied: boolean }).__copied = true
        },
      },
    })
  })
  await preparePage(page, { runs: [LIBRARY_RUN], figureCatalogue: true })
  // Terse mode: the prose must still be in the DOM, only hidden from sight.
  await openSettings(page)
  await page.getByLabel('Explanations', { exact: true }).selectOption('terse')
  await openTask(page, 'Results', 'Run library')
  await backtestLeaf(page, LIBRARY_RUN.display_name).click()
  await page.getByRole('button', { name: 'Ratios & performance' }).click()
  const card = page.locator('.figure-card')
  await expect(card).toHaveCount(1)
  await expect(card.locator('.figure-explain')).toHaveClass(/sr-only/)
  await expect(card.locator('.figure-explain')).toContainText('In-sample only.')

  const expand = card.getByRole('button', { name: 'Open full screen' })
  await expand.click()
  const dialog = page.getByRole('dialog', { name: 'Equity curve' })
  await expect(dialog).toBeVisible()
  await expect(dialog.getByRole('link', { name: 'Save PNG' })).toBeFocused()
  await page.keyboard.press('Tab')
  await expect(dialog.getByRole('link', { name: 'Save SVG' })).toBeFocused()
  await page.keyboard.press('Tab')
  await expect(dialog.getByRole('button', { name: 'Copy' })).toBeFocused()
  await page.keyboard.press('Tab')
  await expect(dialog.getByRole('button', { name: 'Close' })).toBeFocused()
  await page.keyboard.press('Tab')
  // Artboard 3: zoom follows Close; out/fit are disabled until zoomed, so the trap skips them.
  await expect(dialog.getByRole('button', { name: 'Zoom in' })).toBeFocused()
  await page.keyboard.press('Tab')
  await expect(dialog.getByRole('link', { name: 'Save PNG' })).toBeFocused()
  await expect(dialog).toContainText('(maximised)')
  await expect(dialog).toContainText(`Esc restores · run ${LIBRARY_RUN.run_id.slice(0, 8)} · UTC`)
  await expect(dialog.getByRole('link', { name: 'Save PNG' })).toHaveAttribute(
    'download',
    'abcdef01-equity_curve.png',
  )
  await dialog.getByRole('button', { name: 'Copy' }).click()
  await expect(dialog.getByRole('button', { name: 'Copied' })).toBeVisible()
  expect(await page.evaluate(() => (window as unknown as { __copied?: boolean }).__copied)).toBe(true)
  await expectReleaseAccessibility(page)

  await page.keyboard.press('Escape')
  await expect(page.getByRole('dialog', { name: 'Equity curve' })).toHaveCount(0)
  await expect(expand).toBeFocused()

  // Double-clicking the image is the mouse route; Close is the other way out.
  await card.locator('.figure-image').dblclick()
  await expect(page.getByRole('dialog', { name: 'Equity curve' })).toBeVisible()
  await page.getByRole('button', { name: 'Close', exact: true }).click()
  await expect(page.getByRole('dialog', { name: 'Equity curve' })).toHaveCount(0)
  await expect(expand).toBeFocused()
})

test('a figure card shows the plain chart, a toggle for the annotated chart and the long explanation on white', async ({ page }) => {
  await preparePage(page, { runs: [LIBRARY_RUN], figureCatalogue: true })
  await openTask(page, 'Results', 'Run library')
  await backtestLeaf(page, LIBRARY_RUN.display_name).click()
  await page.getByRole('button', { name: 'Ratios & performance' }).click()
  const card = page.locator('.figure-card')
  await expect(card).toHaveCount(1)
  const image = card.locator('.figure-image')
  await expect(image).toHaveAttribute('src', /variant=plain/)
  await expect(card.getByRole('complementary', { name: 'How to read this chart' })).toContainText(
    'The horizontal axis is the date.',
  )
  await expect(card.locator('.figure-surface')).toHaveCSS('background-color', 'rgb(255, 255, 255)')
  await card.getByRole('button', { name: 'Show annotated' }).click()
  await expect(image).toHaveAttribute('src', /variant=annotated/)
  await expect(card.getByRole('button', { name: 'Show plain chart' })).toHaveAttribute('aria-pressed', 'true')
  await card.getByRole('button', { name: 'Show plain chart' }).click()
  await expect(image).toHaveAttribute('src', /variant=plain/)
})

test('Phase 3 acceptance: terminal chrome on every document, no hazard stripe, figures maximise, runs read like a trader', async ({ page }) => {
  await preparePage(page, { runs: [LIBRARY_RUN], figureCatalogue: true })
  for (const item of DOCUMENTS) {
    await openDocument(page, item.title)
    await expect(page.getByRole('menubar', { name: 'Terminal menu' })).toBeVisible()
    await expect(page.getByRole('button', { name: 'Symbol, venue and timeframe' })).toBeVisible()
    await expect(item.id === 'chart' ? page.locator('.analytical-workspace') : page.locator('.workflow-panel')).toHaveCount(1)
    await expect(page.locator('.menubar')).toHaveCount(1)
  }
  // The run leaf reads strategy · D1 · symbol · dates, with the id only as a mono sub-line.
  await openTask(page, 'Results', 'Run library')
  const row = backtestLeaf(page, LIBRARY_RUN.display_name)
  await expect(row.locator('.tree-leaf-label')).toHaveText(LIBRARY_RUN.display_name)
  expect(LIBRARY_RUN.display_name).toMatch(/^ma_crossover D1 — SPY · \d{4}-\d{2}-\d{2} → \d{4}-\d{2}-\d{2} · run [0-9a-f]{8}$/)
  // Every figure card opens the overlay.
  await row.click()
  await page.getByRole('button', { name: 'Ratios & performance' }).click()
  const cards = page.locator('.figure-card')
  await expect(cards).toHaveCount(1)
  for (let index = 0; index < (await cards.count()); index += 1) {
    await cards.nth(index).getByRole('button', { name: 'Open full screen' }).click()
    await expect(page.getByRole('dialog', { name: 'Equity curve' })).toBeVisible()
    await page.keyboard.press('Escape')
    await expect(page.getByRole('dialog', { name: 'Equity curve' })).toHaveCount(0)
  }
  await expectReleaseAccessibility(page)
})

test('the run report is a tree with a summary table and one watermark chip', async ({ page }) => {
  await preparePage(page, { researchGateOverride: true })
  await openTask(page, 'Results', 'Run library')
  await backtestLeaf(page, WATERMARKED_RUN_ITEM.display_name).click()
  const tree = page.getByRole('tree', { name: 'Report sections' })
  await expect(tree).toBeVisible()
  await expect(tree.locator(':scope > li')).toHaveCount(5)
  await expect(page.getByRole('table').filter({ hasText: 'Summary — what this run recorded' })).toBeVisible()
  await expect(page.locator('.run-outcome-summary')).toHaveCount(0)
  await expect(page.locator('.rg-watermark-banner')).toHaveCount(0)
  await expect(page.getByRole('tab', { name: 'Stress test' })).toHaveCount(0)
  await expect(page.locator('.rg-watermark-chip')).toHaveText(RESEARCH_GATE_WATERMARK)
  await expectReleaseAccessibility(page)
})

test('the working documents carry no sandbox banner', async ({ page }) => {
  await preparePage(page)
  for (const title of ['Jobs']) {
    await openDocument(page, title)
    await expect(page.locator('.sandbox-banner')).toHaveCount(0)
  }
})

}


export function registerReferenceTests(): void {
test('@reference-only @perf-budget cold shell and document switch meet workstation latency budgets', async ({ page }) => {
  await preparePage(page)

  const coldShellMs = await page.evaluate(() => performance.now())
  expect(coldShellMs).toBeLessThan(1_500)

  const switchMs = await page.evaluate(async () => {
    const started = performance.now()
    window.location.hash = 'page=data&pane=PriceChart'
    for (let frame = 0; frame < 12; frame += 1) {
      await new Promise<void>((resolve) => requestAnimationFrame(() => resolve()))
      if (document.querySelector('.price-chart-frame, .price-toolbar')) {
        return performance.now() - started
      }
    }
    throw new Error('the Chart document did not render within 12 animation frames')
  })
  expect(switchMs).toBeLessThan(100)
})

test('@reference-only @perf-budget 25k bars and 200 annotations remain interactively responsive', async ({ page }) => {
  test.setTimeout(45_000)
  const bundle = heavyChartBundle()
  await preparePage(page, { chartBundle: bundle, runs: [HEAVY_LIBRARY_RUN] })

  const renderStarted = Date.now()
  await openHeavyPrice(page)

  await expect(page.getByLabel('Price').getByText(`${HEAVY_BAR_COUNT} bars`, { exact: true })).toBeVisible({
    timeout: 12_000,
  })
  const chart = page.locator('.price-chart-canvas-wrap')
  await expect(chart).toBeVisible()
  await page.evaluate(() => new Promise<void>((resolve) => requestAnimationFrame(() => resolve())))
  expect(Date.now() - renderStarted).toBeLessThan(12_000)

  await chart.hover()
  await page.evaluate(() => new Promise<void>((resolve) => requestAnimationFrame(() => resolve())))
  const before = await chart.screenshot()
  const interactionStarted = Date.now()
  await page.mouse.wheel(0, -600)
  await page.evaluate(
    () =>
      new Promise<void>((resolve) =>
        requestAnimationFrame(() => requestAnimationFrame(() => resolve())),
      ),
  )
  const after = await chart.screenshot()

  expect(after.equals(before)).toBe(false)
  expect(Date.now() - interactionStarted).toBeLessThan(2_000)

  const cadence = await chart.evaluate(async (element) => {
    const measure = async (interactive: boolean) => {
      const intervals: number[] = []
      let previous = performance.now()
      for (let frame = 0; frame < 60; frame += 1) {
        await new Promise<void>((resolve) =>
          requestAnimationFrame((timestamp) => {
            intervals.push(timestamp - previous)
            previous = timestamp
            if (interactive) {
              element.dispatchEvent(
                new WheelEvent('wheel', {
                  bubbles: true,
                  cancelable: true,
                  deltaY: frame % 2 ? 24 : -24,
                }),
              )
            }
            resolve()
          }),
        )
      }
      const measured = intervals.slice(1).sort((left, right) => left - right)
      const percentile = (fraction: number): number =>
        measured[Math.min(measured.length - 1, Math.floor(measured.length * fraction))]!
      return {
        medianFrameMs: percentile(0.5),
        p99FrameMs: percentile(0.99),
        overBudgetRatio: measured.filter((interval) => interval > 20).length / measured.length,
      }
    }
    return { baseline: await measure(false), interactive: await measure(true) }
  })
  // A 60 Hz desk has a 16.67 ms frame budget. Headless Chromium on macOS periodically reports
  // 25–27 ms rAF intervals even with no dispatched interaction, so compare chart navigation with
  // an immediately adjacent no-input baseline instead of misclassifying host scheduler jitter.
  expect(cadence.interactive.medianFrameMs).toBeLessThanOrEqual(18)
  expect(cadence.interactive.overBudgetRatio).toBeLessThanOrEqual(
    cadence.baseline.overBudgetRatio + 0.05,
  )
  expect(cadence.interactive.p99FrameMs).toBeLessThanOrEqual(34)
})
}

export function registerLifecycleTests(): void {
test('a store change outside the browser refreshes the panel watching its area', async ({ page }) => {
  await preparePage(page, {
    jobs: [
      {
        job_id: 'job-pull-1',
        run_type: null,
        command: 'data pull XRP/USDT --source ccxt --exchange binance --start 2019-01-01',
        command_path: 'data pull',
        kind: 'data',
        status: 'done',
        created_at: Date.now() / 1_000 - 60,
        finished_at: Date.now() / 1_000 - 52,
        elapsed_seconds: 8,
        current_step: 'complete',
        progress_mode: 'exact',
        progress_fraction: 1,
        eta_seconds: null,
        eta_sample_count: 0,
        run_id: null,
        session_id: null,
        returncode: 0,
        n_lines: 3,
      },
      {
        job_id: 'job-bt-1',
        run_type: 'runs',
        command: 'backtest run SPY --strategy ma_crossover',
        command_path: 'backtest run',
        kind: 'backtest',
        status: 'done',
        created_at: Date.now() / 1_000 - 30,
        finished_at: Date.now() / 1_000 - 20,
        elapsed_seconds: 10,
        current_step: 'complete',
        progress_mode: 'exact',
        progress_fraction: 1,
        eta_seconds: null,
        eta_sample_count: 0,
        run_id: 'abcdefabcdefabcd',
        session_id: null,
        returncode: 0,
        n_lines: 3,
      },
    ],
  })
  await openDocument(page, 'Jobs')
  // Data pulls is the jobs table filtered to data work.
  await openTask(page, 'Operations', 'Data jobs')
  await expect(page.getByRole('row').filter({ hasText: 'data pull XRP/USDT' })).toHaveCount(1)
  await expect(page.getByRole('row').filter({ hasText: 'backtest run SPY' })).toHaveCount(0)
})

test('Data Manager Snapshots tab lists snapshots and Verify runs a data job', async ({ page }) => {
  const posts: Array<{ path: string; body: Record<string, unknown> }> = []
  await preparePage(page, {
    extraGet: {
      '/api/data/snapshots': {
        snapshots: [
          {
            snapshot_id: 'snap1',
            created_at: '2026-01-01T00:00:00+00:00',
            source: 'tiingo',
            adapter_version: '1',
            parser_version: '1',
            symbols: ['AAPL'],
            manifest_sha256: 'a'.repeat(64),
          },
        ],
      },
    },
    capturedPost: (path, body) => {
      posts.push({ path, body })
      if (path === '/api/jobs') return { job_id: 'job-verify-1', status: 'running' }
      return undefined
    },
  })
  await openTask(page, 'Data & Assets', 'Data downloads')
  const dock = page.locator('.workflow-panel')
  await dock.getByRole('tablist', { name: 'Data Manager sections' }).getByRole('tab', { name: 'Snapshots' }).click()
  const row = page.getByRole('table', { name: 'Snapshots' }).getByRole('row').filter({ hasText: 'snap1' })
  await expect(row).toContainText('tiingo')
  await row.getByRole('button', { name: 'Verify' }).click()
  await expect(page.getByText(/verify snap1 started as job job-verify-1/)).toBeVisible()
  expect(posts).toEqual([{ path: '/api/jobs', body: { command: 'data', args: 'verify snap1' } }])
})

}

/** Open the Settings page (display preferences) from the View menu. */
export async function openSettings(page: Page): Promise<void> {
  await page.getByRole('menuitem', { name: 'View', exact: true }).click()
  await page.getByRole('menuitem', { name: 'Settings', exact: true }).click()
  await expect(page.getByLabel('Explanations', { exact: true })).toBeVisible()
}

export async function openTask(page: Page, section: string, task: string): Promise<void> {
  await page.getByRole('menuitem', { name: 'View', exact: true }).click()
  await page.getByRole('menuitem', { name: `${section} › ${task}`, exact: true }).click()
}

export async function openDeskTool(page: Page, name: string): Promise<void> {
  const options = page.locator('details').filter({ has: page.locator('summary').filter({ hasText: /^Docks$/ }) })
  if (await options.getAttribute('open') === null) await page.getByText('Docks', { exact: true }).click()
  await page.getByRole('button', { name, exact: true }).click()
  await page.getByText('Docks', { exact: true }).click()
}
