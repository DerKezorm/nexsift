/**
 * Settings, Sign-in: three cards one below the other, as the shared sign-in module lays them out for every nex
 * app. Order, wording and behaviour come from there; the parts (section, switch, field, button, dialog)
 * are nexsift's own.
 *
 * 1. Sign-in: password sign-in (locked on while the account has no linked, active provider), the public address.
 * 2. Sign-in providers: the list with its marks, the drag handle, and the form as a dialog.
 * 3. authentik in one step: address, token, "Set up", the blueprint, and the steps with the reason of a failure.
 *
 * nexsift has one account: the form has no "New people get an account", and no second factor of its
 * own, so no "The provider checks the second factor itself" either. The way back with the password off is
 * nexsift's command in the container, named at the switch.
 */
import { useCallback, useEffect, useState, type ChangeEvent, type FormEvent } from 'react'
import { useTranslation } from 'react-i18next'

import { api, ApiError, errorMessage } from '../../api/client'
import { oidcApi, type AuthentikResult, type OidcProvider, type OidcProviderForm } from '../../api/oidc'
import type { Settings } from '../../api/types'
import { useAuth } from '../../auth'
import { AddressChangeQuestion } from '../../components/AddressChange'
import { CopyField } from '../../components/CopyField'
import { Dialog } from '../../components/Dialog'
import { useNotice } from '../../components/Notice'
import { Symbol } from '../../components/Symbol'
import { Badge, Banner, Button, Field, Section, Switch } from '../../components/ui'
import { addressQuestion, type AddressQuestion } from '../../lib/addressQuestion'
import {
  authentikIssuerChange,
  authentikProposal,
  authentikProxyWarning,
  authentikReasonKey,
  authentikRedirect,
  authentikStale,
  authentikStepKey,
  oidcErrorKey,
  oidcFormErrorKey,
  slugFromLabel,
  type AuthentikAddress,
} from '../../vendor/nexoidc/oidc'

/** The whole tab: the list is loaded once and shared, the button changes it too. */
export function SignInPart({ settings, onSaved }: { settings: Settings; onSaved: (settings: Settings) => void }) {
  const [providers, setProviders] = useState<OidcProvider[] | null>(null)
  const load = useCallback(async () => {
    try {
      setProviders(await oidcApi.providers())
    } catch {
      setProviders([])
    }
  }, [])
  useEffect(() => {
    void load()
  }, [load])
  // The authentik card can save the public address too ("Use it and set up", "Use it only"): card 1 shows it then.
  const reloadSettings = useCallback(async () => {
    onSaved(await api.get<Settings>('/api/settings'))
  }, [onSaved])
  return (
    <div className="flex flex-col gap-6">
      <SignInCard settings={settings} onSaved={onSaved} providers={providers} />
      <ProvidersCard providers={providers} reload={load} publicUrl={settings.public_url} />
      <AuthentikCard publicUrl={settings.public_url} reload={load} reloadSettings={reloadSettings} />
    </div>
  )
}

// --- Card 1: sign-in -------------------------------------------------------------------------------------------------

function SignInCard({ settings, onSaved, providers }: { settings: Settings; onSaved: (settings: Settings) => void; providers: OidcProvider[] | null }) {
  const { t } = useTranslation()
  const notify = useNotice()
  const { account, refresh } = useAuth()
  const [address, setAddress] = useState(settings.public_url)
  const [error, setError] = useState<string | null>(null)
  // A changed public address may leave authentik knowing the old redirect address: the server asks first (409).
  const [asked, setAsked] = useState<{ values: Partial<Settings>; question: AddressQuestion } | null>(null)
  const linked = !!account?.oidc_linked && (providers ?? []).some((entry) => entry.enabled && entry.links > 0)

  useEffect(() => {
    setAddress(settings.public_url)
  }, [settings.public_url])

  async function save(values: Partial<Settings>, confirmed = false) {
    setError(null)
    try {
      const saved = await api.put<Settings>('/api/settings', { values, ...(confirmed ? { confirm_public_url: true } : {}) })
      setAsked(null)
      onSaved(saved)
      setAddress(saved.public_url)
      notify({ text: t('common.saved') })
      await refresh()
    } catch (caught) {
      const question = addressQuestion(caught)
      if (question) setAsked({ values, question })
      else setError(errorMessage(caught))
    }
  }

  return (
    <div id="sign-in">
      <Section title={t('oidc.admin.signInTitle')}>
        <Switch
          label={t('oidc.admin.password')}
          hint={
            linked || !settings.password_login ? (
              <>
                {t('oidc.admin.passwordHint')}
                <code className="mt-1 block font-mono break-all text-mist-400">docker exec -it nexsift python -m app.reset_password</code>
              </>
            ) : (
              t('settings.signin.needsLink')
            )
          }
          checked={settings.password_login}
          // Without a provider that brings the account in, nobody could come in: the switch stays on.
          disabled={settings.password_login && !linked}
          onChange={(value) => void save({ password_login: value })}
        />
        <form
          className="flex flex-wrap items-end gap-2"
          onSubmit={(event) => {
            event.preventDefault()
            void save({ public_url: address })
          }}
        >
          <div className="min-w-60 flex-1">
            <Field
              label={t('oidc.admin.address')}
              value={address}
              onChange={(event: ChangeEvent<HTMLInputElement>) => setAddress(event.target.value)}
              placeholder="https://nexsift.example.com"
              hint={t('oidc.admin.addressHint')}
            />
          </div>
          <Button type="submit" variant="ghost" disabled={address === settings.public_url} className="mb-6">
            {t('common.save')}
          </Button>
        </form>
        {asked && (
          <AddressChangeQuestion
            question={asked.question}
            onCancel={() => {
              setAsked(null)
              setAddress(settings.public_url)
            }}
            onConfirm={() => void save(asked.values, true)}
          />
        )}
        {error && <Banner tone="bad">{error}</Banner>}
      </Section>
    </div>
  )
}

// --- Card 2: the provider list ---------------------------------------------------------------------------------------

/** The same issuer, however written at the end (the server's `same_issuer` for an issuer without a placeholder). */
function sameIssuer(a: string, b: string): boolean {
  return a.trim().replace(/\/+$/, '') === b.trim().replace(/\/+$/, '')
}

function ProvidersCard({ providers, reload, publicUrl }: { providers: OidcProvider[] | null; reload: () => Promise<void>; publicUrl: string }) {
  const { t } = useTranslation()
  const { refresh } = useAuth()
  const [editing, setEditing] = useState<OidcProvider | 'new' | null>(null)
  const [removing, setRemoving] = useState<{ entry: OidcProvider; count: number; only: number } | null>(null)
  const [dragged, setDragged] = useState<number | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const list = providers ?? []
  const readOnly = list.some((entry) => !entry.editable)

  async function act(work: () => Promise<void>) {
    setBusy(true)
    setError(null)
    try {
      await work()
    } catch (caught) {
      setError(errorMessage(caught))
    } finally {
      setBusy(false)
    }
  }

  const move = (from: number, to: number) => {
    if (from === to || to < 0 || to >= list.length) return
    const ids = list.map((entry) => entry.id)
    const [taken] = ids.splice(from, 1)
    ids.splice(to, 0, taken)
    void act(async () => {
      await oidcApi.order(ids)
      await reload()
    })
  }

  return (
    <div id="sign-in-providers">
      <Section title={t('oidc.admin.providersTitle')} intro={t('oidc.admin.providersText')}>
        {providers !== null && list.length === 0 && <p className="text-sm text-mist-400">{t('oidc.admin.empty')}</p>}
        {list.length > 0 && (
          <ul className="divide-y divide-ink-700 rounded-xl border border-ink-700" data-testid="provider-list">
            {list.map((entry, index) => (
              <li
                key={entry.id}
                className={'flex flex-wrap items-center gap-2 px-3 py-3 text-sm ' + (dragged === index ? 'opacity-50' : '')}
                draggable={!readOnly && list.length > 1}
                onDragStart={() => setDragged(index)}
                onDragEnd={() => setDragged(null)}
                onDragOver={(event) => event.preventDefault()}
                onDrop={(event) => {
                  event.preventDefault()
                  if (dragged !== null) move(dragged, index)
                  setDragged(null)
                }}
              >
                {!readOnly && list.length > 1 && (
                  <button
                    type="button"
                    className="cursor-grab rounded p-1 text-mist-500 hover:text-mist-200"
                    aria-label={t('settings.providers.order', { name: entry.label })}
                    title={t('settings.providers.order', { name: entry.label })}
                    onKeyDown={(event) => {
                      if (event.key === 'ArrowUp') move(index, index - 1)
                      if (event.key === 'ArrowDown') move(index, index + 1)
                    }}
                  >
                    <Symbol name="grip" className="h-4 w-4" />
                  </button>
                )}
                <span className="min-w-0 flex-1 basis-56">
                  <span className="block truncate font-medium text-mist-100">{entry.label}</span>
                  <span className="block truncate text-xs text-mist-500">{entry.issuer}</span>
                </span>
                <span className="flex flex-wrap items-center gap-1.5">
                  <Badge tone={entry.enabled ? 'ok' : 'neutral'}>{entry.enabled ? t('oidc.admin.active') : t('oidc.admin.inactive')}</Badge>
                  {entry.managed === 'authentik' && <Badge tone="accent">{t('oidc.admin.managed')}</Badge>}
                </span>
                {entry.editable && (
                  <span className="flex gap-1.5">
                    <Button variant="ghost" size="sm" onClick={() => setEditing(entry)}>
                      {t('oidc.admin.edit')}
                    </Button>
                    <Button
                      variant="danger"
                      size="sm"
                      loading={busy}
                      onClick={() =>
                        void act(async () => {
                          const impact = await oidcApi.impact(entry.id)
                          setRemoving({ entry, count: impact.count, only: impact.only })
                        })
                      }
                    >
                      {t('oidc.admin.remove')}
                    </Button>
                  </span>
                )}
              </li>
            ))}
          </ul>
        )}
        {!readOnly && (
          <div>
            <Button onClick={() => setEditing('new')}>
              <Symbol name="plus" />
              {t('oidc.admin.add')}
            </Button>
          </div>
        )}
        {error && <Banner tone="bad">{error}</Banner>}
      </Section>
      {editing !== null && (
        <ProviderDialog
          entry={editing === 'new' ? null : editing}
          publicUrl={publicUrl}
          onClose={() => setEditing(null)}
          onSaved={async () => {
            setEditing(null)
            await reload()
            await refresh()
          }}
        />
      )}
      {removing && (
        <Dialog title={t('oidc.admin.remove')} onClose={() => setRemoving(null)}>
          <p className="text-sm text-mist-300">{t('oidc.admin.removeConfirm', { name: removing.entry.label, count: removing.count, only: removing.only })}</p>
          <div className="mt-6 flex justify-end gap-2">
            <Button variant="ghost" onClick={() => setRemoving(null)}>
              {t('settings.providers.cancel')}
            </Button>
            <Button
              variant="danger"
              loading={busy}
              onClick={() =>
                void act(async () => {
                  await oidcApi.removeProvider(removing.entry.id)
                  setRemoving(null)
                  await reload()
                  await refresh()
                })
              }
            >
              {t('oidc.admin.remove')}
            </Button>
          </div>
        </Dialog>
      )}
    </div>
  )
}

const EMPTY: OidcProviderForm = {
  label: '',
  slug: '',
  issuer: '',
  client_id: '',
  client_secret: '',
  scopes: 'openid profile email',
  enabled: true,
  auto_create: false,
  trusts_second_factor: true,
}

type FieldName = 'label' | 'slug' | 'issuer' | 'client_id' | 'client_secret' | 'scopes' | 'id'

/** The provider form as a dialog, fields in the shared order (without the two switches nexsift has no use for). */
function ProviderDialog({ entry, publicUrl, onClose, onSaved }: { entry: OidcProvider | null; publicUrl: string; onClose: () => void; onSaved: () => Promise<void> }) {
  const { t } = useTranslation()
  const [form, setForm] = useState<OidcProviderForm>(
    entry
      ? {
          label: entry.label,
          issuer: entry.issuer,
          client_id: entry.client_id,
          client_secret: '',
          scopes: entry.scopes,
          enabled: entry.enabled,
          auto_create: false,
          trusts_second_factor: entry.trusts_second_factor,
        }
      : EMPTY,
  )
  // The short name follows the name on the button until it is typed itself.
  const [slugTyped, setSlugTyped] = useState(false)
  const [more, setMore] = useState(false)
  const [busy, setBusy] = useState(false)
  const [fieldError, setFieldError] = useState<{ field: FieldName; text: string } | null>(null)
  const [confirmIssuer, setConfirmIssuer] = useState<number | null>(null)

  const slug = entry ? entry.slug : slugTyped ? (form.slug ?? '') : slugFromLabel(form.label)
  const base = (publicUrl || window.location.origin).replace(/\/+$/, '')
  const redirect = entry ? entry.redirect_uri : `${base}/api/oidc/${slug || '…'}/callback`

  const set = (change: Partial<OidcProviderForm>) => setForm((current) => ({ ...current, ...change }))

  const errorFor = (caught: unknown): { field: FieldName; text: string } => {
    if (!(caught instanceof ApiError)) return { field: 'id', text: errorMessage(caught) }
    const field = (typeof caught.details.field === 'string' ? caught.details.field : 'id') as FieldName
    const key = oidcFormErrorKey(caught.code) ?? oidcErrorKey(caught.code)
    return { field, text: key ? t(key) : errorMessage(caught) }
  }

  async function save() {
    setBusy(true)
    setFieldError(null)
    try {
      const body = { ...form, slug: entry ? undefined : slug }
      if (entry) await oidcApi.saveProvider(entry.id, body)
      else await oidcApi.addProvider(body)
      await onSaved()
    } catch (caught) {
      setFieldError(errorFor(caught))
    } finally {
      setBusy(false)
    }
  }

  async function submit(event: FormEvent) {
    event.preventDefault()
    // Another issuer is another provider: say first how many accounts will have to link again.
    if (entry && entry.links > 0 && !sameIssuer(entry.issuer, form.issuer)) {
      try {
        const impact = await oidcApi.impact(entry.id, form.issuer.trim())
        if (impact.issuer_change > 0) return setConfirmIssuer(impact.issuer_change)
      } catch (caught) {
        return setFieldError(errorFor(caught))
      }
    }
    await save()
  }

  const problem = (field: FieldName) => (fieldError?.field === field ? fieldError.text : null)

  return (
    <Dialog title={entry ? `${t('oidc.admin.edit')}: ${entry.label}` : t('oidc.admin.add')} onClose={() => !busy && onClose()} wide>
      <form className="flex flex-col gap-4" onSubmit={(event) => void submit(event)} data-testid="provider-form">
        <Field label={t('oidc.admin.label')} value={form.label} onChange={(event) => set({ label: event.target.value })} error={problem('label')} />
        {entry ? (
          <p className="text-xs text-mist-500">
            {t('oidc.admin.slug')}: <code className="font-mono text-mist-300">{entry.slug}</code>
          </p>
        ) : (
          <Field
            label={t('oidc.admin.slug')}
            value={slug}
            onChange={(event) => {
              setSlugTyped(true)
              set({ slug: event.target.value })
            }}
            hint={t('oidc.admin.slugHint')}
            error={problem('slug')}
          />
        )}
        <Field
          label={t('oidc.admin.issuer')}
          value={form.issuer}
          onChange={(event) => set({ issuer: event.target.value })}
          placeholder="https://auth.example.com/application/o/nexsift/"
          hint={t('oidc.admin.issuerHint')}
          error={problem('issuer')}
        />
        <Field label={t('oidc.admin.clientId')} value={form.client_id} onChange={(event) => set({ client_id: event.target.value })} error={problem('client_id')} />
        <Field
          label={t('oidc.admin.secret')}
          type="password"
          autoComplete="off"
          value={form.client_secret}
          onChange={(event) => set({ client_secret: event.target.value })}
          placeholder={entry?.has_secret ? t('oidc.admin.secretKept') : ''}
          error={problem('client_secret')}
        />
        <CopyField label={t('oidc.admin.redirect')} value={redirect} />
        <Switch label={t('oidc.admin.enabled')} checked={form.enabled} onChange={(enabled) => set({ enabled })} />
        <details open={more || fieldError?.field === 'scopes'} onToggle={(event) => setMore((event.target as HTMLDetailsElement).open)}>
          <summary className="cursor-pointer text-xs text-mist-400">{t('settings.providers.more')}</summary>
          <div className="mt-3">
            <Field label={t('oidc.admin.scopes')} value={form.scopes} onChange={(event) => set({ scopes: event.target.value })} error={problem('scopes')} />
          </div>
        </details>
        {fieldError?.field === 'id' && <Banner tone="bad">{fieldError.text}</Banner>}
        {confirmIssuer !== null && (
          <div className="flex flex-col gap-3 rounded-xl border border-warn-500/40 bg-warn-500/10 p-3" role="alertdialog" aria-label={t('oidc.admin.issuer')}>
            <p className="text-sm text-mist-200">{t('oidc.admin.issuerChangeConfirm', { count: confirmIssuer })}</p>
            <div className="flex justify-end gap-2">
              <Button variant="ghost" size="sm" onClick={() => setConfirmIssuer(null)}>
                {t('settings.providers.cancel')}
              </Button>
              <Button
                variant="danger"
                size="sm"
                loading={busy}
                onClick={() => {
                  setConfirmIssuer(null)
                  void save()
                }}
              >
                {t('common.save')}
              </Button>
            </div>
          </div>
        )}
        <div className="flex justify-end gap-2 pt-2">
          <Button variant="ghost" onClick={onClose} disabled={busy}>
            {t('settings.providers.cancel')}
          </Button>
          <Button type="submit" loading={busy} disabled={confirmIssuer !== null}>
            {t('common.save')}
          </Button>
        </div>
      </form>
    </Dialog>
  )
}

// --- Card 3: authentik in one step ------------------------------------------------------------------------------------

function AuthentikCard({ publicUrl, reload, reloadSettings }: { publicUrl: string; reload: () => Promise<void>; reloadSettings: () => Promise<void> }) {
  const { t } = useTranslation()
  const { refresh } = useAuth()
  const [url, setUrl] = useState('')
  const [token, setToken] = useState('')
  const [busy, setBusy] = useState(false)
  const [result, setResult] = useState<AuthentikResult | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [address, setAddress] = useState<AuthentikAddress | null>(null)
  const [asked, setAsked] = useState<AddressQuestion | null>(null)

  // The address the browser uses is the suggestion while nexsift has none (a proxy may hide it from the server).
  const proposal = authentikProposal(window.location.origin, import.meta.env.BASE_URL)
  const needsAddress = address !== null && !address.public_url
  const stale = authentikStale(address)

  const loadAddress = useCallback(async () => {
    try {
      setAddress(await oidcApi.address())
    } catch {
      // The card still works without it: the button then says what is missing.
    }
  }, [])
  useEffect(() => {
    void loadAddress()
  }, [loadAddress, publicUrl])

  // The button stops before it would change the issuer of an entry with links: the same question as
  // the form, and only "Save" runs it again with the confirmation; "Cancel" leaves everything as it is.
  const issuerChange = result ? authentikIssuerChange(result) : null

  async function run(confirmIssuerChange = false) {
    setBusy(true)
    setError(null)
    setResult(null)
    try {
      const outcome = await oidcApi.authentik(url, token, confirmIssuerChange, needsAddress ? proposal : '')
      setResult(outcome)
      if (outcome.ok) setToken('')
      if (outcome.address) setAddress(outcome.address)
      else await loadAddress()
      // A run that took the suggested address kept it, even when a later step failed.
      if (outcome.public_url) await reloadSettings()
      await reload()
      await refresh()
    } catch (caught) {
      setError(errorMessage(caught))
    } finally {
      setBusy(false)
    }
  }

  /** "Use it only": the suggestion becomes the public address, nothing is set up (the blueprint needs it). */
  async function adoptOnly(confirmed = false) {
    setBusy(true)
    setError(null)
    try {
      setAddress(await oidcApi.saveAddress(proposal, confirmed))
      setAsked(null)
      await reloadSettings()
      await reload()
    } catch (caught) {
      const question = addressQuestion(caught)
      if (question) setAsked(question)
      else if (caught instanceof ApiError && caught.code === 'public_url_invalid') setError(t('oidc.authentik.why.unusable'))
      else setError(errorMessage(caught))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div id="sign-in-authentik">
      <Section title={t('oidc.authentik.title')} intro={t('oidc.authentik.text')}>
        {needsAddress && address && (
          <div className="flex flex-col gap-3" data-testid="authentik-no-address">
            <Banner tone="warn">
              {t('oidc.authentik.noAddress')} <code className="font-mono break-all">{proposal}</code>
            </Banner>
            <CopyField label={t('oidc.admin.redirect')} value={authentikRedirect(proposal, address)} />
            {authentikProxyWarning(proposal, address) && (
              <div data-testid="authentik-proxy-warning">
                <Banner tone="warn">{t('oidc.authentik.proxyWarning', { address: address.seen })}</Banner>
              </div>
            )}
          </div>
        )}
        {stale && (
          <div data-testid="authentik-stale">
            <Banner tone="warn">{t('oidc.authentik.stale', { address: stale })}</Banner>
          </div>
        )}
        <form
          className="flex flex-col gap-4"
          onSubmit={(event) => {
            event.preventDefault()
            void run()
          }}
        >
          <div className="grid gap-3 sm:grid-cols-2">
            <Field label={t('oidc.authentik.url')} value={url} onChange={(event) => setUrl(event.target.value)} placeholder="https://auth.example.com" disabled={busy} />
            <Field label={t('oidc.authentik.token')} type="password" autoComplete="off" value={token} onChange={(event) => setToken(event.target.value)} disabled={busy} />
          </div>
          <div className="flex flex-wrap items-center gap-3">
            <Button type="submit" loading={busy} disabled={!url.trim() || !token.trim()}>
              <Symbol name="shield" />
              {needsAddress ? t('oidc.authentik.adopt') : t('oidc.authentik.run')}
            </Button>
            {needsAddress && (
              <Button variant="ghost" loading={busy} onClick={() => void adoptOnly()}>
                {t('oidc.authentik.adoptOnly')}
              </Button>
            )}
            <a href="/api/oidc/authentik/blueprint" className="inline-flex items-center gap-1.5 text-sm text-accent-400 hover:underline">
              <Symbol name="download" className="h-3.5 w-3.5" />
              {t('oidc.authentik.blueprint')}
            </a>
          </div>
        </form>
        {busy && (
          <p className="text-xs text-mist-400" aria-live="polite">
            {t('oidc.authentik.asking')}
          </p>
        )}
        {error && <Banner tone="bad">{error}</Banner>}
        {asked && <AddressChangeQuestion question={asked} busy={busy} onCancel={() => setAsked(null)} onConfirm={() => void adoptOnly(true)} />}
        {issuerChange !== null && (
          <div className="flex flex-col gap-3 rounded-xl border border-warn-500/40 bg-warn-500/10 p-3" role="alertdialog" aria-label={t('oidc.admin.issuer')} data-testid="authentik-issuer-change">
            <p className="text-sm text-mist-200">{t('oidc.admin.issuerChangeConfirm', { count: issuerChange })}</p>
            <div className="flex justify-end gap-2">
              <Button variant="ghost" size="sm" onClick={() => setResult(null)}>
                {t('settings.providers.cancel')}
              </Button>
              <Button variant="danger" size="sm" loading={busy} onClick={() => void run(true)}>
                {t('common.save')}
              </Button>
            </div>
          </div>
        )}
        {result && issuerChange === null && (
          <ol className="flex flex-col gap-2" data-testid="authentik-steps">
            {result.steps.map((step) => {
              const name = authentikStepKey(step.key)
              const why = step.ok ? null : authentikReasonKey(step.reason)
              return (
                <li key={step.key} className={'flex items-start gap-2.5 text-sm ' + (step.ok ? 'text-mist-200' : 'text-bad-500')}>
                  <Symbol name={step.ok ? 'check' : 'close'} className={'mt-0.5 h-4 w-4 shrink-0 ' + (step.ok ? 'text-ok-500' : '')} />
                  <span>
                    <span className={step.ok ? '' : 'font-medium'}>{name ? t(name) : step.key}</span>
                    {why && <span className="block text-xs text-mist-400">{t(why, { status: step.status ?? 0, count: result.count ?? 0 })}</span>}
                  </span>
                </li>
              )
            })}
          </ol>
        )}
      </Section>
    </div>
  )
}
