import { useState } from 'react'
import { useTranslation } from 'react-i18next'

import { api } from '../api/client'
import type { About } from '../api/types'
import { Explainer } from '../components/Help'
import { Logo } from '../components/Logo'
import { Symbol } from '../components/Symbol'
import { WhatsNewDialog } from '../components/WhatsNewDialog'
import { Banner, Button, Card, PageHeader, Spinner } from '../components/ui'
import { useLoad } from '../lib/useLoad'
import { allVersions, entryFor } from '../lib/whatsnew'

const REPO = 'https://github.com/DerKezorm/nexsift'

function External({ href, children }: { href: string; children: string }) {
  return (
    <a href={href} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 text-sm text-accent-400 hover:underline">
      {children}
      <Symbol name="external" className="h-3.5 w-3.5" />
    </a>
  )
}

/** Version, license, where the code lives, every "What's new" so far, and the way back in without a password. */
export function AboutPage() {
  const { t, i18n } = useTranslation()
  const about = useLoad(() => api.get<About>('/api/about'), [])
  const [reading, setReading] = useState<string | null>(null)

  if (!about.data) return about.error ? <Banner tone="bad">{about.error}</Banner> : <Spinner />
  const versions = allVersions(about.data.version)
  const entry = reading ? entryFor(reading, i18n.language) : null

  return (
    <div className="flex max-w-3xl flex-col gap-6">
      <PageHeader title={t('about.title')} />
      <Card>
        <div className="flex flex-wrap items-center gap-4">
          <Logo className="h-14 w-14" />
          <div>
            <p className="text-2xl font-bold tracking-tight">
              <span className="text-mist-500">NEX</span>
              <span className="text-accent-300">SIFT</span> <span className="text-base font-medium text-mist-500 tabular-nums">v{about.data.version}</span>
            </p>
            <p className="text-sm text-mist-500">{t('about.tagline')}</p>
          </div>
        </div>
        <div className="mt-5 flex flex-col gap-3 border-t border-ink-700 pt-4">
          <div className="flex flex-wrap items-center gap-x-5 gap-y-2">
            {versions[0] && (
              <Button variant="ghost" size="sm" onClick={() => setReading(versions[0])}>
                <Symbol name="info" className="h-3.5 w-3.5" />
                {t('about.whatsNew', { version: versions[0] })}
              </Button>
            )}
            <External href={REPO}>GitHub</External>
            <External href={`${REPO}/releases`}>{t('about.releases')}</External>
          </div>
          <p className="text-xs text-mist-600">{t('about.license')}</p>
        </div>
      </Card>

      {versions.length > 1 && (
        <Card>
          <h2 className="text-lg font-semibold">{t('about.historyTitle')}</h2>
          <p className="mt-1 text-sm text-mist-500">{t('about.historyLead')}</p>
          <ul className="mt-4 flex flex-col divide-y divide-ink-700">
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

      <Explainer title={t('about.resetTitle')}>
        {t('about.reset')}
        <code className="mt-1 block font-mono text-xs break-all text-mist-200">docker exec -it nexsift python -m app.reset_password</code>
      </Explainer>

      {reading && entry && <WhatsNewDialog version={reading} entry={entry} onClose={() => setReading(null)} />}
    </div>
  )
}
