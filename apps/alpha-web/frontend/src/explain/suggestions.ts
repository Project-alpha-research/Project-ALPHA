// Rule-based "what to learn / what to try next" recommendations, generated from a run's actual
// numbers. Deterministic and offline. Ordered by importance; the first 3–4 are the headline.

import { asStr, fmtNum, fmtPct } from '../util/format'
import type { Suggestion, ValidateManifest } from './types'

const str = (v: unknown): string => asStr(v) ?? ''

export function suggestions(m: ValidateManifest): Suggestion[] {
  const out: Suggestion[] = []
  const md = m.metadata ?? {}
  const symbol = str(md.symbol)
  const strategy = str(md.strategy_name)
  const t1 = m.nulls?.find((n) => n.tier === 'returns_level')
  const t2 = m.nulls?.find((n) => n.tier === 'full_engine')
  const t3 = m.nulls?.find((n) => n.tier === 'bar_permutation')
  const ci = m.cis?.find((c) => c.metric === 'sharpe')
  const nullGate = m.outcomes?.find((o) => o.name === 'randomized_price_null')
  const nOos = m.verdict?.detail?.sample_n_oos ?? null
  const ruin = m.oos_metrics?.risk_of_ruin ?? null
  const dd = m.oos_metrics?.max_drawdown ?? null
  const overlap = (m.forecast as { pretrain?: { overlap?: boolean } } | undefined)?.pretrain?.overlap

  // --- the luck test did not separate the strategy from random data ---
  if (nullGate && !nullGate.passed && !(t1?.flagged_low_fidelity && t2?.passed && t3?.passed !== false)) {
    out.push({
      title: 'The edge is indistinguishable from luck here — change something structural',
      why:
        `Random no-edge prices matched the strategy (T1 ${fmtPct(t1?.percentile ?? null, 0)}, ` +
        `T2 ${fmtPct(t2?.percentile ?? null, 0)}` +
        (t3 ? `, T3 ${fmtPct(t3.percentile, 0)}` : '') +
        ` percentile; the level used by the old grade was 95% in every tier). Parameter ` +
        `tweaks rarely change a luck-level result; a different signal family, holding period, or ` +
        `universe usually does. Single-name momentum often reads this way while a ` +
        `diversified basket of the same signal does not.`,
      action: symbol
        ? { command: 'backtest portfolio', args: `${symbol} SPY QQQ TLT GLD --strategy ${strategy || 'ts_momentum'}` }
        : undefined,
    })
  }

  if (t1?.flagged_low_fidelity) {
    out.push({
      title: 'Tier 1 is advisory here — trust Tier 2, but know why',
      why:
        `The fast surrogate fills at the close while the engine fills next open; on this run the ` +
        `two conventions diverge by ${fmtNum(t1.convention_divergence, 3)} Sharpe (more than the tolerance), ` +
        `so Tier 1 is advisory. The honest engine tiers held. High ` +
        `turnover amplifies this bias — a slower rebalance would shrink the divergence itself.`,
    })
  }

  // --- CI straddles zero / low sample ---
  const straddles =
    ci && typeof ci.lower === 'number' && typeof ci.upper === 'number' && ci.lower < 0 && ci.upper > 0
  if (straddles) {
    out.push({
      title: 'Sharpe interval straddles zero — buy statistical power, not parameters',
      why:
        `The ${fmtPct(ci.confidence, 0)} CI [${fmtNum(ci.lower)}, ${fmtNum(ci.upper)}] cannot ` +
        `rule out a zero edge. The cheapest fixes add data, not complexity: extend the history ` +
        `window, or validate the same signal on correlated symbols to see if the effect repeats.`,
      action: symbol
        ? { command: 'data pull', args: `${symbol} --source yfinance --start 2010-01-01` }
        : undefined,
    })
  }
  if (typeof nOos === 'number' && nOos > 0 && nOos < 500) {
    out.push({
      title: `Only ${fmtNum(nOos, 0)} OOS observations — extend the sample`,
      why:
        `Below ~500 observations every statistic here has wide error bars, and under 100 the reading ` +
        `is too little to read. Longer history, or smaller test windows with more folds, ` +
        `raises the count without touching the strategy.`,
    })
  }

  // --- risk tail ---
  if (typeof ruin === 'number' && ruin > 0.05) {
    out.push({
      title: `Risk of ruin ${fmtPct(ruin, 1)} — the tail can kill the account`,
      why:
        `More than 1-in-20 bootstrap re-orderings of these same returns lose half their peak. ` +
        `Lower the vol target, cap leverage, or add the --halt-drawdown kill-switch before ` +
        `sizing this up. A live allocator would ask for exactly that.`,
    })
  }
  if (typeof dd === 'number' && Math.abs(dd) > 0.35) {
    out.push({
      title: `Max drawdown ${fmtPct(Math.abs(dd), 0)} — beyond most mandates`,
      why:
        `Drawdowns past 35% are where compounding math turns against you ` +
        `(a 40% loss needs +67% back). Vol-target lower or diversify the book.`,
    })
  }

  // --- kronos leakage ---
  if (overlap) {
    out.push({
      title: 'Forecast window overlaps model pretraining — treat results as in-sample',
      why:
        `Part of this run predates the Kronos pretraining cutoff, so the model may have seen the ` +
        `answer. Re-run on a post-cutoff window (or read only the post-cutoff half of a forecast ` +
        `eval) before believing the skill.`,
    })
  }

  // --- every stored gate held: the constructive next steps ---
  if (m.passed) {
    out.push({
      title: 'The checks hold up here — now try to break it',
      why:
        `The single-config result is real by every test here. Next stresses, in order: a ` +
        `parameter sweep with overfitting controls (does the edge live on a plateau or a ` +
        `pinnacle?), a diversified portfolio of the signal, and a prop-firm Monte Carlo to see ` +
        `if the path survives real drawdown rules.`,
      action: symbol
        ? { command: 'optim grid', args: `${symbol} --strategy ${strategy || 'ts_momentum'} --grid lookback=126,189,252,315` }
        : undefined,
    })
  } else if (out.length === 0) {
    out.push({
      title: 'No single check explains a weak reading — read the five checks',
      why:
        `No one number explains it; read each check and how far it sits from the level used by ` +
        `the old grade. Small gaps across several checks usually mean a thin edge on a thin sample.`,
    })
  }

  return out
}
