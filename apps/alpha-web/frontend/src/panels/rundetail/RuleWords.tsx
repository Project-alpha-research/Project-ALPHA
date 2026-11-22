import type { RuleTest } from '../../api/types'
import { labelChips, ruleWords } from '../ruleTestModel'

/** What was tested, in words: the owner rule's sentence, its family and each label with its plain meaning. */
export function RuleWords({ test }: { test: RuleTest }) {
  const words = ruleWords(test)
  if (!words) return null
  return (
    <section className="rule-words" aria-label="The rule in words">
      <p><strong>{words.sentence}</strong></p>
      {words.family && <p className="muted">Family: <code className="mono">{words.family}</code></p>}
      {test.labels.length > 0 && (
        <ul className="muted">
          {labelChips(test.labels).map((label) => (
            <li key={label.text}><code className="mono">{label.text}</code>: {label.title}</li>
          ))}
        </ul>
      )}
    </section>
  )
}
