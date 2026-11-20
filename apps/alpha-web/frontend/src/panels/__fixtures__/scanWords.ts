// One home for the owner-facing word scan. The project rule is to never promise or imply profit. It does not
// ban standard trading terms, so the scan looks for promise phrases, not the bare word "profit".
export const STANDARD_TERMS = ['Profit factor', 'P&L', 'realized profit', 'realized gain or loss', 'take-profit', 'profit target', 'profit split']
export const PROMISE = /(?:will profit|profitable|unprofitable|profitability|make money|guaranteed)/i
export const RESULT_WORDS = /\b(?:supported|rejected|inconclusive|pass|passed|fail|failed|verdict|grade|graded)\b/i
export const BANNED = new RegExp(`${RESULT_WORDS.source}|${PROMISE.source}`, 'i')
