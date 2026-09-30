import { useEffect, useState, type FormEvent, type ReactNode } from 'react'
import { useTranslation } from 'react-i18next'

import { api, errorMessage } from '../../api/client'
import type { Account } from '../../api/types'
import { useAuth } from '../../auth'
import { LanguageSwitcher } from '../../components/LanguageSwitcher'
import { Logo } from '../../components/Logo'
import { Symbol } from '../../components/Symbol'
import { ThemeSwitcher } from '../../components/ThemeSwitcher'
import { Banner, Button, Field } from '../../components/ui'

function Frame({ children }: { children: ReactNode }) {
  return (
    <div className="ns-glow flex min-h-dvh flex-col">
      <header className="relative z-10 flex items-center justify-between px-4 py-4 sm:px-6">
        <Logo withWordmark />
        <div className="flex items-center gap-2">
          <ThemeSwitcher />
          <LanguageSwitcher />
        </div>
      </header>
      <main className="relative z-10 flex flex-1 items-start justify-center px-4 pt-6 pb-16 sm:items-center sm:pt-0">
        <div className="w-full max-w-md rounded-2xl border border-ink-700 bg-ink-850/90 p-6 shadow-2xl shadow-black/40 backdrop-blur sm:p-8">{children}</div>
      </main>
    </div>
  )
}

/** The very first start: the operator account. Explains what nexsift is and what happens next. */
export function SetupScreen() {
  const { t } = useTranslation()
  const { setAccount } = useAuth()
  const [name, setName] = useState('admin')
  const [password, setPassword] = useState('')
  const [repeat, setRepeat] = useState('')
  const [email, setEmail] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const mismatch = repeat.length > 0 && repeat !== password
  const tooShort = password.length > 0 && password.length < 12

  async function submit(event: FormEvent) {
    event.preventDefault()
    if (mismatch || tooShort) return
    setBusy(true)
    setError(null)
    try {
      setAccount(await api.post<Account>('/api/setup', { name, password, email }))
    } catch (caught) {
      setError(errorMessage(caught))
    } finally {
      setBusy(false)
    }
  }

  return (
    <Frame>
      <h1 className="text-2xl font-bold tracking-tight">{t('setup.title')}</h1>
      <p className="mt-2 text-sm text-mist-400">{t('setup.lead')}</p>
      <form onSubmit={(event) => void submit(event)} className="mt-6 flex flex-col gap-4">
        <Field label={t('setup.name')} value={name} onChange={(event) => setName(event.target.value)} autoComplete="username" required help={t('setup.nameHelp')} />
        <Field
          label={t('setup.password')}
          type="password"
          value={password}
          onChange={(event) => setPassword(event.target.value)}
          autoComplete="new-password"
          required
          error={tooShort ? t('setup.tooShort') : null}
          hint={!tooShort ? t('setup.passwordHint') : undefined}
        />
        <Field
          label={t('setup.repeat')}
          type="password"
          value={repeat}
          onChange={(event) => setRepeat(event.target.value)}
          autoComplete="new-password"
          required
          error={mismatch ? t('setup.mismatch') : null}
        />
        <Field
          label={t('setup.email')}
          type="email"
          value={email}
          onChange={(event) => setEmail(event.target.value)}
          autoComplete="email"
          hint={t('setup.emailHint')}
          help={t('setup.emailHelp')}
        />
        {error && <Banner tone="bad">{error}</Banner>}
        <Button type="submit" loading={busy} disabled={!name || !password || mismatch || tooShort}>
          {t('setup.submit')}
        </Button>
      </form>
    </Frame>
  )
}

/** Sign-in: the provider button when there is one, the password otherwise (or both). */
export function LoginScreen() {
  const { t } = useTranslation()
  const { setAccount } = useAuth()
  const [name, setName] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [oidc, setOidc] = useState<{ enabled: boolean; provider_name: string; password_login: boolean } | null>(null)
  const fromProvider = new URLSearchParams(window.location.search).get('error')

  useEffect(() => {
    api
      .get<{ enabled: boolean; provider_name: string; password_login: boolean }>('/api/oidc/state')
      .then(setOidc)
      .catch(() => setOidc({ enabled: false, provider_name: '', password_login: true }))
  }, [])

  async function submit(event: FormEvent) {
    event.preventDefault()
    setBusy(true)
    setError(null)
    try {
      setAccount(await api.post<Account>('/api/auth/login', { name, password }))
      window.history.replaceState(null, '', '/')
    } catch (caught) {
      setError(errorMessage(caught))
    } finally {
      setBusy(false)
    }
  }

  return (
    <Frame>
      <h1 className="text-2xl font-bold tracking-tight">{t('login.title')}</h1>
      <p className="mt-2 text-sm text-mist-400">{t('login.lead')}</p>
      {fromProvider && (
        <div className="mt-4">
          <Banner tone="bad">{t(`errors.${fromProvider}`, { defaultValue: t('login.providerFailed') })}</Banner>
        </div>
      )}
      {oidc?.enabled && (
        <a href="/api/oidc/start" className="mt-6 flex w-full items-center justify-center gap-2 rounded-full bg-accent-500 px-5 py-2.5 text-sm font-semibold text-on-accent hover:bg-accent-400">
          <Symbol name="shield" />
          {t('login.withProvider', { name: oidc.provider_name })}
        </a>
      )}
      {oidc?.enabled && oidc.password_login && <p className="my-5 text-center text-xs text-mist-600">{t('login.or')}</p>}
      {(!oidc || oidc.password_login) && (
        <form onSubmit={(event) => void submit(event)} className={'flex flex-col gap-4 ' + (oidc?.enabled ? '' : 'mt-6')}>
          <Field label={t('login.name')} value={name} onChange={(event) => setName(event.target.value)} autoComplete="username" required />
          <Field label={t('login.password')} type="password" value={password} onChange={(event) => setPassword(event.target.value)} autoComplete="current-password" required />
          {error && <Banner tone="bad">{error}</Banner>}
          <Button type="submit" variant={oidc?.enabled ? 'ghost' : 'primary'} loading={busy} disabled={!name || !password}>
            {t('login.submit')}
          </Button>
        </form>
      )}
      <p className="mt-6 text-xs text-mist-600">
        {t('login.forgot')} <code className="font-mono whitespace-nowrap text-mist-400">python -m app.reset_password</code>
      </p>
    </Frame>
  )
}

export function UnreachableScreen({ onRetry }: { onRetry: () => void }) {
  const { t } = useTranslation()
  return (
    <Frame>
      <h1 className="text-xl font-bold">{t('unreachable.title')}</h1>
      <p className="mt-2 text-sm text-mist-400">{t('unreachable.lead')}</p>
      <Button className="mt-6" onClick={onRetry}>
        <Symbol name="refresh" />
        {t('unreachable.retry')}
      </Button>
    </Frame>
  )
}
