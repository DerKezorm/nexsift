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
  // A form (an uploaded file) goes as it is; the browser sets its content type with the boundary.
  const form = body instanceof FormData
  let response: Response
  try {
    response = await fetch(path, {
      method,
      credentials: 'same-origin',
      headers: {
        'X-Requested-By': 'nexsift',
        ...(body !== undefined && !form ? { 'Content-Type': 'application/json' } : {}),
      },
      body: body === undefined ? undefined : form ? body : JSON.stringify(body),
    })
  } catch {
    throw new ApiError(0, 'offline', 'The server cannot be reached.')
  }
  if (response.status === 204) return undefined as T
  return (await read(response)) as T
}

async function read(response: Response): Promise<unknown> {
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
  return data
}

export const api = {
  get: <T>(path: string) => request<T>('GET', path),
  post: <T>(path: string, body?: unknown) => request<T>('POST', path, body ?? {}),
  put: <T>(path: string, body?: unknown) => request<T>('PUT', path, body ?? {}),
  delete: <T = void>(path: string) => request<T>('DELETE', path),
}

/**
 * Downloads a file and hands it to the browser to save. With a body it is a POST (the archive password travels
 * in the body, never in the address).
 */
export async function downloadFile(path: string, fallbackName: string, body?: unknown): Promise<void> {
  let response: Response
  try {
    response = await fetch(path, {
      method: body === undefined ? 'GET' : 'POST',
      credentials: 'same-origin',
      headers: body === undefined ? {} : { 'X-Requested-By': 'nexsift', 'Content-Type': 'application/json' },
      body: body === undefined ? undefined : JSON.stringify(body),
    })
  } catch {
    throw new ApiError(0, 'offline', 'The server cannot be reached.')
  }
  if (!response.ok) await read(response)
  const disposition = response.headers.get('content-disposition') ?? ''
  const match = /filename="?([^";]+)"?/.exec(disposition)
  const blob = await response.blob()
  const url = URL.createObjectURL(blob)
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = match?.[1] ?? fallbackName
  document.body.appendChild(anchor)
  anchor.click()
  anchor.remove()
  window.setTimeout(() => URL.revokeObjectURL(url), 1000)
}

/**
 * The sentence for an error, in the chosen language. Known codes have a text in errors.*; an unknown code falls
 * back to the server's English message, which is better than nothing and still names the problem.
 *
 * Every error answer carries the id of its request; it is added to the sentence, so the matching lines are found
 * under Settings, Log with one search.
 */
export function errorMessage(error: unknown): string {
  if (error instanceof ApiError) {
    const text = i18n.t(`errors.${error.code}`, { ...error.details, defaultValue: error.message })
    const id = error.details.request_id
    return typeof id === 'string' && /^[0-9a-f]{6}$/.test(id) ? `${text} ${i18n.t('errors.requestId', { id })}` : text
  }
  return i18n.t('errors.generic')
}
