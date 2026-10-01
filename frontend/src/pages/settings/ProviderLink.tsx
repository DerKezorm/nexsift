import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useSearchParams } from 'react-router-dom'

import { api, errorMessage } from '../../api/client'
import { useAuth } from '../../auth'
import { useNotice } from '../../components/Notice'
import { Symbol } from '../../components/Symbol'
import { Banner, Button, Section } from '../../components/ui'

/**
 * Which account at the provider is the operator. nexsift has one account, so the link is made right here, while
 * signed in: one run at the provider, and from then on exactly that identity is let in. Nothing else counts, not
 * even a matching address.
 */
export function ProviderLink({ provider, passwordLogin }: { provider: string; passwordLogin: boolean }) {
  const { t } = useTranslation()
  const notify = useNotice()
  const { account, refresh } = useAuth()
  const [params, setParams] = useSearchParams()
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  // Back from the provider: /settings?tab=signin&linked=1 or …&error=<code>.
  useEffect(() => {
    const linked = params.get('linked')
    const code = params.get('error')
    if (!linked && !code) return
    if (linked) {
      notify({ text: t('settings.link.done', { provider }) })
      void refresh()
    } else if (code) {
      setError(t(`errors.${code}`, { defaultValue: t('settings.link.failed') }))
    }
    setParams({ tab: 'signin' }, { replace: true })
  }, [params, setParams, notify, refresh, t, provider])

  async function link() {
    setBusy(true)
    setError(null)
    try {
      const { url } = await api.post<{ url: string }>('/api/oidc/link')
      window.location.assign(url)
    } catch (caught) {
      setError(errorMessage(caught))
      setBusy(false)
    }
  }

  async function unlink() {
    setError(null)
    try {
      await api.delete('/api/oidc/link')
      await refresh()
      notify({ text: t('settings.link.removed') })
    } catch (caught) {
      setError(errorMessage(caught))
    }
  }

  const linked = !!account?.oidc_linked
  return (
    <Section title={t('settings.link.title', { provider })} intro={t('settings.link.lead', { provider })} help={t('settings.link.help', { provider })}>
      {linked ? (
        <div className="flex flex-wrap items-center gap-3">
          <p className="flex flex-1 items-center gap-2 text-sm text-ok-500">
            <Symbol name="check" className="h-4 w-4" />
            {t('settings.link.linked', { provider })}
          </p>
          <Button variant="ghost" size="sm" onClick={() => void unlink()} disabled={!passwordLogin} title={passwordLogin ? undefined : t('settings.link.needPassword')}>
            {t('settings.link.remove')}
          </Button>
        </div>
      ) : (
        <div className="flex flex-col gap-3">
          <p className="text-sm text-mist-300">{t('settings.link.notLinked', { provider })}</p>
          <div>
            <Button onClick={() => void link()} loading={busy}>
              <Symbol name="shield" className="h-4 w-4" />
              {t('settings.link.now', { provider })}
            </Button>
          </div>
        </div>
      )}
      {linked && !passwordLogin && <p className="text-xs text-mist-500">{t('settings.link.needPassword')}</p>}
      {error && <Banner tone="bad">{error}</Banner>}
    </Section>
  )
}
