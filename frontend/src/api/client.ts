import i18n from '../i18n'

/**
 * Talking to the server. Every changing request carries X-Requested-By, which the server demands so that a
 * foreign page cannot act on the signed-in session. Errors come back as ApiError with the server's code; the
 * interface turns the code into a sentence in the chosen language (errors.* in the language files).
 */

export class ApiError extends Error {
  status: number
  code: string
  details: Record<string, unknown>

  constructor(status: number, code: string, message: string, details: Record<string, unknown> = {}) {
    super(message)
    this.status = status
    this.code = code
    this.details = details
  }
}

async function request<T>(method: string, path: string, body?: unknown): Promise<T> {
  let response: Response
  try {
    response = await fetch(path, {
      method,
      credentials: 'same-origin',
      headers: {
        'X-Requested-By': 'nexsift',
        ...(body !== undefined ? { 'Content-Type': 'application/json' } : {}),
      },
      body: body !== undefined ? JSON.stringify(body) : undefined,
    })
  } catch {
    throw new ApiError(0, 'offline', 'The server cannot be reached.')
  }
  if (response.status === 204) return undefined as T
  const text = await response.text()
  let data: unknown
  try {
    data = text ? JSON.parse(text) : undefined
  } catch {
    data = undefined
  }
  if (!response.ok) {
    const detail = (data as { detail?: unknown } | undefined)?.detail
    if (detail && typeof detail === 'object') {
      const { code, message, ...rest } = detail as { code?: string; message?: string }
      throw new ApiError(response.status, code ?? 'error', message ?? response.statusText, rest)
    }
    throw new ApiError(response.status, response.status === 401 ? 'not_signed_in' : 'error', response.statusText)
  }
  return data as T
}

export const api = {
  get: <T>(path: string) => request<T>('GET', path),
  post: <T>(path: string, body?: unknown) => request<T>('POST', path, body ?? {}),
  put: <T>(path: string, body?: unknown) => request<T>('PUT', path, body ?? {}),
  delete: <T = void>(path: string) => request<T>('DELETE', path),
}

/**
 * The sentence for an error, in the chosen language. Known codes have a text in errors.*; an unknown code falls
 * back to the server's English message, which is better than nothing and still names the problem.
 */
export function errorMessage(error: unknown): string {
  if (error instanceof ApiError) {
    return i18n.t(`errors.${error.code}`, { ...error.details, defaultValue: error.message })
  }
  return i18n.t('errors.generic')
}
