import { useState } from 'react'
import { useTranslation } from 'react-i18next'

import { api, errorMessage } from '../../api/client'
import type { ApiKeyCreated, ApiKeyList, Settings } from '../../api/types'
import { CopyField } from '../../components/CopyField'
import { Dialog } from '../../components/Dialog'
import { Help } from '../../components/Help'
import { useNotice } from '../../components/Notice'
import { Symbol } from '../../components/Symbol'
import { Banner, Button, Field, Section, Switch } from '../../components/ui'
import { relative } from '../../lib/time'
import { useLoad } from '../../lib/useLoad'

const ADDRESSES = ['status', 'threads'] as const

/**
 * Read-only keys for dashboards such as nexdeck, behind the operator's switch. Taken over from nextrmnl.
 *
 * The key is shown once, right after it is made: nexsift keeps only its hash, and the dialog says so.
 */
export function ApiKeysTab({ settings, onSettings }: { settings: Settings; onSettings: (settings: Settings) => void }) {
  const { t, i18n } = useTranslation()
  const notify = useNotice()
  const keys = useLoad(() => api.get<ApiKeyList>('/api/api-keys'), [])
  const [name, setName] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [created, setCreated] = useState<ApiKeyCreated | null>(null)
  const [removing, setRemoving] = useState<{ id: number; name: string } | null>(null)
  const origin = window.location.origin

  async function toggle(value: boolean) {
    try {
      onSettings(await api.put<Settings>('/api/settings', { values: { api_keys_allowed: value } }))
      notify({ text: t('common.saved') })
    } catch (caught) {
      notify({ text: errorMessage(caught) })
    }
  }

  async function create() {
    setBusy(true)
    setError(null)
    try {
      setCreated(await api.post<ApiKeyCreated>('/api/api-keys', { name: name.trim() }))
      setName('')
      await keys.reload()
    } catch (caught) {
      setError(errorMessage(caught))
    } finally {
      setBusy(false)
    }
  }

  async function remove() {
    if (!removing) return
    setBusy(true)
    try {
      await api.delete(`/api/api-keys/${removing.id}`)
      setRemoving(null)
      await keys.reload()
    } catch (caught) {
      setError(errorMessage(caught))
    } finally {
      setBusy(false)
    }
  }

  const list = keys.data?.keys ?? []

  return (
    <div className="flex flex-col gap-6">
      <Section title={t('apiKeys.title')} intro={t('apiKeys.lead')} help={t('apiKeys.help')}>
        <Switch label={t('apiKeys.allow')} hint={t('apiKeys.allowHint')} checked={settings.api_keys_allowed} onChange={(value) => void toggle(value)} help={t('apiKeys.allowHelp')} />
        {!settings.api_keys_allowed && list.length > 0 && <Banner tone="warn">{t('apiKeys.offNote')}</Banner>}
      </Section>

      <Section title={t('apiKeys.listTitle')} intro={t('apiKeys.listIntro')} help={t('apiKeys.listHelp')}>
        {keys.error && <Banner tone="bad">{keys.error}</Banner>}
        {list.length === 0 ? (
          <p className="text-sm text-mist-500">{t('apiKeys.empty')}</p>
        ) : (
          <ul className="flex flex-col divide-y divide-ink-800 rounded-xl border border-ink-700">
            {list.map((key) => (
              <li key={key.id} className="flex items-center gap-3 px-3 py-2">
                <Symbol name="key" className="h-4 w-4 shrink-0 text-mist-500" />
                <div className="min-w-0 flex-1">
                  <div className="truncate text-sm text-mist-100">{key.name}</div>
                  <div className="truncate text-xs text-mist-500">
                    <code className="font-mono">{key.prefix}…</code> · {t('apiKeys.made', { when: relative(key.created_at, i18n.language) })} ·{' '}
                    {key.last_used_at ? t('apiKeys.lastUsed', { when: relative(key.last_used_at, i18n.language) }) : t('apiKeys.neverUsed')}
                  </div>
                </div>
                <Button variant="ghost" size="sm" onClick={() => setRemoving({ id: key.id, name: key.name })} aria-label={t('apiKeys.deleteOne', { name: key.name })}>
                  {t('apiKeys.delete')}
                </Button>
              </li>
            ))}
          </ul>
        )}
        <form
          className="flex flex-col gap-2 sm:flex-row sm:items-end"
          onSubmit={(event) => {
            event.preventDefault()
            if (name.trim()) void create()
          }}
        >
          <div className="flex-1">
            <Field label={t('apiKeys.name')} placeholder="nexdeck" maxLength={64} value={name} onChange={(event) => setName(event.target.value)} help={t('apiKeys.nameHelp')} />
          </div>
          <Button type="submit" variant="ghost" loading={busy} disabled={!name.trim()}>
            <Symbol name="plus" className="h-3.5 w-3.5" />
            {t('apiKeys.create')}
          </Button>
        </form>
        {error && <Banner tone="bad">{error}</Banner>}
      </Section>

      <Section title={t('apiKeys.useTitle')} intro={t('apiKeys.useIntro')} help={t('apiKeys.useHelp')}>
        <dl className="flex flex-col gap-3">
          {ADDRESSES.map((address) => (
            <div key={address} className="flex flex-col gap-1">
              <dt className="flex items-center gap-1.5 text-sm font-medium text-mist-200">
                <code className="font-mono text-xs">GET /api/v1/{address}</code>
                <Help label={`/api/v1/${address}`}>{t(`apiKeys.address.${address}Help`)}</Help>
              </dt>
              <dd className="text-xs text-mist-500">{t(`apiKeys.address.${address}`)}</dd>
            </div>
          ))}
        </dl>
        <CopyField label={t('apiKeys.example')} value={`curl -H "Authorization: Bearer nxs_…" ${origin}/api/v1/status`} />
      </Section>

      {created && (
        <Dialog title={t('apiKeys.createdTitle')} onClose={() => setCreated(null)}>
          <div className="flex flex-col gap-4">
            <p className="text-sm text-mist-300">{t('apiKeys.createdLead', { name: created.name })}</p>
            <CopyField value={created.key} />
            <Banner tone="warn">{t('apiKeys.createdWarning')}</Banner>
            {!settings.api_keys_allowed && <Banner tone="info">{t('apiKeys.createdButOff')}</Banner>}
            <div className="flex justify-end">
              <Button onClick={() => setCreated(null)}>{t('common.done')}</Button>
            </div>
          </div>
        </Dialog>
      )}

      {removing && (
        <Dialog title={t('apiKeys.deleteTitle', { name: removing.name })} onClose={() => setRemoving(null)}>
          <div className="flex flex-col gap-4">
            <Banner tone="warn">{t('apiKeys.deleteText')}</Banner>
            <div className="flex justify-end gap-2">
              <Button variant="ghost" onClick={() => setRemoving(null)}>
                {t('common.cancel')}
              </Button>
              <Button variant="danger" loading={busy} onClick={() => void remove()}>
                {t('apiKeys.deleteNow')}
              </Button>
            </div>
          </div>
        </Dialog>
      )}
    </div>
  )
}
