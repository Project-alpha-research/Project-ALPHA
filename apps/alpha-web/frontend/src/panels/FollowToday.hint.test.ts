import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { describe, expect, it } from 'vitest'

// The empty Followed today panel shows a hint naming the command that lists rule tests.
// `alpha results` (results_app, invoke_without_command=True) is that command;
// `alpha results list` does not exist.
const source = readFileSync(fileURLToPath(new URL('./FollowToday.tsx', import.meta.url)), 'utf8')

describe('FollowToday empty-panel hint', () => {
  it('the empty-panel hint still tells the owner how to find a run id', () => {
    expect(source).toContain('Find a run id with')
  })

  it('the empty-panel hint names the real command alpha results', () => {
    expect(source).toMatch(/Find a run id with:\s*<code[^>]*>\s*alpha results\s*<\/code>/)
  })

  it('the empty-panel hint never names the missing command alpha results list', () => {
    expect(source).not.toContain('alpha results list')
  })
})
