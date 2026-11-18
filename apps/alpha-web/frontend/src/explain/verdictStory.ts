// Verdict stories: explain each A–F dimension against the exact band its number landed in.
// The persisted manifest verdict is authoritative — these narratives cite it; recomputeVerdict()
// exists only for the drift-guard tests and the band interval text.

import { fmtNum, fmtPct, isFiniteNum } from '../util/format'
import {
  bandInterval,
  DRAWDOWN_BANDS,
  EDGE_BANDS,
  OVERALL_BANDS,
  RUIN_BANDS,
  SAMPLE_BANDS,
  gradeAtMost,
  gradeAtLeast,
  GPA,
} from './bands'
import type { DimensionStory, Tone, ValidateManifest } from './types'

function toneFor(grade: string): Tone {
  if (grade === 'A' || grade === 'B') return 'good'
  if (grade === 'C') return 'warn'
  return 'bad'
}

// The run response already carries the full manifest, including spine/headline labels.
// Keep these optional for manifests recorded before the sparse-trade cap existed.
export type RecordedManifest = ValidateManifest & {
  labels?: readonly string[]
  spine?: { labels?: readonly string[] }
  n_trades?: number | null
  verdict?: ValidateManifest['verdict'] & { labels?: readonly string[] }
}

/** Explain the recorded walk-forward sample. The full-history trade count has a different basis. */
export function sparseTradeStory(m: RecordedManifest): string | null {
  const v = m.verdict
  if (![m.labels, m.spine?.labels, v?.labels].some(labels => labels?.includes('too-few-trades'))) return null
  const tradeCount = isFiniteNum(m.n_trades) ? `only ${fmtNum(m.n_trades, 0)}` : 'fewer than 30'
  const sample = `${tradeCount} closed trades, which is too few to judge.`
  // The saved overall GPA already includes the cap. Only explain a reduction with all four letters.
  const grades = v ? [v.edge, v.robustness, v.risk, v.sample] : []
  if (v?.overall && grades.every(grade => Object.hasOwn(GPA, grade))) {
    const dimensionGrade = gradeAtLeast(grades.reduce((sum, grade) => sum + GPA[grade], 0) / 4, OVERALL_BANDS)
    if (dimensionGrade === 'A' || dimensionGrade === 'B') {
      return `The dimensions alone would give ${dimensionGrade}, but the stored grade is held at ${v.overall} because this run has ${sample}`
    }
  }
  return `This run has ${sample}`
}

export function verdictStories(m: RecordedManifest): DimensionStory[] {
  const v = m.verdict
  if (!v) return []
  const d = v.detail ?? {}
  const sharpe = d.edge_sharpe ?? null
  const checks = d.robustness_checks_passed ?? null
  const dd = d.risk_max_drawdown ?? null
  const ruin = d.risk_of_ruin ?? null
  const nOos = d.sample_n_oos ?? null
  const gpa = d.overall_gpa ?? null

  const sparseStory = sparseTradeStory(m)

  const ddDepth = isFiniteNum(dd) ? Math.abs(dd) : null
  const ddGrade = gradeAtMost(ddDepth, DRAWDOWN_BANDS)
  const ruinGrade = gradeAtMost(ruin, RUIN_BANDS)
  const riskDriver =
    (v.risk === ddGrade && v.risk !== ruinGrade) ? 'drawdown' :
    (v.risk === ruinGrade && v.risk !== ddGrade) ? 'ruin' : 'both'

  return [
    {
      dimension: 'edge',
      grade: v.edge,
      terse: `Sharpe ${fmtNum(sharpe)} ∈ ${bandInterval(v.edge, EDGE_BANDS, 'atLeast')}`,
      narrative:
        `Edge = ${v.edge} because the OOS Sharpe ${fmtNum(sharpe)} falls in the ` +
        `${bandInterval(v.edge, EDGE_BANDS, 'atLeast')} band. This dimension only asks whether ` +
        `risk-adjusted return exists — the other three ask whether to believe it.`,
      tone: toneFor(v.edge),
    },
    {
      dimension: 'robustness',
      grade: v.robustness,
      terse: `${fmtNum(checks, 0)}/4 checks passed`,
      narrative:
        `Robustness = ${v.robustness}: ${fmtNum(checks, 0)} of the 4 statistical checks held ` +
        `(both null tiers, DSR, CPCV, CI-lower > 0). Note the verdict counts the null check ` +
        `strictly — an advisory "low-fidelity" Tier-1 demotion still counts as a miss here even ` +
        `when the gate itself was excused.`,
      tone: toneFor(v.robustness),
    },
    {
      dimension: 'risk',
      grade: v.risk,
      terse: `MaxDD ${fmtPct(ddDepth, 1)} · ruin ${fmtPct(ruin, 1)}`,
      narrative:
        `Risk = ${v.risk}, the WORSE of the drawdown band (|${fmtPct(ddDepth, 1)}| → ${ddGrade}, ` +
        `band ${bandInterval(ddGrade, DRAWDOWN_BANDS, 'atMost')}) and the ruin band ` +
        `(${fmtPct(ruin, 1)} → ${ruinGrade}, band ${bandInterval(ruinGrade, RUIN_BANDS, 'atMost')}). ` +
        (riskDriver === 'both'
          ? `Both tails bind equally here.`
          : `The binding constraint is ${riskDriver}.`),
      tone: toneFor(v.risk),
    },
    {
      dimension: 'sample',
      grade: v.sample,
      terse: `n=${fmtNum(nOos, 0)} OOS ∈ ${bandInterval(v.sample, SAMPLE_BANDS, 'atLeast')}`,
      narrative:
        `Sample = ${v.sample}: ${fmtNum(nOos, 0)} out-of-sample observations ` +
        `(band ${bandInterval(v.sample, SAMPLE_BANDS, 'atLeast')}). Every other number's error ` +
        `bars shrink with this count — a great Sharpe on a small sample is a hypothesis, ` +
        `not a result.`,
      tone: toneFor(v.sample),
    },
    {
      dimension: 'overall',
      grade: v.overall,
      terse: sparseStory ? `Stored ${v.overall} · too few trades` : `GPA ${fmtNum(gpa)} → ${v.overall}`,
      narrative:
        (sparseStory ? `Overall = ${v.overall}. ${sparseStory} ` :
          `Overall = ${v.overall}: the equal-weight GPA of the four dimensions is ${fmtNum(gpa)}, ` +
          `landing in the ${bandInterval(v.overall, OVERALL_BANDS, 'atLeast')} band. `) +
        `${m.passed ? 'All hard gates also passed.' : 'Independent of the letter, at least one hard gate FAILED — the run does not clear the gauntlet.'}`,
      tone: m.passed ? toneFor(v.overall) : 'bad',
    },
  ]
}
