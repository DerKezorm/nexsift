/**
 * The sign-in providers on the server (`/api/oidc`, the shared sign-in module): the list for the operator, the own
 * links, the authentik button. Texts and codes come from `vendor/nexoidc/oidc.ts`.
 */
import { api } from './client'
import type { AuthentikAddress } from '../vendor/nexoidc/oidc'

/** One entry of the list as the operator sees it: never the secret, only whether one is stored. */
export interface OidcProvider {
  id: number
  slug: string
  label: string
  issuer: string
  client_id: string
  has_secret: boolean
  scopes: string
  enabled: boolean
  auto_create: boolean
  trusts_second_factor: boolean
  managed: string
  position: number
  redirect_uri: string
  /** What the authentik button registered at authentik last, '' for nothing; with `redirect_stale` the card says so. */
  registered_redirect_uri: string
  redirect_stale: boolean
  links: number
  editable: boolean
}

export interface OidcProviderForm {
  label: string
  slug?: string
  issuer: string
  client_id: string
  client_secret: string
  scopes: string
  enabled: boolean
  auto_create: boolean
  trusts_second_factor: boolean
}

export interface ProviderButton {
  slug: string
  label: string
}

/** What the sign-in page needs before anybody is signed in. */
export interface SignInState {
  password_login: boolean
  providers: ProviderButton[]
}

export interface MyProvider extends ProviderButton {
  linked: boolean
}

export interface AuthentikStep {
  key: string
  ok: boolean
  detail: string
  reason?: string
  status?: number
}

export interface AuthentikResult {
  ok: boolean
  steps: AuthentikStep[]
  client_id: string
  issuer: string
  provider_id: number | null
  links_dropped: number
  /** With `reason: issuer_change`: how many accounts would have to link again. */
  count?: number
  /** The run kept this public address (it stays saved even when a later step failed). */
  public_url?: string
  /** With `reason: public_url_needed`: what the card shows about the address. */
  address?: AuthentikAddress
}

export interface Impact {
  issuer_change: number
  count: number
  only: number
}

export const oidcApi = {
  state: () => api.get<SignInState>('/api/oidc/state'),
  providers: () => api.get<OidcProvider[]>('/api/oidc/admin/providers'),
  addProvider: (form: OidcProviderForm) => api.post<OidcProvider>('/api/oidc/admin/providers', form),
  saveProvider: (id: number, form: OidcProviderForm) => api.put<OidcProvider & { dropped: number }>(`/api/oidc/admin/providers/${id}`, form),
  removeProvider: (id: number) => api.delete<Impact>(`/api/oidc/admin/providers/${id}`),
  order: (ids: number[]) => api.put<ProviderButton[]>('/api/oidc/admin/providers/order', { ids }),
  impact: (id: number, issuer = '') =>
    api.get<Impact>(`/api/oidc/admin/providers/${id}/impact${issuer ? `?issuer=${encodeURIComponent(issuer)}` : ''}`),
  mine: () => api.get<MyProvider[]>('/api/oidc/me'),
  link: (slug: string, password: string) => api.post<{ url: string }>(`/api/oidc/${encodeURIComponent(slug)}/link`, { password }),
  unlink: (slug: string) => api.delete(`/api/oidc/${encodeURIComponent(slug)}/link`),
  authentik: (url: string, token: string, confirmIssuerChange = false, publicUrl = '') =>
    api.post<AuthentikResult>('/api/oidc/authentik/setup', {
      url,
      token,
      confirm_issuer_change: confirmIssuerChange,
      ...(publicUrl ? { public_url: publicUrl } : {}),
    }),
  address: () => api.get<AuthentikAddress>('/api/oidc/authentik/address'),
  /** "Use it only": saves the address; a changed one may be answered with the question (409 `public_url_change`). */
  saveAddress: (publicUrl: string, confirm = false) =>
    api.post<AuthentikAddress>('/api/oidc/authentik/address', { public_url: publicUrl, ...(confirm ? { confirm: true } : {}) }),
}

/** The start of a sign-in at a provider: a full page load, the server answers with the way to the provider. */
export function startAt(slug: string): void {
  window.location.assign(`/api/oidc/${encodeURIComponent(slug)}/start`)
}
