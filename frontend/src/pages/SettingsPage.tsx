import { useState, type ChangeEvent } from 'react'
import { useTranslation } from 'react-i18next'
import { useSearchParams } from 'react-router-dom'

import { api, errorMessage } from '../api/client'
import type { Settings } from '../api/types'
import { useAuth } from '../auth'
import { AddressChangeQuestion } from '../components/AddressChange'
import { useNotice } from '../components/Notice'
import { TabRow } from '../components/TabRow'
import { Banner, Button, Field, PageHeader, Section } from '../components/ui'
import { addressQuestion, type AddressQuestion } from '../lib/addressQuestion'
import { useLoad } from '../lib/useLoad'
import { ApiKeysTab } from './settings/ApiKeysTab'
import { BackupTab } from './settings/BackupTab'
import { Languages } from './settings/Languages'
import { LogTab } from './settings/LogTab'
import { MyProviders } from './settings/MyProviders'
import { SignInPart } from './settings/SignInCards'

const TABS = ['account', 'signin', 'addresses', 'retention', 'backup', 'log', 'api', 'languages'] as const
type Tab = (typeof TABS)[number]

function isTab(value: string | null): value is Tab {
  return (TABS as readonly string[]).includes(value ?? '')
}

export function SettingsPage() {
  const { t } = useTranslation()
  const settings = useLoad(() => api.get<Settings>('/api/settings'), [])
  // The tab is in the address (`?tab=addresses`), so other pages can link straight to it.
  const [params, setParams] = useSearchParams()
  const wanted = params.get('tab')
  const tab: Tab = isTab(wanted) ? wanted : 'account'
  const tabs = TABS.map((value) => ({ value, label: t(`settings.tab.${value}`) }))
  return (
    <div className="flex flex-col gap-6">
      <PageHeader title={t('settings.title')} lead={t('settings.lead')} />
      <TabRow tabs={tabs} active={tab} onChange={(value) => setParams(value === 'account' ? {} : { tab: value }, { replace: true })} label={t('settings.title')} />
      <div className={tab === 'log' ? 'max-w-5xl' : 'max-w-3xl'}>
        {tab === 'account' && (
          <div className="flex flex-col gap-6">
            <AccountSection />
            <MyProviders settings={settings.data} />
          </div>
        )}
        {tab === 'signin' && settings.data && <SignInPart settings={settings.data} onSaved={settings.set} />}
        {tab === 'addresses' && settings.data && <Addresses settings={settings.data} onSaved={settings.set} />}
        {tab === 'retention' && settings.data && <Retention settings={settings.data} onSaved={settings.set} />}
        {tab === 'backup' && <BackupTab onSettings={settings.set} />}
        {tab === 'log' && <LogTab />}
        {tab === 'api' && settings.data && <ApiKeysTab settings={settings.data} onSettings={settings.set} />}
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

/** The addresses: how the browser reaches nexsift, and how the devices at home do. The public address is also on the
 * sign-in tab (shared sign-in blueprint, card 1); both edit the same setting. */
function Addresses({ settings, onSaved }: { settings: Settings; onSaved: (settings: Settings) => void }) {
  const { t } = useTranslation()
  const notify = useNotice()
  const [publicUrl, setPublicUrl] = useState(settings.public_url)
  const [senderHost, setSenderHost] = useState(settings.sender_host)
  const [error, setError] = useState<string | null>(null)
  // A changed public address may leave authentik knowing the old redirect address: the server asks first (409).
  const [asked, setAsked] = useState<{ values: Partial<Settings>; question: AddressQuestion } | null>(null)

  async function save(values: Partial<Settings>, confirmed = false) {
    setError(null)
    try {
      const saved = await api.put<Settings>('/api/settings', { values, ...(confirmed ? { confirm_public_url: true } : {}) })
      setAsked(null)
      onSaved(saved)
      // The server tidies addresses up (a pasted http:// goes); the fields show what was stored.
      setPublicUrl(saved.public_url)
      setSenderHost(saved.sender_host)
      notify({ text: t('common.saved') })
    } catch (caught) {
      const question = addressQuestion(caught)
      if (question) setAsked({ values, question })
      else setError(errorMessage(caught))
    }
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
      {asked && (
        <AddressChangeQuestion
          question={asked.question}
          onCancel={() => {
            setAsked(null)
            setPublicUrl(settings.public_url)
          }}
          onConfirm={() => void save(asked.values, true)}
        />
      )}
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

