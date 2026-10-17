import { ApiError } from '../api/client'

/**
 * The question a changed public address asks: the server answers 409
 * `public_url_change` with these fields and saves nothing; only the same request with the confirmation saves.
 */
export interface AddressQuestion {
  /** Entries of the authentik button whose address at authentik the new one leaves behind. */
  count: number
  /** The redirect address authentik still knows (of the first of them). */
  address: string
  /** Active providers entered by hand whose redirect address changes with it. */
  hand: number
}

/** The question in an error of a save, or null for any other error. */
export function addressQuestion(caught: unknown): AddressQuestion | null {
  if (!(caught instanceof ApiError) || caught.code !== 'public_url_change') return null
  const { count, address, hand } = caught.details
  return { count: Number(count) || 0, address: typeof address === 'string' ? address : '', hand: Number(hand) || 0 }
}
