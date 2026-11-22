import type {
  CryptoAssetMaster,
  CryptoAssetMasters,
} from '../api/types'

type CryptoAssetsViewProps = {
  show: boolean
  assetMasters: CryptoAssetMasters | null
  assetMaster: CryptoAssetMaster | null
  assetMasterVersion: string
  busyAction: string | null
  onAssetMasterVersionChange: (value: string) => void
  onFreezeAssetMaster: () => void
  onVerifyAssetMaster: () => void
}

export function CryptoAssetsView({
  show,
  assetMasters,
  assetMaster,
  assetMasterVersion,
  busyAction,
  onAssetMasterVersionChange,
  onFreezeAssetMaster,
  onVerifyAssetMaster,
}: CryptoAssetsViewProps) {
  if (!show) return null

  return (
    <div className="crypto-card-grid">
      <section className="provider-card" aria-label="Frozen asset master">
        <div className="rd-head">Exact contract identity map</div>
        <p className="muted">Contract assets are joined only when CoinGecko and GeckoTerminal agree on the exact network and contract address.</p>
        <div className="crypto-form-grid">
          <label>
            <span className="eyebrow">Identity map</span>
            <select
              className="field"
              value={assetMasterVersion}
              onChange={(event) => onAssetMasterVersionChange(event.target.value)}
            >
              {(assetMasters?.items ?? []).map((item) => (
                <option key={item.asset_master_version} value={item.asset_master_version}>
                  {item.builtin
                    ? 'Reviewed native assets (BTC and ETH)'
                    : `${item.contract_identity_count} contract mappings · ${item.identity_count} total assets`}
                </option>
              ))}
            </select>
          </label>
          <button className="btn" type="button" disabled={busyAction !== null} onClick={onFreezeAssetMaster}>
            {busyAction === 'asset-master' ? 'Building…' : 'Build from latest qualified catalogs'}
          </button>
          {assetMasterVersion !== 'reviewed-native-v1' ? (
            <button className="btn" type="button" disabled={busyAction !== null} onClick={onVerifyAssetMaster}>
              {busyAction === 'asset-master-verify' ? 'Verifying…' : 'Verify identity map'}
            </button>
          ) : null}
        </div>
        {assetMaster ? (
          <div className="crypto-detail" role="status">
            <strong>{assetMaster.state.toUpperCase()} · {assetMaster.contract_identity_count} contract mappings</strong>
            <span>Ticker-only joins: prohibited</span>
            <span className="mono muted advanced-only">asset master {assetMaster.asset_master_version}</span>
          </div>
        ) : null}
        {assetMasterVersion === 'reviewed-native-v1' ? <p className="muted">Acquire qualified CoinGecko asset metadata and a GeckoTerminal pool catalog, then build a contract identity map.</p> : null}
      </section>
    </div>
  )
}
