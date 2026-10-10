import { describe, expect, it } from 'vitest'

import { ApiError } from '../api/client'
import { addressQuestion } from './addressQuestion'

describe('addressQuestion', () => {
  it('reads the question out of the 409 of a changed public address', () => {
    const asked = new ApiError(409, 'public_url_change', 'x', { count: 1, address: 'https://a.example/api/oidc/authentik/callback', hand: 2, entries: [] })
    expect(addressQuestion(asked)).toEqual({ count: 1, address: 'https://a.example/api/oidc/authentik/callback', hand: 2 })
  })

  it('takes a question that has only providers by hand', () => {
    expect(addressQuestion(new ApiError(409, 'public_url_change', 'x', { count: 0, hand: 1 }))).toEqual({ count: 0, address: '', hand: 1 })
  })

  it('is none for any other error', () => {
    expect(addressQuestion(new ApiError(422, 'public_url_invalid', 'x'))).toBeNull()
    expect(addressQuestion(new ApiError(409, 'password_needed', 'x'))).toBeNull()
    expect(addressQuestion(new Error('public_url_change'))).toBeNull()
    expect(addressQuestion(null)).toBeNull()
  })
})
