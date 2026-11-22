import { postJSON } from './client'
import type { components } from './generated'

type Schema = components['schemas']
export type RuleExplanation = Schema['RuleEvaluationResponse']
export const edgeApi = {
  evaluate: (rules_id: string, symbol: string, as_of: string | null) => postJSON<RuleExplanation>('/api/rules/evaluate', { rules_id, symbol, as_of }),
}
