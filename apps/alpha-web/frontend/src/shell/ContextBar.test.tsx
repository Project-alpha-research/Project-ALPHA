import * as React from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { api } from '../api/client'
import { ContextBar } from './ContextBar'
import * as inventory from './projectContextModel'

vi.mock('react', async original => ({ ...await original<typeof import('react')>() }))
vi.mock('../context/linked', () => ({ useLinked: () => ({ projectId: null }), setLinked: vi.fn() }))
vi.mock('../state/settings', () => ({ useSettings: () => ({ profile: 'crypto' }) }))
vi.mock('../state/activity', () => ({ useAreaVersion: () => 0 }))
vi.mock('../context/storedQuotes', () => ({ useStoredVenues: () => ({}) }))
vi.mock('../panels/actions', () => ({ openArchiveMarket: vi.fn(), openStoredMarket: vi.fn(), openCryptoData: vi.fn() }))
vi.mock('../components/AssetSelect', () => ({ AssetSelect: () => null }))

const empty = { items: [], offset: 0, limit: 50, has_more: false }
afterEach(() => vi.restoreAllMocks())

// Exercise the actual loading effect and its rendered states in Node, without a browser.
function mount() {
  const effects: React.EffectCallback[] = []
  vi.spyOn(React, 'useEffect').mockImplementation(effect => { effects.push(effect) })
  vi.spyOn(React, 'useRef').mockReturnValue({ current: null })
  const state = vi.spyOn(React, 'useState')
  let projects: inventory.ProjectChoice[] = []
  let error: string | null = null
  let loading = false
  const setProjects = vi.fn(value => { projects = value })
  const setError = vi.fn(value => { error = value })
  const setLoading = vi.fn(value => { loading = value })
  const render = () => {
    state.mockReturnValueOnce([false, vi.fn()]).mockReturnValueOnce([projects, setProjects])
      .mockReturnValueOnce([error, setError]).mockReturnValueOnce([loading, setLoading])
      .mockReturnValueOnce([0, vi.fn()])
    return renderToStaticMarkup(<ContextBar />)
  }
  render()
  const dispose = effects[0]()
  return { render, dispose, setProjects, setError, setLoading }
}

describe('project inventory loading', () => {
  it('settles an empty inventory without leaving loading text', async () => {
    vi.spyOn(api, 'projects').mockResolvedValue(empty)
    vi.spyOn(api, 'researchCases').mockResolvedValue(empty)
    const view = mount()
    expect(view.render()).toContain('Loading projects…')
    await vi.waitFor(() => expect(view.setLoading).toHaveBeenLastCalledWith(false))
    expect(view.render()).not.toContain('Loading projects…')
    expect(view.render()).not.toContain('Project inventory failed')
  })

  it('shows the existing failure button and settles loading after a rejected request', async () => {
    vi.spyOn(api, 'projects').mockRejectedValue(new Error('Inventory unavailable'))
    vi.spyOn(api, 'researchCases').mockResolvedValue(empty)
    const view = mount()
    await vi.waitFor(() => expect(view.setLoading).toHaveBeenLastCalledWith(false))
    expect(view.render()).toContain('Project inventory failed')
    expect(view.render()).toContain('Inventory unavailable')
    expect(view.render()).not.toContain('Loading projects…')
  })

  it('reports a projection failure instead of leaving loading stuck', async () => {
    vi.spyOn(api, 'projects').mockResolvedValue(empty)
    vi.spyOn(api, 'researchCases').mockResolvedValue(empty)
    vi.spyOn(inventory, 'projectChoices').mockImplementation(() => { throw new Error('Invalid project inventory') })
    const view = mount()
    await vi.waitFor(() => expect(view.setLoading).toHaveBeenLastCalledWith(false))
    expect(view.render()).toContain('Project inventory failed')
    expect(view.render()).toContain('Invalid project inventory')
    expect(view.render()).not.toContain('Loading projects…')
  })

  it('does not update a disposed request', async () => {
    let resolve!: (page: typeof empty) => void
    vi.spyOn(api, 'projects').mockReturnValue(new Promise(done => { resolve = done }))
    vi.spyOn(api, 'researchCases').mockResolvedValue(empty)
    const view = mount()
    if (typeof view.dispose === 'function') view.dispose()
    resolve(empty)
    await new Promise(done => setTimeout(done, 0))
    expect(view.setProjects).toHaveBeenCalledTimes(1)
    expect(view.setError).toHaveBeenCalledTimes(1)
    expect(view.setLoading).toHaveBeenCalledTimes(1)
  })
})
