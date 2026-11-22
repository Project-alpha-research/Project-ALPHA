import { useCallback, useEffect, useMemo, useState } from 'react'

import { api } from '../api/client'
import type {
  CryptoAcquisitionRequest,
  CryptoAssetMaster,
  CryptoAssetMasters,
  CryptoCatalog,
  CryptoCapabilities,
  CryptoCoverage,
  CryptoCoverageItem,
  CryptoEstimate,
  CryptoFamily,
  CryptoFeature,
  CryptoFeatureName,
  CryptoFeatures,
  CryptoQuality,
  CryptoSnapshotCreate,
  CryptoSnapshotRegister,
  CryptoSnapshotVerify,
  CryptoStorage,
  CryptoStorageInventory,
  CryptoStorageVerify,
  CryptoCacheClean,
} from '../api/types'
import { JobConsole } from '../components/JobConsole'
import { fmtBytes } from '../util/format'
import { CryptoAcquisitionView } from './CryptoAcquisitionView'
import { CryptoAssetsView } from './CryptoAssetsView'
import { CryptoCoverageView } from './CryptoCoverageView'
import { CryptoQualityView } from './CryptoQualityView'
import {
  cryptoCanonicalAction,
  cryptoAcquisitionFrequencies,
  cryptoFeatureInputSelection,
  cryptoMarketChoicesForFamily,
  cryptoSectionForFamily,
  latestCryptoManifestIds,
  type CryptoDataSection,
} from './researchDataModel'

const SECTIONS: { id: CryptoDataSection; label: string }[] = [
  { id: 'assets', label: 'Assets & Contracts' },
  { id: 'cex', label: 'CEX History' },
  { id: 'derivatives', label: 'Derivatives & Funding' },
  { id: 'options', label: 'Options & Volatility' },
  { id: 'onchain', label: 'On-chain Metrics' },
  { id: 'dex', label: 'DEX Pools & Liquidity' },
  { id: 'defi', label: 'DeFi Fundamentals' },
  { id: 'quality', label: 'Coverage & Quality' },
  { id: 'storage', label: 'Storage & Jobs' },
]

const PROVIDERS = new Set([
  'binance',
  'bybit',
  'coingecko',
  'geckoterminal',
  'coinmetrics',
  'defillama',
  'ccxt:coinbase',
])
const BYBIT_RANGED_FAMILIES = new Set<CryptoFamily>([
  'funding',
  'open_interest',
  'long_short_ratio',
  'derivative_bars',
  'mark_bars',
  'index_bars',
  'premium_bars',
  'historical_volatility',
])

function acquisitionProvider(value: string): CryptoAcquisitionRequest['provider'] | null {
  if (PROVIDERS.has(value)) return value as CryptoAcquisitionRequest['provider']
  return null
}

function defaultInstrument(family: CryptoFamily): string {
  if (family === 'comparison_bars') return 'BTC/USD'
  if (family === 'instrument_catalog') return 'linear'
  if (family === 'asset_metadata') return 'all'
  if (family === 'market_reference') return 'bitcoin'
  if (family === 'onchain_catalog') return 'community'
  if (family === 'onchain_metrics') return 'btc'
  if (family === 'defi_tvl') return 'ethereum'
  if (family === 'protocol_tvl') return 'aave'
  if (family === 'stablecoin_supply') return '1'
  if (family === 'yield_pools') return 'all'
  if (family === 'yield_history') return ''
  if (family.startsWith('option_') || family === 'historical_volatility') return 'BTC'
  return 'BTCUSDT'
}

export function CryptoDataCenter({
  onRegistered,
  initialSection,
  initialFamily,
}: {
  onRegistered?: () => void
  /** The section a document opens on; an unknown id falls back to Derivatives & Funding. */
  initialSection?: CryptoDataSection
  initialFamily?: CryptoFamily
}) {
  const [section, setSection] = useState<CryptoDataSection>(
    SECTIONS.some((item) => item.id === initialSection) ? initialSection! : 'derivatives',
  )
  const [catalog, setCatalog] = useState<CryptoCatalog | null>(null)
  const [capabilities, setCapabilities] = useState<CryptoCapabilities | null>(null)
  const [storage, setStorage] = useState<CryptoStorage | null>(null)
  const [coverage, setCoverage] = useState<CryptoCoverage | null>(null)
  const [loading, setLoading] = useState(true)
  const [refreshing, setRefreshing] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [family, setFamily] = useState<CryptoFamily>(initialFamily ?? 'funding')
  const [instrument, setInstrument] = useState(() => defaultInstrument(initialFamily ?? 'funding'))
  const [base, setBase] = useState('BTC')
  const [quote, setQuote] = useState('USDT')
  const [category, setCategory] = useState<CryptoAcquisitionRequest['category']>('linear')
  const [frequency, setFrequency] = useState<CryptoAcquisitionRequest['frequency']>('1h')
  const [period, setPeriod] = useState('2026-07')
  const [network, setNetwork] = useState('eth')
  const [poolAddress, setPoolAddress] = useState('')
  const [metrics, setMetrics] = useState('AdrActCnt,TxCnt,FeeTotNtv')
  const [start, setStart] = useState('2025-01-01T00:00:00Z')
  const [end, setEnd] = useState('2026-01-01T00:00:00Z')
  const [days, setDays] = useState(30)
  const [estimate, setEstimate] = useState<CryptoEstimate | null>(null)
  const [assetMasters, setAssetMasters] = useState<CryptoAssetMasters | null>(null)
  const [assetMaster, setAssetMaster] = useState<CryptoAssetMaster | null>(null)
  const [assetMasterVersion, setAssetMasterVersion] = useState('reviewed-native-v1')
  const [quality, setQuality] = useState<CryptoQuality | null>(null)
  const [features, setFeatures] = useState<CryptoFeatures | null>(null)
  const [featureName, setFeatureName] = useState<CryptoFeatureName>('funding')
  const [createdFeature, setCreatedFeature] = useState<CryptoFeature | null>(null)
  const [selected, setSelected] = useState<Set<string>>(() => new Set())
  const [jobId, setJobId] = useState<string | null>(null)
  const [jobFinished, setJobFinished] = useState(false)
  const [snapshot, setSnapshot] = useState<CryptoSnapshotCreate | null>(null)
  const [verification, setVerification] = useState<CryptoSnapshotVerify | null>(null)
  const [registration, setRegistration] = useState<CryptoSnapshotRegister | null>(null)
  const [storageInventory, setStorageInventory] = useState<CryptoStorageInventory | null>(null)
  const [storageVerification, setStorageVerification] = useState<CryptoStorageVerify | null>(null)
  const [cacheResult, setCacheResult] = useState<CryptoCacheClean | null>(null)
  const [cleanupArmed, setCleanupArmed] = useState(false)
  const [busyAction, setBusyAction] = useState<string | null>(null)

  const load = useCallback(async (refresh = false) => {
    if (refresh) setRefreshing(true)
    else setLoading(true)
    try {
      const [nextCatalog, nextCapabilities, nextAssetMasters, nextStorage, nextCoverage, nextFeatures] = await Promise.all([
        api.cryptoCatalog(),
        api.cryptoCapabilities(),
        api.cryptoAssetMasters(),
        api.cryptoStorage(),
        api.cryptoCoverage(),
        api.cryptoFeatures(),
      ])
      setCatalog(nextCatalog)
      setCapabilities(nextCapabilities)
      setAssetMasters(nextAssetMasters)
      setAssetMasterVersion((current) => {
        if (nextAssetMasters.items.some((item) => item.asset_master_version === current)) {
          return current
        }
        return nextAssetMasters.items.find((item) => item.contract_identity_count > 0)
          ?.asset_master_version ?? 'reviewed-native-v1'
      })
      setStorage(nextStorage)
      setCoverage(nextCoverage)
      setFeatures(nextFeatures)
      setSelected((current) => {
        const admitted = new Set(
          nextCoverage.items
            .filter((item) => item.state === 'qualified')
            .map((item) => item.manifest_id),
        )
        return new Set([...current].filter((id) => admitted.has(id)))
      })
      setError(null)
    } catch (reason: unknown) {
      setError(reason instanceof Error ? reason.message : String(reason))
    } finally {
      setLoading(false)
      setRefreshing(false)
    }
  }, [])

  useEffect(() => {
    void load()
  }, [load])

  const familyRows = useMemo(
    () => (catalog?.families ?? []).filter((row) => {
      const provider = acquisitionProvider(row.provider)
      return provider !== null && cryptoSectionForFamily(row.family) === section
    }),
    [catalog, section],
  )

  useEffect(() => {
    if (familyRows.length === 0 || familyRows.some((row) => row.family === family)) return
    const next = familyRows[0].family
    setFamily(next)
    setInstrument(defaultInstrument(next))
  }, [family, familyRows])

  useEffect(() => {
    setEstimate(null)
    setSnapshot(null)
    setVerification(null)
    setRegistration(null)
  }, [family, instrument, base, quote, category, frequency, days])

  const provider = acquisitionProvider(
    catalog?.families.find((row) => row.family === family)?.provider ?? '',
  )

  useEffect(() => {
    if (family === 'comparison_bars') {
      if (category !== 'spot') setCategory('spot')
      if (frequency !== '1d') setFrequency('1d')
      if (base !== 'BTC') setBase('BTC')
      if (quote !== 'USD') setQuote('USD')
      if (instrument !== 'BTC/USD') setInstrument('BTC/USD')
      return
    }
    const marketChoices = cryptoMarketChoicesForFamily(family)
    if (!marketChoices.includes(category)) setCategory(marketChoices[0])
    const supported = cryptoAcquisitionFrequencies(family, provider)
    if (!supported.includes(frequency)) setFrequency(supported.includes('1h') ? '1h' : supported[0])
  }, [base, category, family, frequency, instrument, quote, provider])

  useEffect(() => {
    if (!BYBIT_RANGED_FAMILIES.has(family)) return
    const recentEnd = new Date(Date.now() - 60 * 60 * 1000)
    recentEnd.setUTCMinutes(0, 0, 0)
    const recentStart = new Date(recentEnd.getTime() - 7 * 24 * 60 * 60 * 1000)
    setStart(recentStart.toISOString())
    setEnd(recentEnd.toISOString())
  }, [family])

  const capability = capabilities?.items.find((item) => item.family === family) ?? null
  const categoryChoices: CryptoAcquisitionRequest['category'][] =
    cryptoMarketChoicesForFamily(family)
  const frequencyChoices = cryptoAcquisitionFrequencies(family, provider)
  const qualifiedCount = coverage?.items.filter((item) => item.state === 'qualified').length ?? 0
  const action = cryptoCanonicalAction({
    loading,
    storageState: storage?.state,
    storageBlocker: storage?.blocker,
    qualifiedCount,
    selectedCount: selected.size,
  })
  const visibleCoverage = (coverage?.items ?? []).filter((item) => {
    if (section === 'quality' || section === 'storage') return true
    return cryptoSectionForFamily(item.family) === section
  })
  const latestManifestIds = latestCryptoManifestIds(visibleCoverage)
  const selectedBaseAssets = new Set(
    (coverage?.items ?? [])
      .filter((item) => selected.has(item.manifest_id) && item.base_asset)
      .map((item) => item.base_asset as string),
  )
  const featureInputSelection = useMemo(
    () => cryptoFeatureInputSelection(featureName, coverage?.items ?? [], selected),
    [coverage, featureName, selected],
  )

  async function deriveFeature(): Promise<void> {
    if (featureInputSelection.blocker) return
    setBusyAction('feature')
    setError(null)
    try {
      const created = await api.cryptoFeatureCreate({
        feature_name: featureName,
        inputs: featureInputSelection.inputs,
      })
      setCreatedFeature(created)
      setFeatures(await api.cryptoFeatures())
    } catch (reason: unknown) {
      setCreatedFeature(null)
      setError(reason instanceof Error ? reason.message : String(reason))
    } finally {
      setBusyAction(null)
    }
  }

  async function estimateAcquisition(): Promise<void> {
    if (frequency === 'catalog_snapshot') return
    setBusyAction('estimate')
    setError(null)
    try {
      setEstimate(await api.cryptoEstimate({ family, instruments: 1, days, frequency }))
    } catch (reason: unknown) {
      setEstimate(null)
      setError(reason instanceof Error ? reason.message : String(reason))
    } finally {
      setBusyAction(null)
    }
  }

  async function freezeAssetMaster(): Promise<void> {
    const latestFor = (target: CryptoFamily): CryptoCoverageItem[] => {
      const candidates = (coverage?.items ?? []).filter(
        (item) => item.family === target
          && item.state === 'qualified'
          && (target !== 'asset_metadata' || item.instrument === 'all'),
      )
      const latest = latestCryptoManifestIds(candidates)
      return candidates.filter((item) => latest.has(item.manifest_id))
    }
    const [coingecko] = latestFor('asset_metadata')
    const geckoterminal = latestFor('dex_pools')
    if (!coingecko || geckoterminal.length === 0) {
      setError('Acquire qualified CoinGecko asset metadata and a GeckoTerminal pool catalog first.')
      return
    }
    setBusyAction('asset-master')
    setError(null)
    try {
      const created = await api.cryptoAssetMasterCreate(
        coingecko.manifest_id,
        geckoterminal.map((item) => item.manifest_id),
      )
      setAssetMaster(created)
      setAssetMasterVersion(created.asset_master_version)
      await load(true)
    } catch (reason: unknown) {
      setError(reason instanceof Error ? reason.message : String(reason))
    } finally {
      setBusyAction(null)
    }
  }

  async function verifyAssetMaster(): Promise<void> {
    if (assetMasterVersion === 'reviewed-native-v1') return
    setBusyAction('asset-master-verify')
    setError(null)
    try {
      setAssetMaster(await api.cryptoAssetMasterVerify(assetMasterVersion))
    } catch (reason: unknown) {
      setAssetMaster(null)
      setError(reason instanceof Error ? reason.message : String(reason))
    } finally {
      setBusyAction(null)
    }
  }

  async function acquire(): Promise<void> {
    if (!provider) return
    setBusyAction('acquire')
    setError(null)
    try {
      const request: CryptoAcquisitionRequest = {
        provider,
        family,
        instrument,
        base,
        quote,
        category,
        frequency,
        period: provider === 'binance' && family !== 'book_snapshots' ? period : null,
        network: provider === 'geckoterminal' ? network : null,
        pool_address: provider === 'geckoterminal' && poolAddress ? poolAddress : null,
        metrics: provider === 'coinmetrics' && family === 'onchain_metrics'
          ? metrics.split(',').map((item) => item.trim()).filter(Boolean)
          : [],
        start: (provider === 'coinmetrics' && family === 'onchain_metrics') || provider === 'ccxt:coinbase' || (provider === 'bybit' && BYBIT_RANGED_FAMILIES.has(family)) ? start : null,
        end: (provider === 'coinmetrics' && family === 'onchain_metrics') || provider === 'ccxt:coinbase' || (provider === 'bybit' && BYBIT_RANGED_FAMILIES.has(family)) ? end : null,
      }
      const accepted = await api.cryptoAcquire(request)
      setJobId(accepted.job_id)
      setJobFinished(false)
    } catch (reason: unknown) {
      setError(reason instanceof Error ? reason.message : String(reason))
    } finally {
      setBusyAction(null)
    }
  }

  async function freezeSnapshot(): Promise<void> {
    setBusyAction('snapshot')
    setError(null)
    try {
      const created = await api.cryptoSnapshotCreate([...selected], assetMasterVersion)
      setSnapshot(created)
      setVerification(null)
    } catch (reason: unknown) {
      setError(reason instanceof Error ? reason.message : String(reason))
    } finally {
      setBusyAction(null)
    }
  }

  async function verifySnapshot(): Promise<void> {
    if (!snapshot) return
    setBusyAction('verify')
    setError(null)
    try {
      setVerification(await api.cryptoSnapshotVerify(snapshot.snapshot_id, {
        required_families: snapshot.families,
        purpose: 'research',
      }))
    } catch (reason: unknown) {
      setVerification(null)
      setError(reason instanceof Error ? reason.message : String(reason))
    } finally {
      setBusyAction(null)
    }
  }

  async function registerSnapshot(): Promise<void> {
    if (!snapshot || !verification?.eligible || selectedBaseAssets.size !== 1) return
    setBusyAction('register')
    setError(null)
    try {
      setRegistration(
        await api.cryptoSnapshotRegister(snapshot.snapshot_id, [...selectedBaseAssets][0]),
      )
      onRegistered?.()
    } catch (reason: unknown) {
      setRegistration(null)
      setError(reason instanceof Error ? reason.message : String(reason))
    } finally {
      setBusyAction(null)
    }
  }

  async function inspectQuality(item: CryptoCoverageItem): Promise<void> {
    setBusyAction(`quality:${item.manifest_id}`)
    setError(null)
    try {
      setQuality(await api.cryptoQuality(item.manifest_id))
      setSection('quality')
    } catch (reason: unknown) {
      setError(reason instanceof Error ? reason.message : String(reason))
    } finally {
      setBusyAction(null)
    }
  }

  async function inspectStorage(): Promise<void> {
    setBusyAction('storage-inventory')
    setError(null)
    try {
      setStorageInventory(await api.cryptoStorageInventory())
    } catch (reason: unknown) {
      setError(reason instanceof Error ? reason.message : String(reason))
    } finally {
      setBusyAction(null)
    }
  }

  async function verifyStorage(): Promise<void> {
    setBusyAction('storage-verify')
    setError(null)
    try {
      setStorageVerification(await api.cryptoStorageVerify())
    } catch (reason: unknown) {
      setStorageVerification(null)
      setError(reason instanceof Error ? reason.message : String(reason))
    } finally {
      setBusyAction(null)
    }
  }

  async function cleanCache(): Promise<void> {
    if (!cleanupArmed) {
      setCleanupArmed(true)
      return
    }
    setBusyAction('cache-clean')
    setError(null)
    try {
      setCacheResult(await api.cryptoCacheClean())
      setCleanupArmed(false)
      await load(true)
      await inspectStorage()
    } catch (reason: unknown) {
      setCacheResult(null)
      setError(reason instanceof Error ? reason.message : String(reason))
    } finally {
      setBusyAction(null)
    }
  }

  function toggleManifest(item: CryptoCoverageItem): void {
    if (item.state !== 'qualified') return
    setSelected((current) => {
      const next = new Set(current)
      if (next.has(item.manifest_id)) next.delete(item.manifest_id)
      else next.add(item.manifest_id)
      return next
    })
    setSnapshot(null)
    setVerification(null)
  }

  return (
    <section className="crypto-center" aria-label="Crypto Data Center">
      <div className="crypto-center-head">
        <div>
          <div className="title">Crypto Data Center</div>
          <p className="muted">Provider-native public data · exact units · no automatic fallback · no execution authority</p>
        </div>
        <button className="btn" type="button" disabled={refreshing} onClick={() => void load(true)}>
          {refreshing ? 'Refreshing…' : 'Refresh'}
        </button>
      </div>

      <div className={`crypto-next ${action.state}`} role="status">
        <span className="eyebrow">Canonical next action</span>
        <strong>{action.label}</strong>
      </div>
      {error ? <div className="workbench-notice" role="alert"><strong>ACTION BLOCKED</strong><span>{error}</span></div> : null}

      <nav className="crypto-tabs" role="tablist" aria-label="Crypto data families">
        {SECTIONS.map((item) => (
          <button
            key={item.id}
            type="button"
            role="tab"
            aria-selected={section === item.id}
            className={`area-tab${section === item.id ? ' active' : ''}`}
            onClick={() => setSection(item.id)}
          >
            {item.label}
          </button>
        ))}
      </nav>

      <CryptoAssetsView
        show={section === 'assets'}
        assetMasters={assetMasters}
        assetMaster={assetMaster}
        assetMasterVersion={assetMasterVersion}
        busyAction={busyAction}
        onAssetMasterVersionChange={(value) => {
          setAssetMasterVersion(value)
          setAssetMaster(null)
          setSnapshot(null)
          setVerification(null)
        }}
        onFreezeAssetMaster={() => void freezeAssetMaster()}
        onVerifyAssetMaster={() => void verifyAssetMaster()}
      />

      <CryptoAcquisitionView
        familyRows={familyRows}
        provider={provider}
        capability={capability}
        family={family}
        instrument={instrument}
        base={base}
        quote={quote}
        category={category}
        categoryChoices={categoryChoices}
        frequency={frequency}
        frequencyChoices={frequencyChoices}
        days={days}
        period={period}
        network={network}
        poolAddress={poolAddress}
        metrics={metrics}
        start={start}
        end={end}
        storageReady={storage?.state === 'ready'}
        estimate={estimate}
        busyAction={busyAction}
        rangedBybitFamily={BYBIT_RANGED_FAMILIES.has(family)}
        onFamilyChange={(next) => { setFamily(next); setInstrument(defaultInstrument(next)) }}
        onInstrumentChange={setInstrument}
        onBaseChange={setBase}
        onQuoteChange={setQuote}
        onCategoryChange={setCategory}
        onFrequencyChange={setFrequency}
        onDaysChange={setDays}
        onPeriodChange={setPeriod}
        onNetworkChange={setNetwork}
        onPoolAddressChange={setPoolAddress}
        onMetricsChange={setMetrics}
        onStartChange={setStart}
        onEndChange={setEnd}
        onEstimate={() => void estimateAcquisition()}
        onAcquire={() => void acquire()}
      />

      {jobId ? <section className="crypto-job"><div className="rd-head">Acquisition job</div><div className="workbench-notice" role="status"><strong>{jobFinished ? 'FINISHED' : 'RUNNING'}</strong><span>{jobFinished ? 'Coverage refreshed. Review the new mechanical qualification below.' : 'Fetching one bounded provider response and freezing its exact bytes.'}</span></div><div className="advanced-only"><JobConsole jobId={jobId} onDone={() => { setJobFinished(true); void load(true) }} /></div></section> : null}

      <CryptoCoverageView
        section={section}
        loading={loading}
        items={visibleCoverage}
        latestManifestIds={latestManifestIds}
        selectedManifestIds={selected}
        busyAction={busyAction}
        onToggle={toggleManifest}
        onInspectQuality={(item) => void inspectQuality(item)}
      />

      <CryptoQualityView
        quality={quality}
        showFeatures={section === 'quality'}
        features={features}
        featureName={featureName}
        featureInputSelection={featureInputSelection}
        createdFeature={createdFeature}
        busyAction={busyAction}
        onFeatureNameChange={(name) => {
          setFeatureName(name)
          setCreatedFeature(null)
        }}
        onDeriveFeature={() => void deriveFeature()}
      />

      <section className="crypto-snapshot provider-card" aria-label="Frozen crypto snapshot">
        <div className="provider-card-head"><div className="rd-head">Research snapshot</div><span className="chip kind">{selected.size} selected</span></div>
        <p className="muted">Only mechanically qualified datasets can be selected. Provider, venue, quote, units, timestamps, and hashes remain separate.</p>
        <p className="muted">Identity map: {(assetMasters?.items.find((item) => item.asset_master_version === assetMasterVersion)?.builtin ?? true) ? 'reviewed native assets' : 'exact contract identity map'}<span className="advanced-only mono"> · {assetMasterVersion}</span></p>
        <div className="crypto-actions">
          <button className="btn primary" type="button" disabled={selected.size === 0 || busyAction !== null} onClick={() => void freezeSnapshot()}>{busyAction === 'snapshot' ? 'Freezing…' : 'Freeze selected snapshot'}</button>
          {snapshot ? <button className="btn" type="button" disabled={busyAction !== null} onClick={() => void verifySnapshot()}>{busyAction === 'verify' ? 'Verifying…' : 'Verify for research'}</button> : null}
        </div>
        {snapshot ? <div className="crypto-detail"><strong>Frozen · {snapshot.member_count} members</strong><span>{snapshot.families.map((item) => item.replaceAll('_', ' ')).join(' · ')}</span><span className="mono muted advanced-only">snapshot {snapshot.snapshot_id}</span></div> : null}
        {verification ? <div className={`workbench-notice ${verification.eligible ? '' : 'fail'}`} role="status"><strong>{verification.eligible ? 'ELIGIBLE' : 'BLOCKED'}</strong><span>{verification.eligible ? 'Register this immutable snapshot for compatible research proposals.' : `${verification.next_action}${verification.blockers.length ? ` ${verification.blockers.join('; ')}` : ''}`}</span></div> : null}
        {verification?.eligible ? <div className="crypto-actions"><button className="btn primary" type="button" disabled={busyAction !== null || selectedBaseAssets.size !== 1 || registration !== null} onClick={() => void registerSnapshot()}>{busyAction === 'register' ? 'Registering…' : registration ? 'Registered for research' : 'Register research-only dataset'}</button>{selectedBaseAssets.size !== 1 ? <span className="muted">Select datasets for exactly one base asset before registration.</span> : null}</div> : null}
        {registration ? <div className="workbench-notice" role="status"><strong>REGISTERED · RESEARCH ONLY</strong><span>Available to compatible proposal operators; registration does not make an incompatible case executable.</span><span className="mono muted advanced-only">{registration.ref_id}</span></div> : null}
      </section>

      {section === 'storage' && storage ? (
        <>
        <section className="provider-card">
          <div className="rd-head">Storage</div>
          <div className="crypto-storage-stats"><span className={storage.state === 'ready' ? 'chip pass' : 'chip fail'}>{storage.state.toUpperCase()}</span><span>{fmtBytes(storage.free_bytes)} free of {fmtBytes(storage.total_bytes)}</span><span>{storage.manifest_count} immutable manifests</span><span>{fmtBytes(storage.cache_bytes)} removable cache</span><span>Reserve {storage.reserve_fraction == null ? '—' : `${Math.round(storage.reserve_fraction * 100)}%`} · minimum {fmtBytes(storage.minimum_free_bytes)}</span></div>
          <p className="muted">The browser receives only the volume label and capacity—not the private absolute path. Missing or substituted media fails closed.</p>
          <div className="crypto-actions"><button className="btn" type="button" disabled={busyAction !== null} onClick={() => void inspectStorage()}>{busyAction === 'storage-inventory' ? 'Inspecting…' : 'Inspect storage inventory'}</button><button className="btn" type="button" disabled={busyAction !== null} onClick={() => void verifyStorage()}>{busyAction === 'storage-verify' ? 'Verifying every artifact…' : 'Verify all immutable data'}</button><button className={cleanupArmed ? 'btn danger' : 'btn'} type="button" disabled={busyAction !== null || storage.cache_bytes === 0} onClick={() => void cleanCache()}>{busyAction === 'cache-clean' ? 'Cleaning cache…' : cleanupArmed ? 'Confirm clean removable cache' : 'Review cache cleanup'}</button></div>
          {cleanupArmed ? <div className="workbench-notice fail" role="alert"><strong>CONFIRM CACHE CLEANUP</strong><span>Only {fmtBytes(storage.cache_bytes)} under the disposable cache tree will be deleted. Raw, normalized, staged, snapshot, and control artifacts are excluded.</span></div> : null}
          {storageInventory ? <div className="crypto-detail"><strong>INVENTORY</strong><span>{storageInventory.manifest_count} manifests · {storageInventory.snapshot_count} snapshots · {storageInventory.staging_count} staged downloads</span><span>{fmtBytes(storageInventory.cache_bytes)} removable cache</span><span className="mono muted advanced-only">{JSON.stringify(storageInventory.counts_by_kind)}</span></div> : null}
          {storageVerification ? <div className="workbench-notice" role="status"><strong>VERIFIED</strong><span>{storageVerification.manifest_count} manifests and {storageVerification.snapshot_count} snapshots re-hashed · {storageVerification.research_eligible_snapshot_count} research eligible</span></div> : null}
          {cacheResult ? <div className="workbench-notice" role="status"><strong>CACHE CLEANED</strong><span>{fmtBytes(cacheResult.removed_bytes)} removed · immutable artifacts removed: 0</span></div> : null}
        </section>
        </>
      ) : null}
    </section>
  )
}
