import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, beforeAll, describe, expect, it, vi } from 'vitest'

import { changeLanguage, startI18n } from '../i18n'
import { AddressChangeQuestion } from './AddressChange'

beforeAll(async () => {
  await startI18n()
  await changeLanguage('en')
})
afterEach(cleanup)

const REDIRECT = 'https://old.example.org/api/oidc/authentik/callback'

describe('the question a changed public address asks', () => {
  it('names the redirect address authentik still knows, for the entry of the button', () => {
    render(<AddressChangeQuestion question={{ count: 1, address: REDIRECT, hand: 0 }} onCancel={() => undefined} onConfirm={() => undefined} />)
    expect(screen.getByText((text) => text.startsWith(`authentik still knows the redirect address ${REDIRECT}.`))).toBeTruthy()
    expect(screen.queryByText(/entered by hand/)).toBeNull()
  })

  it('says only the hand sentence, with the number, when the button made no entry', () => {
    render(<AddressChangeQuestion question={{ count: 0, address: '', hand: 2 }} onCancel={() => undefined} onConfirm={() => undefined} />)
    expect(screen.getByText('For 2 providers entered by hand, change the redirect address there yourself.')).toBeTruthy()
    expect(screen.queryByText(/authentik still knows/)).toBeNull()
  })

  it('says both when both are so, and the singular for one', () => {
    render(<AddressChangeQuestion question={{ count: 1, address: REDIRECT, hand: 1 }} onCancel={() => undefined} onConfirm={() => undefined} />)
    expect(screen.getByText(/authentik still knows the redirect address/)).toBeTruthy()
    expect(screen.getByText('For 1 provider entered by hand, change the redirect address there yourself.')).toBeTruthy()
  })

  it('confirms only with Save, and Cancel leaves everything as it is', () => {
    const confirm = vi.fn()
    const cancel = vi.fn()
    render(<AddressChangeQuestion question={{ count: 1, address: REDIRECT, hand: 0 }} onCancel={cancel} onConfirm={confirm} />)
    fireEvent.click(screen.getByRole('button', { name: 'Cancel' }))
    expect(cancel).toHaveBeenCalledTimes(1)
    expect(confirm).not.toHaveBeenCalled()
    fireEvent.click(screen.getByRole('button', { name: 'Save' }))
    expect(confirm).toHaveBeenCalledTimes(1)
  })
})
