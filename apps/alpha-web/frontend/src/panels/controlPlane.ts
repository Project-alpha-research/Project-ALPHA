import type { ProviderDefinition } from '../api/types'
import { validateDates } from './dataManagerModel'

export function historicalProviders(providers: ProviderDefinition[]): ProviderDefinition[] {
  return providers.filter(
    (provider) => provider.installed && provider.capabilities.includes('historical_bars'),
  )
}

export function providerOptionDefault(
  provider: ProviderDefinition | undefined,
  option: string,
): string | null {
  return provider?.options[option]?.default ?? null
}

interface PullArgs {
  symbol: string
  source: string
  start: string
  end: string
  exchange: string
}

/** The `alpha data pull` argv; throws the date problem the CLI would otherwise reject. */
export function buildDataPullArgs({ symbol, source, start, end, exchange }: PullArgs): string {
  const problem = validateDates(start, end)
  if (problem) throw new Error(problem)
  const venue = source === 'ccxt' ? ` --exchange ${exchange}` : ''
  return `${symbol.trim()} --source ${source}${venue} --start ${start} --end ${end}`
}
