import { useState } from 'react'
import { useTranslation } from 'react-i18next'

import { api, errorMessage } from '../../api/client'
import type { Priority, Settings, Target, TargetKind } from '../../api/types'
import { useTargets } from '../../lib/data'
import { deviceName } from '../../lib/device'
import { PRIORITY_CHIP } from '../../lib/priority'
import { relative } from '../../lib/time'
import { useLoad } from '../../lib/useLoad'
import { Dialog } from '../Dialog'
import { Explainer } from '../Help'
import { useNotice } from '../Notice'
import { Symbol } from '../Symbol'
import { Badge, Banner, Button, Field, Section, SelectField, Switch } from '../ui'
import { WebPushSignup, type Subscription } from './WebPushSignup'

const KINDS: TargetKind[] = ['webpush', 'ntfy', 'gotify', 'telegram', 'apprise', 'webhook']
const PRIORITIES: Priority[] = ['info', 'warn', 'crit']

interface Draft {
  id?: number
  kind: TargetKind
  name: string
  url: string
  token: string
  chat_id: string
  p256dh: string
  auth: string
  min_priority: Priority
  quiet_from: string
  quiet_to: string
  enabled: boolean
  has_token?: boolean
}

const EMPTY: Draft = { kind: 'webpush', name: deviceName(), url: '', token: '', chat_id: '', p256dh: '', auth: '', min_priority: 'crit', quiet_from: '', quiet_to: '', enabled: true }

/** Where important things go. Each target has a test button, because a push that never arrives is noticed too late. */
export function Targets() {
  const { t, i18n } = useTranslation()
  const notify = useNotice()
  const targets = useTargets()
  const [editing, setEditing] = useState<Draft | null>(null)
  const [testing, setTesting] = useState<number | null>(null)
  const settings = useLoad(() => api.get<Settings>('/api/settings'), [editing])

  async function test(target: Target) {
    setTesting(target.id)
    try {
      const result = await api.post<{ ok: boolean; error?: string }>(`/api/targets/${target.id}/test`)
      notify({ text: result.ok ? t('targets.testOk', { name: target.name }) : t('targets.testFailed', { error: result.error }) })
      void targets.reload()
    } catch (caught) {
      notify({ text: errorMessage(caught) })
    } finally {
      setTesting(null)
    }
  }

  async function switchWebpush(enabled: boolean) {
    try {
      settings.set(await api.put<Settings>('/api/settings', { values: { webpush_enabled: enabled } }))
    } catch (caught) {
      notify({ text: errorMessage(caught) })
    }
  }

  async function toggle(target: Target, enabled: boolean) {
    try {
      await api.put(`/api/targets/${target.id}`, { ...target, token: '', enabled })
      void targets.reload()
    } catch (caught) {
      notify({ text: errorMessage(caught) })
    }
  }

  return (
    <Section
      title={t('targets.title')}
      intro={t('targets.intro')}
      help={t('targets.help')}
      aside={
        <Button variant="ghost" size="sm" onClick={() => setEditing({ ...EMPTY })}>
          <Symbol name="plus" className="h-3.5 w-3.5" />
          {t('targets.add')}
        </Button>
      }
    >
      {targets.data?.length === 0 && <Explainer title={t('targets.noneTitle')}>{t('targets.none')}</Explainer>}
      <ul className="flex flex-col gap-2">
        {targets.data?.map((target) => (
          <li key={target.id} className={'flex flex-wrap items-center gap-3 rounded-xl border border-ink-700 bg-ink-900 p-3 ' + (target.enabled ? '' : 'opacity-55')}>
            <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-accent-500/10 text-accent-400">
              <Symbol name="phone" />
            </span>
            <button type="button" className="min-w-0 flex-1 text-left" onClick={() => setEditing({ ...target, token: '', p256dh: '', auth: '' })} title={t('targets.editHint')}>
              <p className="flex items-center gap-2 text-sm font-medium text-mist-100">
                {target.name}
                <Badge>{t(`targets.kind.${target.kind}`)}</Badge>
              </p>
              <p className="truncate font-mono text-xs text-mist-500">{target.url || (target.chat_id && `chat ${target.chat_id}`)}</p>
              <p className="mt-1 flex flex-wrap gap-1.5 text-xs text-mist-500">
                {t('targets.from')}
                <span className={'rounded-md border px-1.5 py-px ' + PRIORITY_CHIP[target.min_priority]}>{t(`priority.${target.min_priority}`)}</span>
                {target.quiet_from && (
                  <span className="inline-flex items-center gap-1 rounded-md bg-ink-800 px-1.5 py-0.5 text-mist-300">
                    <Symbol name="clock" className="h-3 w-3" />
                    {t('targets.quiet', { from: target.quiet_from, to: target.quiet_to })}
                  </span>
                )}
              </p>
              {target.last_error ? (
                <p className="mt-1 text-xs text-warn-500">{t('targets.lastError', { error: target.last_error })}</p>
              ) : target.last_ok_at ? (
                <p className="mt-1 text-xs text-ok-500">{t('targets.lastOk', { when: relative(target.last_ok_at, i18n.language) })}</p>
              ) : null}
            </button>
            <Button variant="ghost" size="sm" onClick={() => void test(target)} loading={testing === target.id} title={t('targets.testHelp')}>
              {t('targets.test')}
            </Button>
            <Switch label={target.name} checked={target.enabled} onChange={(enabled) => void toggle(target, enabled)} hideLabel />
          </li>
        ))}
      </ul>
      {settings.data && (
        <div className="mt-2 border-t border-ink-700 pt-3">
          <Switch
            label={t('targets.webpush.switch')}
            hint={t('targets.webpush.switchHint')}
            checked={settings.data.webpush_enabled}
            onChange={(value) => void switchWebpush(value)}
            help={t('targets.webpush.switchHelp')}
          />
        </div>
      )}
      {editing && (
        <TargetEditor
          draft={editing}
          onClose={() => setEditing(null)}
          onSaved={() => {
            setEditing(null)
            void targets.reload()
          }}
        />
      )}
    </Section>
  )
}

function TargetEditor({ draft: initial, onClose, onSaved }: { draft: Draft; onClose: () => void; onSaved: () => void }) {
  const { t } = useTranslation()
  const [draft, setDraft] = useState<Draft>(initial)
  const [error, setError] = useState<string | null>(null)
  const [quiet, setQuiet] = useState(!!initial.quiet_from)
  const [confirmDelete, setConfirmDelete] = useState(false)
  const [signedUp, setSignedUp] = useState<Subscription | null>(null)
  const notify = useNotice()
  const set = (patch: Partial<Draft>) => setDraft({ ...draft, ...patch })

  async function save() {
    // The time fields show 23:00 and 07:00 until touched; those are what counts then.
    const body = { ...draft, quiet_from: quiet ? draft.quiet_from || '23:00' : '', quiet_to: quiet ? draft.quiet_to || '07:00' : '' }
    try {
      if (draft.id) await api.put(`/api/targets/${draft.id}`, body)
      else {
        const saved = await api.post<Target>('/api/targets', body)
        // A device just signed up gets its first notification right away: proof that the way works.
        if (saved.kind === 'webpush') {
          const result = await api.post<{ ok: boolean; error?: string }>(`/api/targets/${saved.id}/test`)
          notify({ text: result.ok ? t('targets.webpush.testSent') : t('targets.testFailed', { error: result.error }) })
        }
      }
      onSaved()
    } catch (caught) {
      setError(errorMessage(caught))
    }
  }

  async function remove() {
    if (!draft.id) return
    try {
      await api.delete(`/api/targets/${draft.id}`)
      onSaved()
    } catch (caught) {
      setError(errorMessage(caught))
    }
  }

  const webpush = draft.kind === 'webpush'
  const needsUrl = draft.kind !== 'telegram' && !webpush
  const needsToken = draft.kind === 'gotify' || draft.kind === 'telegram' || draft.kind === 'ntfy'
  const tokenOptional = draft.kind === 'ntfy'

  return (
    <Dialog title={draft.id ? t('targets.edit') : t('targets.new')} onClose={onClose} wide>
      <div className="flex flex-col gap-4">
        <SelectField label={t('targets.kindLabel')} value={draft.kind} onChange={(value) => set({ kind: value as TargetKind })} help={t('targets.kindHelp')}>
          {KINDS.map((kind) => (
            <option key={kind} value={kind}>
              {t(`targets.kind.${kind}`)}
            </option>
          ))}
        </SelectField>
        <Explainer>{t(`targets.how.${draft.kind}`)}</Explainer>
        <Field label={t('targets.name')} value={draft.name} onChange={(event) => set({ name: event.target.value })} placeholder={t('targets.namePlaceholder')} help={t('targets.nameHelp')} />
        {webpush &&
          (draft.id && !signedUp ? (
            <div className="flex flex-wrap items-center gap-3 rounded-xl border border-ink-700 bg-ink-900 p-3.5 text-sm text-mist-300">
              <span className="flex-1">{t('targets.webpush.signedUp', { host: draft.url })}</span>
              <Button variant="ghost" size="sm" onClick={() => setSignedUp({ url: '', p256dh: '', auth: '' })}>
                {t('targets.webpush.again')}
              </Button>
            </div>
          ) : (
            <WebPushSignup
              done={signedUp?.url ? signedUp : null}
              onSignedUp={(subscription) => {
                setSignedUp(subscription)
                set(subscription)
              }}
            />
          ))}
        {needsUrl && (
          <Field label={t(`targets.url.${draft.kind}`)} value={draft.url} onChange={(event) => set({ url: event.target.value })} placeholder={t(`targets.urlExample.${draft.kind}`)} help={t(`targets.urlHelp.${draft.kind}`)} />
        )}
        {needsToken && (
          <Field
            label={t(`targets.token.${draft.kind}`)}
            type="password"
            autoComplete="off"
            value={draft.token}
            onChange={(event) => set({ token: event.target.value })}
            placeholder={draft.has_token ? t('targets.tokenKept') : tokenOptional ? t('targets.optional') : ''}
            help={t(`targets.tokenHelp.${draft.kind}`)}
          />
        )}
        {draft.kind === 'telegram' && <Field label={t('targets.chatId')} value={draft.chat_id} onChange={(event) => set({ chat_id: event.target.value })} help={t('targets.chatIdHelp')} />}
        <SelectField label={t('targets.minPriority')} value={draft.min_priority} onChange={(value) => set({ min_priority: value as Priority })} help={t('targets.minPriorityHelp')}>
          {PRIORITIES.map((priority) => (
            <option key={priority} value={priority}>
              {t(`targets.fromPriority.${priority}`)}
            </option>
          ))}
        </SelectField>
        <div className="flex flex-col gap-3 rounded-xl border border-ink-700 bg-ink-900 p-3">
          <Switch label={t('targets.quietTitle')} hint={t('targets.quietHint')} checked={quiet} onChange={setQuiet} help={t('targets.quietHelp')} />
          {quiet && (
            <div className="grid grid-cols-2 gap-3">
              <Field label={t('targets.quietFrom')} type="time" value={draft.quiet_from || '23:00'} onChange={(event) => set({ quiet_from: event.target.value })} />
              <Field label={t('targets.quietTo')} type="time" value={draft.quiet_to || '07:00'} onChange={(event) => set({ quiet_to: event.target.value })} />
            </div>
          )}
        </div>
        {error && <Banner tone="bad">{error}</Banner>}
        <div className="flex flex-wrap items-center justify-between gap-2">
          {draft.id ? (
            confirmDelete ? (
              <Button variant="danger" size="sm" onClick={() => void remove()}>
                {t('targets.confirmDelete')}
              </Button>
            ) : (
              <Button variant="ghost" size="sm" onClick={() => setConfirmDelete(true)}>
                <Symbol name="trash" className="h-3.5 w-3.5" />
                {t('targets.delete')}
              </Button>
            )
          ) : (
            <span />
          )}
          <div className="flex gap-2">
            <Button variant="ghost" onClick={onClose}>
              {t('common.cancel')}
            </Button>
            <Button onClick={() => void save()} disabled={!draft.name.trim() || (webpush && !draft.id && !signedUp?.url)}>
              {t('common.save')}
            </Button>
          </div>
        </div>
      </div>
    </Dialog>
  )
}
