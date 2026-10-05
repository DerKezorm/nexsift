/**
 * About nexsift, built like nexlore's: version, licence, where it comes from, whether a newer one is out, what goes
 * out to other servers, and what it is built with. nexsift's own additions: every "What's new" so far, and the way
 * back in without a password.
 *
 * The switches for the two calls nexsift makes by itself stand here, next to the sentence that says what goes out:
 * the daily question to GitHub, and fetching logos.
 */
import { useState, type ReactNode } from 'react'
import { useTranslation } from 'react-i18next'

import { api, errorMessage } from '../api/client'
import type { About, Settings, Updates } from '../api/types'
import { Explainer } from '../components/Help'
import { Logo } from '../components/Logo'
import { Symbol, type SymbolName } from '../components/Symbol'
import { WhatsNewDialog } from '../components/WhatsNewDialog'
import { Banner, Button, Card, Spinner, Switch } from '../components/ui'
import { useLoad } from '../lib/useLoad'
import { allVersions, entryFor } from '../lib/whatsnew'

const PARTS = [
  { name: 'FastAPI', url: 'https://fastapi.tiangolo.com', licence: 'MIT' },
  { name: 'SQLAlchemy', url: 'https://www.sqlalchemy.org', licence: 'MIT' },
  { name: 'SQLite', url: 'https://sqlite.org', licence: 'Public Domain' },
  { name: 'HTTPX', url: 'https://www.python-httpx.org', licence: 'BSD-3' },
  { name: 'aiosmtpd', url: 'https://github.com/aio-libs/aiosmtpd', licence: 'Apache-2.0' },
  { name: 'argon2-cffi', url: 'https://github.com/hynek/argon2-cffi', licence: 'MIT' },
  { name: 'PyJWT', url: 'https://github.com/jpadilla/pyjwt', licence: 'MIT' },
  { name: 'pyzipper', url: 'https://github.com/danifus/pyzipper', licence: 'MIT' },
  { name: 'React', url: 'https://react.dev', licence: 'MIT' },
  { name: 'Vite', url: 'https://vite.dev', licence: 'MIT' },
  { name: 'Tailwind CSS', url: 'https://tailwindcss.com', licence: 'MIT' },
  { name: 'i18next', url: 'https://www.i18next.com', licence: 'MIT' },
]

/** The logo collections the picker offers; selfh.st asks to be named (CC BY 4.0). */
const LOGOS = [
  { name: 'Dashboard Icons', url: 'https://github.com/homarr-labs/dashboard-icons', licence: 'Apache-2.0' },
  { name: 'selfh.st/icons', url: 'https://selfh.st/icons/', licence: 'CC BY 4.0' },
]

function Out({ href, children }: { href: string; children: ReactNode }) {
  return (
    <a href={href} target="_blank" rel="noreferrer noopener" className="text-accent-400 underline decoration-accent-500/40 underline-offset-4 hover:decoration-accent-400">
      {children}
    </a>
  )
}

function Row({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="flex flex-wrap items-baseline justify-between gap-x-6 gap-y-1 border-b border-ink-700/60 py-2.5 last:border-b-0">
      <dt className="text-sm text-mist-500">{label}</dt>
      <dd className="text-sm font-medium text-mist-100">{children}</dd>
    </div>
  )
}

function CardTitle({ symbol, title, text }: { symbol: SymbolName; title: string; text?: string }) {
  return (
    <div className="mb-4">
      <h2 className="flex items-center gap-2 text-lg font-semibold">
        <Symbol name={symbol} className="h-4 w-4 text-mist-400" />
        {title}
      </h2>
      {text && <p className="mt-1 text-sm text-mist-500">{text}</p>}
    </div>
  )
}

export function AboutPage() {
  const { t, i18n } = useTranslation()
  const about = useLoad(() => api.get<About>('/api/about'), [])
  // A side matter: when the answer does not come, the page simply shows none.
  const updates = useLoad(() => api.get<Updates>('/api/about/updates').catch(() => null), [])
  const settings = useLoad(() => api.get<Settings>('/api/settings'), [])
  const [reading, setReading] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [problem, setProblem] = useState<string | null>(null)

  async function checkNow() {
    setBusy(true)
    try {
      updates.set(await api.post<Updates>('/api/about/updates/check'))
      setProblem(null)
    } catch (caught) {
      setProblem(errorMessage(caught))
    } finally {
      setBusy(false)
    }
  }

  async function switchCheck(on: boolean) {
    if (updates.data) updates.set({ ...updates.data, update_check: on })
    try {
      updates.set(await api.put<Updates>('/api/about/updates', { update_check: on }))
    } catch (caught) {
      setProblem(errorMessage(caught))
      void updates.reload()
    }
  }

  async function switchIcons(on: boolean) {
    try {
      settings.set(await api.put<Settings>('/api/settings', { values: { icons_from_web: on } }))
    } catch (caught) {
      setProblem(errorMessage(caught))
    }
  }

  if (!about.data) return about.error ? <Banner tone="bad">{about.error}</Banner> : <Spinner />
  const facts = about.data
  const state = updates.data
  const latest = state?.latest?.replace(/^v/, '')
  const versions = allVersions(facts.version)
  const entry = reading ? entryFor(reading, i18n.language) : null

  return (
    <div className="flex max-w-3xl flex-col gap-6">
      <div className="flex items-center gap-4">
        <Logo className="h-14 w-14" />
        <div>
          <h1 className="text-2xl font-bold tracking-tight">
            <span className="text-mist-500">NEX</span>
            <span className="text-accent-300">SIFT</span>
          </h1>
          <p className="text-sm text-mist-500">{t('about.tagline')}</p>
        </div>
      </div>

      {problem && <Banner tone="bad">{problem}</Banner>}

      <dl className="rounded-2xl border border-ink-700 bg-ink-850/80 px-5 py-2" data-testid="about-facts">
        <Row label={t('about.version')}>
          <span className="flex flex-wrap items-center gap-2">
            <span className="tabular-nums" data-testid="about-version">
              {facts.version}
            </span>
            {state?.newer && <span className="rounded-full bg-accent-500/15 px-2 py-0.5 text-xs font-semibold text-accent-400">{t('about.newer', { version: latest })}</span>}
            {versions[0] && (
              <Button variant="ghost" size="sm" onClick={() => setReading(versions[0])}>
                {t('about.whatsNew', { version: versions[0] })}
              </Button>
            )}
          </span>
        </Row>
        <Row label={t('about.licence')}>
          <Out href="https://www.gnu.org/licenses/agpl-3.0.html">{facts.license}</Out>
        </Row>
        <Row label={t('about.source')}>
          <Out href={facts.repo_url}>{facts.repo_url.replace(/^https:\/\//, '')}</Out>
        </Row>
        <Row label={t('about.releases')}>
          <Out href={facts.releases_url}>{t('about.releasesLink')}</Out>
        </Row>
        {facts.project_url && (
          <Row label={t('about.project')}>
            <Out href={facts.project_url}>{facts.project_url.replace(/^https:\/\//, '')}</Out>
          </Row>
        )}
        <Row label={t('about.report')}>
          <Out href={`${facts.repo_url}/issues/new`}>{t('about.reportLink')}</Out>
        </Row>
      </dl>

      <Card>
        <CardTitle symbol="refresh" title={t('about.updates.title')} text={t('about.updates.text')} />
        <div className="flex flex-col gap-4">
          {state && <Switch label={t('about.updates.daily')} hint={t('about.updates.dailyHint')} checked={state.update_check} onChange={(on) => void switchCheck(on)} />}
          <div className="flex flex-wrap items-center gap-x-4 gap-y-2 text-sm" aria-live="polite">
            <Button size="sm" onClick={() => void checkNow()} loading={busy}>
              {t('about.updates.now')}
            </Button>
            <span data-testid="about-update-state" className="text-mist-400">
              {!state || !state.checked ? (
                state && !state.update_check ? t('about.updates.off') : t('about.updates.notYet')
              ) : state.newer ? (
                <>
                  {t('about.newer', { version: latest })}
                  {state.release_url && (
                    <>
                      {' · '}
                      <Out href={state.release_url}>{t('about.updates.toRelease')}</Out>
                    </>
                  )}
                </>
              ) : state.latest ? (
                t('about.updates.current')
              ) : (
                t('about.updates.none')
              )}
            </span>
            {state?.checked_at && <span className="text-xs text-mist-500">{t('about.updates.checkedAt', { when: new Date(state.checked_at).toLocaleString(i18n.language) })}</span>}
          </div>
          <p className="text-xs leading-relaxed text-mist-500">{t('about.updates.whatGoesOut')}</p>
        </div>
      </Card>

      <Card>
        <CardTitle symbol="external" title={t('about.outside.title')} text={t('about.outside.text')} />
        <ul className="flex flex-col divide-y divide-ink-700">
          <li className="py-3 text-sm">
            <p className="font-medium text-mist-100">{t('about.outside.updatesTitle')}</p>
            <p className="mt-0.5 text-mist-500">{t('about.outside.updates')}</p>
          </li>
          <li className="flex flex-col gap-3 py-3 text-sm">
            <div>
              <p className="font-medium text-mist-100">{t('about.outside.logosTitle')}</p>
              <p className="mt-0.5 text-mist-500">{t('about.outside.logos')}</p>
            </div>
            {settings.data && (
              <Switch label={t('about.outside.logosSwitch')} hint={t('about.outside.logosSwitchHint')} checked={settings.data.icons_from_web} onChange={(on) => void switchIcons(on)} />
            )}
          </li>
          <li className="py-3 text-sm">
            <p className="font-medium text-mist-100">{t('about.outside.phoneTitle')}</p>
            <p className="mt-0.5 text-mist-500">{t('about.outside.phone')}</p>
          </li>
          <li className="py-3 text-sm">
            <p className="font-medium text-mist-100">{t('about.outside.pushTitle')}</p>
            <p className="mt-0.5 text-mist-500">{t('about.outside.push')}</p>
          </li>
        </ul>
      </Card>

      {versions.length > 1 && (
        <Card>
          <CardTitle symbol="info" title={t('about.historyTitle')} text={t('about.historyLead')} />
          <ul className="flex flex-col divide-y divide-ink-700">
            {versions.map((version) => (
              <li key={version} className="flex items-center gap-3 py-2.5">
                <span className="w-16 font-mono text-sm text-mist-300 tabular-nums">{version}</span>
                <span className="min-w-0 flex-1 truncate text-sm text-mist-500">{entryFor(version, i18n.language)?.lead}</span>
                <Button variant="ghost" size="sm" onClick={() => setReading(version)}>
                  {t('about.read')}
                </Button>
              </li>
            ))}
          </ul>
        </Card>
      )}

      <Card>
        <CardTitle symbol="code" title={t('about.builtWith')} />
        <ul className="flex flex-wrap gap-x-3 gap-y-1.5 text-sm">
          {PARTS.map((part) => (
            <li key={part.name}>
              <Out href={part.url}>{part.name}</Out>
              <span className="ml-1 text-xs text-mist-500">({part.licence})</span>
            </li>
          ))}
        </ul>
        <p className="mt-4 text-sm text-mist-500">{t('about.logosFrom')}</p>
        <ul className="mt-1.5 flex flex-wrap gap-x-3 gap-y-1.5 text-sm">
          {LOGOS.map((part) => (
            <li key={part.name}>
              <Out href={part.url}>{part.name}</Out>
              <span className="ml-1 text-xs text-mist-500">({part.licence})</span>
            </li>
          ))}
        </ul>
      </Card>

      <Explainer title={t('about.resetTitle')}>
        {t('about.reset')}
        <code className="mt-1 block font-mono text-xs break-all text-mist-200">docker exec -it nexsift python -m app.reset_password</code>
      </Explainer>

      {reading && entry && <WhatsNewDialog version={reading} entry={entry} onClose={() => setReading(null)} />}
    </div>
  )
}
