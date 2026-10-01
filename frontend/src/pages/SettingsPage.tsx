import { useEffect, useState, type ChangeEvent } from 'react'
import { useTranslation } from 'react-i18next'
import { useSearchParams } from 'react-router-dom'

import { api, errorMessage } from '../api/client'
import type { Settings } from '../api/types'
import { useAuth } from '../auth'
import { useNotice } from '../components/Notice'
import { Symbol } from '../components/Symbol'
import { TabRow } from '../components/TabRow'
import { Banner, Button, Field, PageHeader, Section, Switch } from '../components/ui'
import { useLoad } from '../lib/useLoad'
import { Languages } from './settings/Languages'
import { ProviderLink } from './settings/ProviderLink'

interface OidcConfig {
  configured: boolean
  issuer: string
  client_id: string
  provider_name: string
  redirect_uri: string
}

const TABS = ['account', 'signin', 'addresses', 'retention', 'languages'] as const
type Tab = (typeof TABS)[number]

function isTab(value: string | null): value is Tab {
  return (TABS as readonly string[]).includes(value ?? '')
}

export function SettingsPage() {
  const { t } = useTranslation()
  const settings = useLoad(() => api.get<Settings>('/api/settings'), [])
  const oidc = useLoad(() => api.get<OidcConfig>('/api/oidc/config'), [])
  // The password may only go once the provider is linked: otherwise nobody could sign in any more.
  const { account } = useAuth()
  // The tab is in the address (`?tab=addresses`), so other pages can link straight to it.
  const [params, setParams] = useSearchParams()
  const wanted = params.get('tab')
  const tab: Tab = isTab(wanted) ? wanted : 'account'
  const tabs = TABS.map((value) => ({ value, label: t(`settings.tab.${value}`) }))
  return (
    <div className="flex flex-col gap-6">
      <PageHeader title={t('settings.title')} lead={t('settings.lead')} />
      <TabRow tabs={tabs} active={tab} onChange={(value) => setParams(value === 'account' ? {} : { tab: value }, { replace: true })} label={t('settings.title')} />
      <div className="max-w-3xl">
        {tab === 'account' && <AccountSection />}
        {tab === 'signin' && (
          <div className="flex flex-col gap-6">
            <Authentik config={oidc.data} onDone={() => void oidc.reload()} />
            <OtherProvider config={oidc.data} onChange={() => void oidc.reload()} />
            {oidc.data?.configured && <ProviderLink provider={oidc.data.provider_name || 'OpenID Connect'} passwordLogin={settings.data?.password_login ?? true} />}
            {settings.data && <SignIn part="password" settings={settings.data} configured={!!oidc.data?.configured && !!account?.oidc_linked} onSaved={settings.set} />}
          </div>
        )}
        {tab === 'addresses' && settings.data && <SignIn part="addresses" settings={settings.data} configured={!!oidc.data?.configured} onSaved={settings.set} />}
        {tab === 'retention' && settings.data && <Retention settings={settings.data} onSaved={settings.set} />}
        {tab === 'languages' && <Languages />}
      </div>
    </div>
  )
}

function AccountSection() {
  const { t } = useTranslation()
  const notify = useNotice()
  const { account } = useAuth()
  const [current, setCurrent] = useState('')
  const [next, setNext] = useState('')
  const [repeat, setRepeat] = useState('')
  const [error, setError] = useState<string | null>(null)
  const mismatch = repeat.length > 0 && repeat !== next

  async function changePassword() {
    setError(null)
    try {
      await api.put('/api/auth/password', { current, new: next })
      setCurrent('')
      setNext('')
      setRepeat('')
      notify({ text: t('settings.account.passwordChanged') })
    } catch (caught) {
      setError(errorMessage(caught))
    }
  }

  return (
    <Section title={t('settings.account.title')} intro={t('settings.account.intro', { name: account?.name })} help={t('settings.account.help')}>
      <form
        className="flex flex-col gap-3"
        onSubmit={(event) => {
          event.preventDefault()
          void changePassword()
        }}
      >
        <p className="text-sm font-medium text-mist-200">{t('settings.account.passwordTitle')}</p>
        <input type="text" autoComplete="username" value={account?.name ?? ''} readOnly hidden />
        <Field label={t('settings.account.current')} type="password" autoComplete="current-password" value={current} onChange={(event) => setCurrent(event.target.value)} />
        <div className="grid gap-3 sm:grid-cols-2">
          <Field label={t('settings.account.new')} type="password" autoComplete="new-password" value={next} onChange={(event) => setNext(event.target.value)} hint={t('setup.passwordHint')} />
          <Field label={t('settings.account.repeat')} type="password" autoComplete="new-password" value={repeat} onChange={(event) => setRepeat(event.target.value)} error={mismatch ? t('setup.mismatch') : null} />
        </div>
        {error && <Banner tone="bad">{error}</Banner>}
        <Button type="submit" variant="ghost" className="self-start" disabled={!current || next.length < 12 || mismatch || !repeat}>
          {t('settings.account.changePassword')}
        </Button>
      </form>
    </Section>
  )
}

interface SetupResult {
  steps: { key: string; ok: boolean; detail: string }[]
  client_id: string
  issuer: string
}

const STEPS = ['reached', 'signingKey', 'mapping', 'provider', 'application', 'filled']

/**
 * Like in nextrmnl: address plus a one-time API token, and nexsift creates signing key, scope mapping, provider
 * and application in authentik itself. The token is used once and never stored.
 */
function Authentik({ config, onDone }: { config?: OidcConfig; onDone: () => void }) {
  const { t } = useTranslation()
  const [url, setUrl] = useState('')
  const [token, setToken] = useState('')
  const [busy, setBusy] = useState(false)
  const [result, setResult] = useState<SetupResult | null>(null)
  const [error, setError] = useState<string | null>(null)
  const failed = result?.steps.some((step) => !step.ok) ?? false

  async function run() {
    setBusy(true)
    setError(null)
    setResult(null)
    try {
      const outcome = await api.post<SetupResult>('/api/oidc/authentik/setup', { url, token })
      setResult(outcome)
      if (!outcome.steps.some((step) => !step.ok)) {
        setToken('')
        onDone()
      }
    } catch (caught) {
      setError(errorMessage(caught))
    } finally {
      setBusy(false)
    }
  }

  return (
    <Section
      title={t('settings.authentik.title')}
      intro={t('settings.authentik.lead')}
      help={t('settings.authentik.help')}
      aside={<span className="rounded-full bg-accent-500/15 px-2.5 py-0.5 text-xs font-medium text-accent-400">{t('settings.recommended')}</span>}
    >
      {config?.configured && config.provider_name === 'authentik' && !result && <Banner tone="ok">{t('settings.authentik.already', { issuer: config.issuer })}</Banner>}
      <Field label={t('settings.authentik.url')} value={url} onChange={(event) => setUrl(event.target.value)} placeholder="https://auth.example.com" help={t('settings.authentik.urlHelp')} disabled={busy} />
      <Field label={t('settings.authentik.token')} hint={t('settings.authentik.tokenHint')} type="password" autoComplete="off" value={token} onChange={(event) => setToken(event.target.value)} disabled={busy} help={t('settings.authentik.tokenHelp')} />
      <div className="flex flex-wrap items-center justify-between gap-3">
        <Button onClick={() => void run()} loading={busy} disabled={!url.trim() || !token.trim()}>
          <Symbol name="shield" />
          {config?.configured ? t('settings.authentik.again') : t('settings.authentik.setUp')}
        </Button>
        <a href="/api/oidc/authentik/blueprint" className="inline-flex items-center gap-1.5 text-xs text-mist-500 hover:text-mist-100" title={t('settings.authentik.blueprintHelp')}>
          <Symbol name="download" className="h-3.5 w-3.5" />
          {t('settings.authentik.blueprint')}
        </a>
      </div>
      {error && <Banner tone="bad">{error}</Banner>}
      {result && (
        <ol className="flex flex-col gap-2">
          {STEPS.map((key) => {
            const step = result.steps.find((item) => item.key === key)
            return (
              <li key={key} className={'flex items-start gap-2.5 text-sm ' + (step ? (step.ok ? 'text-mist-200' : 'text-bad-500') : 'text-mist-600')}>
                {step ? <Symbol name={step.ok ? 'check' : 'close'} className={'mt-0.5 h-4 w-4 shrink-0 ' + (step.ok ? 'text-ok-500' : '')} /> : <span className="mt-1.5 ml-1.5 h-1.5 w-1.5 shrink-0 rounded-full bg-ink-600" />}
                <span>
                  {t(`settings.authentik.step.${key}`, { redirect: config?.redirect_uri ?? '' })}
                  {step && !step.ok && <span className="block text-xs">{step.detail}</span>}
                </span>
              </li>
            )
          })}
        </ol>
      )}
      {result && !failed && <Banner tone="ok">{t('settings.authentik.done')}</Banner>}
      {result && failed && <Banner tone="bad">{t('settings.authentik.failed')}</Banner>}
    </Section>
  )
}

function OtherProvider({ config, onChange }: { config?: OidcConfig; onChange: () => void }) {
  const { t } = useTranslation()
  const notify = useNotice()
  const [open, setOpen] = useState(false)
  const [issuer, setIssuer] = useState('')
  const [clientId, setClientId] = useState('')
  const [secret, setSecret] = useState('')
  const [name, setName] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    if (!config) return
    setIssuer(config.issuer)
    setClientId(config.client_id)
    setName(config.provider_name)
  }, [config])

  async function save() {
    setBusy(true)
    setError(null)
    try {
      await api.put('/api/oidc/config', { issuer, client_id: clientId, client_secret: secret, provider_name: name })
      setSecret('')
      notify({ text: t('common.saved') })
      onChange()
    } catch (caught) {
      setError(errorMessage(caught))
    } finally {
      setBusy(false)
    }
  }

  async function remove() {
    try {
      await api.delete('/api/oidc/config')
      notify({ text: t('settings.other.removed') })
      onChange()
    } catch (caught) {
      notify({ text: errorMessage(caught) })
    }
  }

  return (
    <Section
      title={t('settings.other.title')}
      intro={config?.configured ? t('settings.other.active', { name: config.provider_name || 'OpenID Connect' }) : t('settings.other.lead')}
      help={t('settings.other.help')}
      aside={
        <Button variant="ghost" size="sm" onClick={() => setOpen(!open)} aria-expanded={open}>
          {open ? t('common.hide') : t('common.show')}
        </Button>
      }
    >
      {open && (
        <>
          <Field label={t('settings.other.issuer')} value={issuer} onChange={(event) => setIssuer(event.target.value)} placeholder="https://id.example.com/realms/homelab" help={t('settings.other.issuerHelp')} />
          <div className="grid gap-3 sm:grid-cols-2">
            <Field label={t('settings.other.clientId')} value={clientId} onChange={(event) => setClientId(event.target.value)} />
            <Field label={t('settings.other.clientSecret')} type="password" autoComplete="off" value={secret} onChange={(event) => setSecret(event.target.value)} placeholder={config?.configured ? t('settings.other.secretKept') : ''} />
          </div>
          <Field label={t('settings.other.providerName')} value={name} onChange={(event) => setName(event.target.value)} placeholder="Keycloak" help={t('settings.other.providerNameHelp')} />
          {config && <Field label={t('settings.other.redirect')} readOnly value={config.redirect_uri} help={t('settings.other.redirectHelp')} />}
          {error && <Banner tone="bad">{error}</Banner>}
          <div className="flex flex-wrap justify-between gap-2">
            {config?.configured ? (
              <Button variant="danger" size="sm" onClick={() => void remove()}>
                {t('settings.other.remove')}
              </Button>
            ) : (
              <span />
            )}
            <Button onClick={() => void save()} loading={busy} disabled={!issuer.trim() || !clientId.trim()}>
              {t('common.save')}
            </Button>
          </div>
        </>
      )}
    </Section>
  )
}

/** Two tabs share the saving: the addresses, and the switch for signing in with a password. */
function SignIn({ part, settings, configured, onSaved }: { part: 'addresses' | 'password'; settings: Settings; configured: boolean; onSaved: (settings: Settings) => void }) {
  const { t } = useTranslation()
  const notify = useNotice()
  const [publicUrl, setPublicUrl] = useState(settings.public_url)
  const [senderHost, setSenderHost] = useState(settings.sender_host)
  const [error, setError] = useState<string | null>(null)

  async function save(values: Partial<Settings>) {
    setError(null)
    try {
      const saved = await api.put<Settings>('/api/settings', { values })
      onSaved(saved)
      // The server tidies addresses up (a pasted http:// goes); the fields show what was stored.
      setPublicUrl(saved.public_url)
      setSenderHost(saved.sender_host)
      notify({ text: t('common.saved') })
    } catch (caught) {
      setError(errorMessage(caught))
    }
  }

  if (part === 'password') {
    return (
      <Section title={t('settings.signin.passwordTitle')} intro={t('settings.signin.passwordLead')}>
        <Switch
          label={t('settings.signin.password')}
          hint={configured ? t('settings.signin.passwordHint') : t('settings.signin.passwordNeedsProvider')}
          checked={settings.password_login}
          onChange={(value) => void save({ password_login: value })}
          disabled={!configured && settings.password_login}
          help={t('settings.signin.passwordHelp')}
        />
        {error && <Banner tone="bad">{error}</Banner>}
      </Section>
    )
  }

  return (
    <Section title={t('settings.signin.title')} intro={t('settings.signin.lead')} help={t('settings.signin.help')}>
      <div className="flex items-end gap-2">
        <div className="flex-1">
          <Field label={t('settings.signin.publicUrl')} hint={t('settings.signin.publicUrlHint')} value={publicUrl} onChange={(event: ChangeEvent<HTMLInputElement>) => setPublicUrl(event.target.value)} placeholder="https://nexsift.example.com" help={t('settings.signin.publicUrlHelp')} />
        </div>
        <Button variant="ghost" onClick={() => void save({ public_url: publicUrl })} disabled={publicUrl === settings.public_url} className="mb-10">
          {t('common.save')}
        </Button>
      </div>
      <div className="flex items-end gap-2">
        <div className="flex-1">
          <Field label={t('settings.signin.senderHost')} hint={t('settings.signin.senderHostHint')} value={senderHost} onChange={(event: ChangeEvent<HTMLInputElement>) => setSenderHost(event.target.value)} placeholder="192.168.1.10" help={t('settings.signin.senderHostHelp')} />
        </div>
        <Button variant="ghost" onClick={() => void save({ sender_host: senderHost })} disabled={senderHost === settings.sender_host} className="mb-10">
          {t('common.save')}
        </Button>
      </div>
      {error && <Banner tone="bad">{error}</Banner>}
    </Section>
  )
}

function Retention({ settings, onSaved }: { settings: Settings; onSaved: (settings: Settings) => void }) {
  const { t } = useTranslation()
  const notify = useNotice()
  const [values, setValues] = useState({ retention_days: settings.retention_days, archive_days: settings.archive_days, raw_days: settings.raw_days })
  const [error, setError] = useState<string | null>(null)
  const changed = values.retention_days !== settings.retention_days || values.archive_days !== settings.archive_days || values.raw_days !== settings.raw_days

  async function save() {
    try {
      onSaved(await api.put<Settings>('/api/settings', { values }))
      setError(null)
      notify({ text: t('common.saved') })
    } catch (caught) {
      setError(errorMessage(caught))
    }
  }

  const input = (key: keyof typeof values) => ({
    value: String(values[key]),
    inputMode: 'numeric' as const,
    onChange: (event: ChangeEvent<HTMLInputElement>) => setValues({ ...values, [key]: Number(event.target.value.replace(/\D/g, '') || 0) }),
  })

  return (
    <Section title={t('settings.retention.title')} intro={t('settings.retention.lead')} help={t('settings.retention.help')}>
      <div className="grid gap-3 sm:grid-cols-3">
        <Field label={t('settings.retention.events')} help={t('settings.retention.eventsHelp')} {...input('retention_days')} />
        <Field label={t('settings.retention.archive')} help={t('settings.retention.archiveHelp')} {...input('archive_days')} />
        <Field label={t('settings.retention.raw')} help={t('settings.retention.rawHelp')} {...input('raw_days')} />
      </div>
      {error && <Banner tone="bad">{error}</Banner>}
      <div className="flex justify-end">
        <Button onClick={() => void save()} disabled={!changed}>
          {t('common.save')}
        </Button>
      </div>
    </Section>
  )
}

