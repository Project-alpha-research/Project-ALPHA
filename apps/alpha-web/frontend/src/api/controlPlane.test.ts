import { afterEach, describe, expect, it, vi } from 'vitest'

import { api, clearImmutableApiCache } from './client'

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'content-type': 'application/json' },
  })
}

function apiError(message: string, status: number): Response {
  return jsonResponse(
    {
      schema_version: 1,
      code: status === 422 ? 'request_invalid' : 'service_unavailable',
      message,
      recovery_action: 'Retry after resolving the blocker.',
      field_errors: [],
      request_id: 'request-test',
    },
    status,
  )
}

afterEach(() => {
  clearImmutableApiCache()
  vi.unstubAllGlobals()
})

describe('control-plane API client', () => {
  it('reads the provider projection from its stable endpoint', async () => {
    const fetchMock = vi.fn().mockResolvedValueOnce(jsonResponse([]))
    vi.stubGlobal('fetch', fetchMock)

    await api.providers()

    expect(fetchMock).toHaveBeenNthCalledWith(1, '/api/providers')
  })

  it('cancels through the linked job endpoint with DELETE', async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse({ status: 'cancelled' }))
    vi.stubGlobal('fetch', fetchMock)

    const response = await api.cancel('job-7')

    expect(response.ok).toBe(true)
    expect(fetchMock).toHaveBeenCalledWith('/api/jobs/job-7', { method: 'DELETE' })
  })

  it('surfaces non-success responses for panel error states', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response('offline', { status: 503 })))

    await expect(api.providers()).rejects.toThrow('The Workstation server could not answer this request. Try again. If it keeps failing, restart the Workstation.')
  })

  it('reads as plain text when a panel prints the error, with no Error: prefix', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(apiError('The data store is not ready.', 422)))

    const failure = await api.providers().catch((cause: unknown) => cause)

    expect(String(failure)).toBe('The data store is not ready. Retry after resolving the blocker.')
  })

  it('uses bounded artifact endpoints for causal charts and native analytics', async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(jsonResponse({ trace_status: 'trace_unavailable' }))
      .mockResolvedValueOnce(jsonResponse({ available: false }))
    vi.stubGlobal('fetch', fetchMock)

    await api.chartBundle('0123456789abcdef', 5000)
    await api.nativeTearsheet('0123456789abcdef')

    expect(fetchMock).toHaveBeenNthCalledWith(
      1,
      '/api/runs/0123456789abcdef/chart-bundle?limit=5000',
    )
    expect(fetchMock).toHaveBeenNthCalledWith(
      2,
      '/api/runs/0123456789abcdef/native-tearsheet?point_limit=750',
    )
  })

  it('deduplicates immutable run projections and retries a rejected request', async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(jsonResponse({ run_id: 'run-cache' }))
      .mockResolvedValueOnce(apiError('temporary', 503))
      .mockResolvedValueOnce(jsonResponse({ run_id: 'run-retry' }))
    vi.stubGlobal('fetch', fetchMock)

    const [first, second] = await Promise.all([api.run('run-cache'), api.run('run-cache')])
    expect(first).toBe(second)
    expect(fetchMock).toHaveBeenCalledOnce()

    await expect(api.run('run-retry')).rejects.toThrow('temporary')
    await expect(api.run('run-retry')).resolves.toMatchObject({ run_id: 'run-retry' })
    expect(fetchMock).toHaveBeenCalledTimes(3)
  })

  it('extracts ApiErrorV1 messages without leaking JSON response framing', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(apiError('run has no equity stream', 422)))

    await expect(api.providers()).rejects.toThrow('run has no equity stream')
    await expect(api.providers()).rejects.not.toThrow('422')
    await expect(api.providers()).rejects.not.toThrow('{"message"')
  })

  it('turns typed 422 field errors into actionable labels', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(jsonResponse({
      schema_version: 1,
      code: 'request_invalid',
      message: 'The request fields are invalid.',
      recovery_action: 'Correct the named fields and retry.',
      field_errors: [{ field: 'dataset_ref_id', message: 'Select a qualified dataset.' }],
      request_id: 'request-fields',
    }, 422)))

    await expect(api.providers()).rejects.toThrow(
      'Fields: dataset_ref_id: Select a qualified dataset.',
    )
  })

  it('sends the linked date window with the causal chart bundle request', async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse({ trace_status: 'available' }))
    vi.stubGlobal('fetch', fetchMock)

    await api.chartBundle('0123456789abcdef', 2000, '2026-01-02', '2026-03-31')

    expect(fetchMock).toHaveBeenCalledWith(
      '/api/runs/0123456789abcdef/chart-bundle?limit=2000&start=2026-01-02&end=2026-03-31',
    )
  })

  it('reads worker capabilities without inferring readiness', async () => {
    const fetchMock = vi.fn().mockImplementation(() => Promise.resolve(jsonResponse({})))
    vi.stubGlobal('fetch', fetchMock)
    await api.mlCapabilities()
    expect(fetchMock).toHaveBeenCalledWith('/api/ml/capabilities')
  })

  it('reads a bounded Qlib diagnostic tear sheet without accepting an unbounded offset', async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse({ available: false }))
    vi.stubGlobal('fetch', fetchMock)

    await api.mlTearsheet('unsafe/id', 500)

    expect(fetchMock).toHaveBeenCalledWith(
      '/api/ml/exchanges/unsafe%2Fid/tear-sheet?feature_limit=50&timeline_limit=500&timeline_offset=500&history_limit=200',
    )
    expect(() => api.mlTearsheet('exchange', 1_000_001)).toThrow(RangeError)
    expect(fetchMock).toHaveBeenCalledOnce()
  })

  it('does not expose caller-asserted owner actions', () => {
    expect('sealHoldout' in api).toBe(false)
    expect('transitionExperimentStage' in api).toBe(false)
    expect('freezeDecision' in api).toBe(false)
  })
})
