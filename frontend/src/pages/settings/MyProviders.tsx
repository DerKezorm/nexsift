/**
 * "Sign-in providers" of the own account (shared sign-in blueprint, part 04, "Mein Konto, Sicherheit"): one line per
 * active provider with its state and "Link" or "Unlink". nexsift has one account, so this card sits under
 * Settings, Account. Linking asks the password once more, then the browser goes to the provider and comes back to
 * `/account?linked=<slug>` or `?error=<code>` (forwarded here, see `App.tsx`).
 */
import { useCallback, useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useSearchParams } from 'react-router-dom'

import { errorMessage } from '../../api/client'
import { oidcApi, type MyProvider } from '../../api/oidc'
import type { Settings } from '../../api/types'
import { useAuth } from '../../auth'
import { useNotice } from '../../components/Notice'
import { Symbol } from '../../components/Symbol'
import { Badge, Banner, Button, Field, Section } from '../../components/ui'
import { oidcErrorKey } from '../../vendor/nexoidc/oidc'

export function MyProviders({ settings }: { settings: Settings | undefined }) {
  const { t } = useTranslation()
  const notify = useNotice()
  const { account, refresh } = useAuth()
  const [params, setParams] = useSearchParams()
  const [mine, setMine] = useState<MyProvider[] | null>(null)
  const [asking, setAsking] = useState<string | null>(null)
  const [password, setPassword] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(async () => {
    try {
      setMine(await oidcApi.mine())
    } catch (caught) {
      setError(errorMessage(caught))
      setMine([])
    }
  }, [])

  useEffect(() => {
    void load()
  }, [load])

  // Back from the provider: ?linked=<slug> names the provider by the name on its button, never by the short name.
  const linkedSlug = params.get('linked')
  const returned = oidcErrorKey(params.get('error'))
  useEffect(() => {
    if (!linkedSlug || mine === null) return
    const entry = mine.find((item) => item.slug === linkedSlug)
    if (entry) notify({ text: t('settings.providers.linkedNow', { name: entry.label }) })
    void refresh()
    setParams({}, { replace: true })
  }, [linkedSlug, mine, notify, refresh, setParams, t])

  async function link(slug: string) {
    setBusy(true)
    setError(null)
    try {
      const { url } = await oidcApi.link(slug, password)
      window.location.assign(url)
    } catch (caught) {
      setError(errorMessage(caught))
      setBusy(false)
    }
  }

  async function unlink(slug: string) {
    setBusy(true)
    setError(null)
    try {
      await oidcApi.unlink(slug)
      await load()
      await refresh()
    } catch (caught) {
      setError(errorMessage(caught))
    } finally {
      setBusy(false)
    }
  }

  const passwordOff = settings ? !settings.password_login : false
  const linkedCount = (mine ?? []).filter((item) => item.linked).length
  return (
    <div id="my-providers">
      <Section title={t('oidc.account.title')} intro={t('oidc.account.text')}>
        {returned && (
          <Banner tone="bad">
            <span data-testid="link-error">{t(returned)}</span>
          </Banner>
        )}
        {mine !== null && mine.length === 0 && <p className="text-sm text-mist-400">{t('settings.providers.none')}</p>}
        {mine !== null && mine.length > 0 && (
          <ul className="divide-y divide-ink-700 rounded-xl border border-ink-700" data-testid="my-providers">
            {mine.map((item) => (
              <li key={item.slug} className="flex flex-col gap-3 px-3 py-3 text-sm">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="min-w-0 flex-1 font-medium text-mist-100">{item.label}</span>
                  <Badge tone={item.linked ? 'ok' : 'neutral'}>{item.linked ? t('oidc.account.linked') : t('oidc.account.notLinked')}</Badge>
                  {item.linked ? (
                    <Button variant="ghost" size="sm" loading={busy} onClick={() => void unlink(item.slug)}>
                      {t('oidc.account.unlink')}
                    </Button>
                  ) : (
                    asking !== item.slug && (
                      <Button
                        size="sm"
                        onClick={() => {
                          setAsking(item.slug)
                          setPassword('')
                          setError(null)
                        }}
                      >
                        <Symbol name="shield" className="h-4 w-4" />
                        {t('oidc.account.link')}
                      </Button>
                    )
                  )}
                </div>
                {asking === item.slug && !item.linked && (
                  <form
                    className="flex flex-wrap items-end gap-2"
                    onSubmit={(event) => {
                      event.preventDefault()
                      void link(item.slug)
                    }}
                  >
                    <input type="text" autoComplete="username" value={account?.name ?? ''} readOnly hidden />
                    <div className="min-w-48 flex-1">
                      <Field label={t('settings.providers.confirmPassword')} type="password" autoComplete="current-password" value={password} onChange={(event) => setPassword(event.target.value)} autoFocus />
                    </div>
                    <Button variant="ghost" onClick={() => setAsking(null)} disabled={busy}>
                      {t('settings.providers.cancel')}
                    </Button>
                    <Button type="submit" loading={busy} disabled={!password}>
                      {t('oidc.account.link')}
                    </Button>
                  </form>
                )}
                {item.linked && passwordOff && linkedCount === 1 && <p className="text-xs text-mist-500">{t('settings.providers.wayBackNote')}</p>}
              </li>
            ))}
          </ul>
        )}
        {error && <Banner tone="bad">{error}</Banner>}
      </Section>
    </div>
  )
}
