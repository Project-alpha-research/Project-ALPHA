// Words and rows for the Machine learning window. Every number is the stored one; a missing number
// is said to be missing, with its reason, and is never shown as zero.

import type { MlStoredFold, MlStoredRun } from '../api/types'

export const EMPTY_STATE_TEXT = 'No machine learning run is stored yet. To make the first one, ask your AI to run:'
export const FIRST_RUN_COMMAND = 'alpha ml run research/examples/ml-gbm-etfs.toml'

export const READ_ONLY_NOTE = 'This window only reads stored runs. It starts no training.'

/** A stored fraction as a percentage with a sign; null reads "not recorded". */
export function fraction(value: number | null | undefined): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return 'not recorded'
  const text = (value * 100).toFixed(1)
  return Number(text) === 0 ? '0.0%' : `${value < 0 ? '-' : '+'}${Math.abs(Number(text)).toFixed(1)}%`
}

function comparison(model: number | null, hold: number | null): string {
  if (model === null || hold === null) return 'compared with: not recorded'
  if (model > hold) return 'ahead of'
  if (model < hold) return 'behind'
  return 'level with'
}

/** The reading: stored numbers in context, after costs. No verdict, no advice. */
export function readingWords(run: MlStoredRun): string[] {
  const m = run.metrics
  const lines: string[] = []
  const hold = m.benchmark_total_return
  const days = run.n_oos_periods === null ? 'the tested periods' : `${run.n_oos_periods} tested periods`
  lines.push(
    hold === null || m.total_return === null
      ? `Over ${days}, after costs, the model returned ${fraction(m.total_return)}. Holding the same assets: ${fraction(hold)}.`
      : `Over ${days}, after costs, the model returned ${fraction(m.total_return)}, ${comparison(m.total_return, hold)} ${fraction(hold)} for holding the same assets.`,
  )
  lines.push(`Largest fall from a peak: ${fraction(m.max_drawdown)}.`)
  lines.push(m.sharpe === null ? `Sharpe: not worked out. ${m.sharpe_reason ?? ''}`.trim() : `Sharpe after costs: ${m.sharpe.toFixed(2)}.`)
  if (run.label) lines.push(run.label + '.')
  return lines
}

export interface FoldRow { fold: number; trained: string; tested: string }

export function foldRows(folds: readonly MlStoredFold[]): FoldRow[] {
  return folds.map(fold => ({
    fold: fold.fold,
    trained: `${fold.train_start} to ${fold.train_end}`,
    tested: `${fold.test_start} to ${fold.test_end}`,
  }))
}

export function runTitle(run: MlStoredRun): string {
  return `${run.assets.length} assets · ${run.model}`
}
