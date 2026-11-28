// Thin typed client over the FastAPI JSON layer. Same-origin (loopback), so no base URL.

import type { components } from './generated'

type Schema = components['schemas']

import type {
  Candles,
  MarketOverview,
  FollowToday,
  FollowShow,
  IdeaFile,
  IdeaList,
  ChartOverlays,
  RuleList,
  ChartBundle,
  CommandDef,
  CryptoAcquisitionRequest,
  CryptoAssetMaster,
  CryptoAssetMasters,
  CryptoCatalog,
  CryptoCapabilities,
  CryptoCoverage,
  CryptoEstimate,
  CryptoEstimateRequest,
  CryptoFeature,
  CryptoFeatureCreateRequest,
  CryptoFeatures,
  CryptoQuality,
  CryptoSnapshotCreate,
  CryptoSnapshotVerify,
  CryptoSnapshotVerifyRequest,
  CryptoStorage,
  CryptoStorageInventory,
  CryptoStorageVerify,
  CryptoCacheClean,
  EquitySeries,
  RunSeries,
  FirstBar,
  Ticker,
  ForecastOrigins,
  ForecastPaths,
  ForecastSeries,
  JobDetail,
  JobSummary,
  NativeTearSheetProjection,
  NullTiers,
  OptimTrials,
  PortfolioAnalyticsProjection,
  ProviderDefinition,
  DataSnapshots,
  DataSourceStatus,
  FigureCatalogue,
  RunComparison,
  FigureMetadata,
  RiskReport,
  RunContextV1,
  RuleTestChecks,
  RunDetail,
  RunList,
  StrategyDef,
  TradeRow,
} from './types'

export function runContextForProject(projectId: string | null): RunContextV1 {
  return projectId
    ? { schema_version: 1, kind: 'governed_project', project_id: projectId }
    : { schema_version: 1, kind: 'standalone_sandbox' }
}

export async function getJSON<T>(url: string): Promise<T> {
  const res = await fetch(url)
  if (!res.ok) throw await responseError(res)
  return (await res.json()) as T
}

/**
 * What failed and what to try, in plain words: the server's own message, its field errors and its
 * recovery step. The HTTP status and the request id stay out of the text the owner reads.
 */
async function responseError(res: Response): Promise<Error> {
  let message = res.status >= 500 ? 'The Workstation server could not answer this request.' : 'The Workstation refused this request.'
  let recovery = ''
  let fields = ''
  try {
    const parsed: unknown = await res.json()
    if (parsed && typeof parsed === 'object' && !Array.isArray(parsed)) {
      const error = parsed as Record<string, unknown>
      if (typeof error.message === 'string' && error.message) message = error.message
      if (typeof error.recovery_action === 'string') recovery = error.recovery_action
      if (Array.isArray(error.field_errors)) {
        fields = error.field_errors
          .flatMap((item) => {
            if (!item || typeof item !== 'object' || Array.isArray(item)) return []
            const field = (item as Record<string, unknown>).field
            const fieldMessage = (item as Record<string, unknown>).message
            return typeof field === 'string' && typeof fieldMessage === 'string'
              ? [`${field}: ${fieldMessage}`]
              : []
          })
          .join('; ')
      }
    }
  } catch {
    // The stable API contract was unavailable; never relay an untrusted raw response to the DOM.
  }
  const advice = recovery || 'Try again. If it keeps failing, restart the Workstation.'
  const plain = `${message}${fields ? ` Fields: ${fields}.` : ''} ${advice}`
  // Panels print `String(cause)`; the owner reads a sentence, not "Error: ...".
  return Object.assign(new Error(plain), { toString: () => plain })
}

const IMMUTABLE_CACHE_LIMIT = 128
const immutableCache = new Map<string, Promise<unknown>>()

function getImmutableJSON<T>(url: string): Promise<T> {
  const existing = immutableCache.get(url)
  if (existing) {
    immutableCache.delete(url)
    immutableCache.set(url, existing)
    return existing as Promise<T>
  }
  const request = getJSON<T>(url).catch((error: unknown) => {
    immutableCache.delete(url)
    throw error
  })
  immutableCache.set(url, request)
  if (immutableCache.size > IMMUTABLE_CACHE_LIMIT) {
    const oldest = immutableCache.keys().next().value
    if (oldest !== undefined) immutableCache.delete(oldest)
  }
  return request
}

export function clearImmutableApiCache(): void {
  immutableCache.clear()
}

export type ArchiveChartDataset = Schema['ArchiveChartDataset']

export interface LiteratureCandidate {
  candidate_id: string
  title: string
  provider: string
  doi: string | null
  year: number | null
  authors: string[]
  open_access_url: string | null
  access_state: 'direct_pdf' | 'landing_page' | 'metadata_only' | 'unavailable'
  relevance_explanation: string
  matched_concepts: string[]
  retracted: boolean | null
}

export interface LiteratureDiscoveryResult {
  discovery_id: string
  query: string
  candidates: LiteratureCandidate[]
  receipt: Record<string, unknown>
}

export interface LiteratureAcquisitionResult {
  source: Record<string, unknown>
  document: {
    extraction_id: string
    status: 'extracted' | 'encrypted' | 'image_only' | 'truncated' | 'parser_failed'
    page_count: number
    character_count: number
    warnings: string[]
    artifact: Record<string, unknown>
  }
  acquisition: Record<string, unknown>
}

export async function postJSON<T>(url: string, body: unknown): Promise<T> {
  const res = await fetch(url, {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!res.ok) throw await responseError(res)
  return (await res.json()) as T
}

export const api = {
  chartDatasets: (): Promise<Schema['ArchiveChartDatasets']> => getJSON('/api/chart-datasets'),
  cryptoMarketCatalog: (query = '', limit = 25): Promise<Schema['CryptoMarketCatalogResponse']> => {
    const params = new URLSearchParams({ query, limit: String(limit) })
    return getJSON(`/api/crypto-data/market-catalog?${params.toString()}`)
  },
  runs: (query = ''): Promise<RunList> => getJSON(`/api/runs${query}`),
  run: (id: string): Promise<RunDetail> => getImmutableJSON(`/api/runs/${id}`),
  chartBundle(id: string, limit = 2_000, start?: string | null, end?: string | null): Promise<ChartBundle> {
    const params = new URLSearchParams({ limit: String(limit) })
    if (start) params.set('start', start)
    if (end) params.set('end', end)
    return getImmutableJSON(`/api/runs/${id}/chart-bundle?${params.toString()}`)
  },
  compareRuns: (runIds: string[]): Promise<RunComparison> =>
    postJSON('/api/v3/runs/compare', { run_ids: runIds }),
  ruleTestChecks: (id: string): Promise<RuleTestChecks> => getJSON(`/api/runs/${id}/checks`),
  figures: (id: string): Promise<FigureCatalogue> => getJSON(`/api/runs/${id}/figures`),
  figureMetadata: (
    id: string,
    figureId: string,
    variant: 'plain' | 'annotated' = 'plain',
    fmt: 'svg' | 'png' = 'svg',
  ): Promise<FigureMetadata> => getJSON(`/api/runs/${id}/figures/${figureId}?fmt=${fmt}&variant=${variant}`),
  // Content-addressed: the key makes the URL immutable, so the browser caches it for good.
  figureImageUrl: (
    id: string,
    figureId: string,
    key: string,
    fmt: 'svg' | 'png' = 'svg',
    variant: 'plain' | 'annotated' = 'plain',
  ): string => `/api/runs/${id}/figures/${figureId}/image?fmt=${fmt}&variant=${variant}&key=${key}`,
  equity: (id: string): Promise<EquitySeries> => getImmutableJSON(`/api/runs/${id}/equity`),
  // Not cached for good: the price status depends on the stored bars as they are now.
  runSeries: (id: string, limit = 2000): Promise<RunSeries> => getJSON(`/api/runs/${id}/series?limit=${limit}`),
  trades: (id: string): Promise<TradeRow[]> => getImmutableJSON(`/api/runs/${id}/trades`),
  forecast: (id: string): Promise<ForecastSeries> => getImmutableJSON(`/api/runs/${id}/forecast`),
  forecastPaths: (id: string, n = 20): Promise<ForecastPaths> =>
    getImmutableJSON(`/api/runs/${id}/forecast/paths?n=${n}`),
  nulls: (id: string): Promise<NullTiers> => getImmutableJSON(`/api/runs/${id}/nulls`),
  trials: (id: string): Promise<OptimTrials> => getImmutableJSON(`/api/runs/${id}/trials`),
  origins: (id: string): Promise<ForecastOrigins> => getImmutableJSON(`/api/runs/${id}/origins`),
  nativeTearsheet: (id: string, pointLimit = 750): Promise<NativeTearSheetProjection> =>
    getImmutableJSON(`/api/runs/${id}/native-tearsheet?point_limit=${pointLimit}`),
  portfolioAnalytics: (
    id: string,
    timestampLimit = 2000,
    symbolLimit = 50,
  ): Promise<PortfolioAnalyticsProjection> =>
    getImmutableJSON(
      `/api/runs/${id}/portfolio-analytics?timestamp_limit=${timestampLimit}&symbol_limit=${symbolLimit}`,
    ),
  tearsheetUrl: (id: string): string => `/api/runs/${id}/tearsheet`,
  candles: (symbol: string, query = ''): Promise<Candles> =>
    (new URLSearchParams(query).has('manifest_id') || new URLSearchParams(query).has('snapshot') ? getImmutableJSON<Candles> : getJSON<Candles>)(`/api/candles/${encodeURIComponent(symbol)}${query}`),
  overlays: (symbol: string, query = ''): Promise<ChartOverlays> =>
    getJSON(`/api/overlays/${encodeURIComponent(symbol)}${query}`),
  rules: (): Promise<RuleList> => getJSON('/api/rules'),
  strategies: (): Promise<StrategyDef[]> => getJSON('/api/strategies'),
  commands: (): Promise<CommandDef[]> => getJSON('/api/commands'),
  symbols: (): Promise<{ symbols: string[] }> => getJSON('/api/symbols'),
  marketOverview: (store: string, window: number, limit = 15): Promise<MarketOverview> =>
    getJSON(`/api/market/overview?${new URLSearchParams({ store, window: String(window), limit: String(limit) })}`),
  followToday: (): Promise<FollowToday> => getJSON('/api/follow/today'),
  ideaList: (): Promise<IdeaList> => getJSON('/api/ideas'),
  ideaFile: (card: string): Promise<IdeaFile> => getJSON(`/api/ideas/${encodeURIComponent(card)}`),
  followShow: (id: string): Promise<FollowShow> => getJSON(`/api/follow/${encodeURIComponent(id)}`),
  firstBar: (symbol: string, exchange: string): Promise<FirstBar> =>
    getJSON(
      `/api/data/first-bar?symbol=${encodeURIComponent(symbol)}&exchange=${encodeURIComponent(exchange)}`,
    ),
  ticker: (symbol: string, exchange: string): Promise<Ticker> =>
    getJSON(
      `/api/data/ticker?symbol=${encodeURIComponent(symbol)}&exchange=${encodeURIComponent(exchange)}`,
    ),
  providers: (): Promise<ProviderDefinition[]> => getJSON('/api/providers'),
  cryptoCatalog: (): Promise<CryptoCatalog> => getJSON('/api/crypto-data/catalog'),
  cryptoCapabilities: (): Promise<CryptoCapabilities> =>
    getJSON('/api/crypto-data/capabilities'),
  cryptoStorage: (): Promise<CryptoStorage> => getJSON('/api/crypto-data/storage'),
  cryptoStorageInventory: (): Promise<CryptoStorageInventory> =>
    getJSON('/api/crypto-data/storage/inventory'),
  cryptoStorageVerify: (): Promise<CryptoStorageVerify> =>
    postJSON('/api/crypto-data/storage/verify', {}),
  cryptoCacheClean: (): Promise<CryptoCacheClean> =>
    postJSON('/api/crypto-data/storage/cache/clean', { confirm: true }),
  cryptoCoverage: (): Promise<CryptoCoverage> => getJSON('/api/crypto-data/coverage'),
  cryptoAssetMasters: (): Promise<CryptoAssetMasters> =>
    getJSON('/api/crypto-data/asset-masters'),
  cryptoAssetMasterCreate: (
    coingeckoManifestId: string,
    geckoterminalManifestIds: string[],
  ): Promise<CryptoAssetMaster> =>
    postJSON('/api/crypto-data/asset-masters', {
      coingecko_manifest_id: coingeckoManifestId,
      geckoterminal_manifest_ids: geckoterminalManifestIds,
    }),
  cryptoAssetMasterVerify: (version: string): Promise<CryptoAssetMaster> =>
    postJSON(`/api/crypto-data/asset-masters/${encodeURIComponent(version)}/verify`, {}),
  cryptoQuality: (manifestId: string): Promise<CryptoQuality> =>
    getJSON(`/api/crypto-data/quality/${encodeURIComponent(manifestId)}`),
  cryptoFeatures: (): Promise<CryptoFeatures> => getJSON('/api/crypto-data/features'),
  cryptoFeatureCreate: (body: CryptoFeatureCreateRequest): Promise<CryptoFeature> =>
    postJSON('/api/crypto-data/features', body),
  cryptoEstimate: (body: CryptoEstimateRequest): Promise<CryptoEstimate> =>
    postJSON('/api/crypto-data/estimate', body),
  cryptoAcquire: (
    body: CryptoAcquisitionRequest,
  ): Promise<{ job_id: string; status: string; session_id?: string | null }> =>
    postJSON('/api/crypto-data/acquisitions', body),
  cryptoSnapshotCreate: (
    manifestIds: string[],
    assetMasterVersion = 'reviewed-native-v1',
  ): Promise<CryptoSnapshotCreate> =>
    postJSON('/api/crypto-data/snapshots', {
      manifest_ids: manifestIds,
      asset_master_version: assetMasterVersion,
    }),
  cryptoSnapshotVerify: (
    snapshotId: string,
    body: CryptoSnapshotVerifyRequest,
  ): Promise<CryptoSnapshotVerify> =>
    postJSON(`/api/crypto-data/snapshots/${encodeURIComponent(snapshotId)}/verify`, body),
  jobs: (): Promise<JobSummary[]> => getJSON('/api/jobs'),
  job: (id: string): Promise<JobDetail> => getJSON(`/api/jobs/${id}`),
  async launch(
    command: string,
    args: string,
    runContext?: RunContextV1,
  ): Promise<{ job_id: string; status: string; session_id?: string | null }> {
    const res = await fetch('/api/jobs', {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ command, args, ...(runContext ? { run_context: runContext } : {}) }),
    })
    if (!res.ok) throw await responseError(res)
    return (await res.json()) as { job_id: string; status: string; session_id?: string | null }
  },
  cancel: (id: string): Promise<Response> => fetch(`/api/jobs/${id}`, { method: 'DELETE' }),
  streamUrl: (id: string): string => `/api/jobs/${id}/stream`,
  riskScenario: (runId: string, confidence = 0.95): Promise<RiskReport> =>
    getJSON(`/api/risk/scenario?run_id=${encodeURIComponent(runId)}&confidence=${confidence}&include_metric_basis=true`),
  dataSnapshots: (): Promise<DataSnapshots> => getJSON('/api/data/snapshots'),
  dataSourceStatus: (symbol: string): Promise<DataSourceStatus> =>
    getJSON(`/api/data/source-status?symbol=${encodeURIComponent(symbol)}`),
}
