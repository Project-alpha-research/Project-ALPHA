import { api } from '../api/client'
import { describe, expect, it, vi } from 'vitest'

import {
  authenticationRequestOptions,
  performOwnerAction,
  contentAddressHash,
  registrationCreationOptions,
} from './ownerAuth'

function bytes(value: BufferSource): number[] {
  if (value instanceof ArrayBuffer) return [...new Uint8Array(value)]
  return [...new Uint8Array(value.buffer, value.byteOffset, value.byteLength)]
}

describe('owner WebAuthn contract', () => {
  it('decodes every browser binary input from base64url', () => {
    const creation = registrationCreationOptions({
      challenge: 'AQID',
      rp: { id: 'localhost', name: 'Project ALPHA' },
      user: { id: 'BAUG', name: 'owner', displayName: 'owner' },
      pubKeyCredParams: [{ type: 'public-key', alg: -7 }],
      excludeCredentials: [{ type: 'public-key', id: 'BwgJ' }],
    })
    expect(bytes(creation.challenge)).toEqual([1, 2, 3])
    expect(bytes(creation.user.id)).toEqual([4, 5, 6])
    expect(bytes(creation.excludeCredentials?.[0]?.id ?? new Uint8Array())).toEqual([7, 8, 9])

    const request = authenticationRequestOptions({
      challenge: 'Cg_t',
      rpId: 'localhost',
      allowCredentials: [{ type: 'public-key', id: 'EBES' }],
    })
    expect(bytes(request.challenge)).toEqual([10, 15, 237])
    expect(bytes(request.allowCredentials?.[0]?.id ?? new Uint8Array())).toEqual([16, 17, 18])
  })

  it('accepts only the digest portion of a content-addressed artifact', () => {
    expect(contentAddressHash(`rc_${'b'.repeat(64)}`)).toBe('b'.repeat(64))
    expect(() => contentAddressHash('legacy-contract')).toThrow(/content-addressed/u)
  })
})


describe('local action confirmation', () => {
  it.each([true, false])('only performs when confirmation is %s', async accepted => {
    const request = { action_type: 'launch_d1' as const, project_id: 'project', artifact_hash: 'a'.repeat(64), expected_case_revision: 'b'.repeat(64), consequence_summary: 'Launch D1', reason: 'Reviewed', payload: {} }
    const confirm = vi.fn(() => accepted)
    vi.stubGlobal('window', { confirm })
    const challenge = vi.spyOn(api, 'ownerLocalChallenge').mockResolvedValue({ challenge_id: 'id', confirmation_token: 'c'.repeat(64), binding: request })
    const perform = vi.spyOn(api, 'ownerLocalPerform').mockResolvedValue({ authorization: {}, result: {} })
    try {
      if (accepted) {
        await performOwnerAction(request)
        expect(perform).toHaveBeenCalledWith('id', 'c'.repeat(64), {})
      } else {
        await expect(performOwnerAction(request)).rejects.toThrow('cancelled')
        expect(perform).not.toHaveBeenCalled()
      }
      expect(challenge).toHaveBeenCalledWith(request)
      expect(confirm).toHaveBeenCalledWith(expect.stringContaining('Launch D1'))
    } finally { vi.restoreAllMocks(); vi.unstubAllGlobals() }
  })
})
