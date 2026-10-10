import { useEffect, useState, type FormEvent, type ReactNode } from 'react'
import { useTranslation } from 'react-i18next'

import { api, errorMessage } from '../../api/client'
import { oidcApi, startAt, type SignInState } from '../../api/oidc'
import type { Account } from '../../api/types'
import { useAuth } from '../../auth'
import { LanguageSwitcher } from '../../components/LanguageSwitcher'
import { Logo } from '../../components/Logo'
import { Symbol } from '../../components/Symbol'
import { ThemeSwitcher } from '../../components/ThemeSwitcher'
import { Banner, Button, Field } from '../../components/ui'
import { oidcErrorKey } from '../../vendor/nexoidc/oidc'

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

/**
 * Sign-in, as the shared sign-in blueprint lays it out (part 04): the password form, below it "or" and a button per
 * active provider in the order of the list. With the password sign-in off only the buttons. An error from the
 * provider (`?error=<code>`) shows above, in the module's words; an unknown code shows nothing.
 */
export function LoginScreen() {
  const { t } = useTranslation()
  const { setAccount } = useAuth()
  const [name, setName] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [state, setState] = useState<SignInState | null>(null)
  // Only where the app lets the operator keep the password (settings_service.PASSWORD_ALWAYS_FOR_OPERATOR).
  const [asOperator, setAsOperator] = useState(false)
  const fromProvider = oidcErrorKey(new URLSearchParams(window.location.search).get('error'))

  useEffect(() => {
    oidcApi
      .state()
      .then(setState)
      .catch(() => setState({ password_login: true, operator_password: false, providers: [] }))
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

  const buttons = state?.providers ?? []
  const passwordShown = !state || state.password_login || asOperator
  return (
    <Frame>
      <h1 className="text-2xl font-bold tracking-tight">{t('login.title')}</h1>
      <p className="mt-2 text-sm text-mist-400">{t('login.lead')}</p>
      {fromProvider && (
        <div className="mt-4" data-testid="sign-in-error">
          <Banner tone="bad">{t(fromProvider)}</Banner>
        </div>
      )}
      {passwordShown && (
        <form onSubmit={(event) => void submit(event)} className="mt-6 flex flex-col gap-4">
          <Field label={t('login.name')} value={name} onChange={(event) => setName(event.target.value)} autoComplete="username" required />
          <Field label={t('login.password')} type="password" value={password} onChange={(event) => setPassword(event.target.value)} autoComplete="current-password" required />
          {error && <Banner tone="bad">{error}</Banner>}
          <Button type="submit" loading={busy} disabled={!name || !password}>
            {t('login.submit')}
          </Button>
        </form>
      )}
      {passwordShown && buttons.length > 0 && (
        <div className="my-5 flex items-center gap-3 text-xs text-mist-600" aria-hidden="true">
          <span className="h-px flex-1 bg-ink-700" />
          {t('oidc.login.or')}
          <span className="h-px flex-1 bg-ink-700" />
        </div>
      )}
      {buttons.length > 0 && (
        <div className={'flex flex-col gap-2 ' + (passwordShown ? '' : 'mt-6')} data-testid="provider-buttons">
          {buttons.map((button) => (
            <Button key={button.slug} variant={passwordShown ? 'ghost' : 'primary'} onClick={() => startAt(button.slug)}>
              <Symbol name="shield" />
              {t('oidc.login.button', { name: button.label })}
            </Button>
          ))}
        </div>
      )}
      {state && !passwordShown && state.operator_password && (
        <button type="button" className="mt-4 text-xs text-mist-500 underline hover:text-mist-200" onClick={() => setAsOperator(true)}>
          {t('oidc.login.operator')}
        </button>
      )}
      <p className="mt-6 text-xs text-mist-600">
        {t('login.forgot')} <code className="font-mono whitespace-nowrap text-mist-400">python -m app.reset_password</code>
      </p>
    </Frame>
  )
}

/** Shown while the server is away, typically for the minute an update restarts the container. It keeps
 * trying on its own, so nobody is stuck on this page after the server came back. */
export function UnreachableScreen({ onRetry }: { onRetry: () => void }) {
  const { t } = useTranslation()
  useEffect(() => {
    const timer = window.setInterval(onRetry, 5000)
    return () => window.clearInterval(timer)
  }, [onRetry])
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
