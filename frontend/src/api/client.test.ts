import { beforeAll, describe, expect, it } from 'vitest'

import { changeLanguage, startI18n } from '../i18n'
import { ApiError, errorMessage } from './client'

beforeAll(async () => {
  await startI18n()
  await changeLanguage('en')
})

describe('errorMessage', () => {
  it('says the codes of sign-in through a provider in the shared words', () => {
    expect(errorMessage(new ApiError(409, 'oidc_only_account', 'english for the log'))).toBe(
      'This account signs in through this provider only. The last link stays.',
    )
    expect(errorMessage(new ApiError(429, 'too_many_attempts', 'x', { retry_after: 9 }))).toBe(
      'Too many attempts. Wait a moment, then try again.',
    )
    expect(errorMessage(new ApiError(422, 'slug_taken', 'x', { field: 'slug' }))).toBe('Another entry has this short name already.')
  })

  it("keeps nexsift's own codes", () => {
    expect(errorMessage(new ApiError(409, 'password_needed', 'x'))).toBe(
      'Link your account to an active provider first (Settings, Account); then the password can be switched off.',
    )
  })
})
