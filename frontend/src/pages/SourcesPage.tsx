import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link, useSearchParams } from 'react-router-dom'

import { api, errorMessage } from '../api/client'
import type { About, Preset, Source, SourceWithConnection, Stranger } from '../api/types'
import { CopyField } from '../components/CopyField'
import { Dialog } from '../components/Dialog'
import { Explainer, Help } from '../components/Help'
import { useNotice } from '../components/Notice'
import { SourceMark } from '../components/SourceMark'
import { Symbol } from '../components/Symbol'
import { Badge, Banner, Button, Card, Field, PageHeader, Spinner } from '../components/ui'
import { isMuted, useSources } from '../lib/data'
import { useLiveVersion } from '../lib/live'
import { presetOf, setupLines } from '../lib/setup'
import { relative, useNow } from '../lib/time'
import { useLoad } from '../lib/useLoad'

/** Senders nexsift knows by name: the setup follows their own settings page, their messages are understood. */
const KNOWN = ['proxmox', 'synology', 'uptimekuma', 'watchtower', 'homeassistant', 'paperless']
/** Everything else goes by what the device offers, the most capable way first. */
const WAYS = ['webhook', 'email', 'syslog', 'ntfy', 'gotify', 'discord']

export function SourcesPage() {
  const { t, i18n } = useTranslation()
  const sources = useSources()
  const now = useNow()
  const [params, setParams] = useSearchParams()
  const [adding, setAdding] = useState<{ preset?: string; key?: string; hostname?: string } | null>(params.get('add') ? {} : null)
  const [showing, setShowing] = useState<number | null>(null)
  const strangersVersion = useLiveVersion(['strangers', 'source'])
  const strangers = useLoad(() => api.get<Stranger[]>('/api/sources/strangers'), [strangersVersion])
  const about = useLoad(() => api.get<About>('/api/about'), [])

  function closeAdd() {
    setAdding(null)
    if (params.get('add')) setParams({}, { replace: true })
  }

  return (
    <>
      <PageHeader
        title={t('sources.title')}
        lead={t('sources.lead')}
        aside={
          <Button onClick={() => setAdding({})}>
            <Symbol name="plus" />
            {t('sources.add')}
          </Button>
        }
      />

      <div className="grid gap-6 lg:grid-cols-[1fr_20rem]">
        <div className="flex flex-col gap-4">
          <Explainer title={t('sources.explainTitle')}>{t('sources.explain')}</Explainer>

          {(strangers.data?.length ?? 0) > 0 && (
            <Card className="flex flex-col gap-3 border-warn-500/40">
              <h2 className="flex items-center gap-2 font-semibold">
                <Symbol name="bell" className="h-4 w-4 text-warn-500" />
                {t('sources.strangers.title')}
                <Help label={t('sources.strangers.title')}>{t('sources.strangers.help')}</Help>
              </h2>
              <ul className="flex flex-col gap-2">
                {strangers.data?.map((stranger) => (
                  <li key={`${stranger.protocol}:${stranger.key}`} className="flex flex-wrap items-center gap-3 rounded-xl border border-ink-700 bg-ink-900 p-3">
                    <div className="min-w-0 flex-1">
                      <p className="text-sm text-mist-100">
                        {t(`sources.strangers.${stranger.protocol}`, { key: stranger.key })}
                        <span className="ml-2 text-xs text-mist-500">{t('sources.strangers.count', { count: stranger.count })}</span>
                      </p>
                      <p className="truncate font-mono text-xs text-mist-500">
                        {stranger.peer && `${stranger.peer} · `}
                        {stranger.sample}
                      </p>
                    </div>
                    <Button
                      size="sm"
                      onClick={() =>
                        setAdding(
                          stranger.protocol === 'syslog'
                            ? { preset: 'syslog', hostname: stranger.key }
                            : { preset: stranger.protocol === 'smtp' ? 'email' : 'ntfy', key: stranger.key },
                        )
                      }
                    >
                      {t('sources.strangers.create')}
                    </Button>
                  </li>
                ))}
              </ul>
            </Card>
          )}

          {sources.data?.length === 0 && (
            <div className="rounded-2xl border border-dashed border-ink-700 px-6 py-10 text-center">
              <p className="font-semibold text-mist-200">{t('sources.none')}</p>
              <p className="mt-1 text-sm text-mist-500">{t('sources.noneHint')}</p>
              <Button className="mt-4" onClick={() => setAdding({})}>
                <Symbol name="plus" />
                {t('sources.add')}
              </Button>
            </div>
          )}

          <ul className="grid content-start gap-3 sm:grid-cols-2">
            {sources.data?.map((source) => (
              <SourceCard key={source.id} source={source} now={now} language={i18n.language} onShow={() => setShowing(source.id)} />
            ))}
          </ul>
        </div>

        <Card className="flex h-fit flex-col gap-4">
          <div>
            <h2 className="flex items-center gap-2 text-lg font-semibold">
              {t('sources.ports.title')}
              <Help label={t('sources.ports.title')}>{t('sources.ports.help')}</Help>
            </h2>
            <p className="mt-1 text-sm text-mist-500">{t('sources.ports.lead')}</p>
          </div>
          <ul className="flex flex-col divide-y divide-ink-700">
            {(['web', 'gotify', 'ntfy', 'smtp', 'syslog'] as const).map((door) => {
              const open = door === 'web' || about.data?.doors[door] !== false
              return (
                <li key={door} className="flex items-center gap-3 py-2.5 text-sm">
                  <span className="w-12 shrink-0 font-mono text-mist-100 tabular-nums">{about.data?.ports[door] ?? ''}</span>
                  <span className={'min-w-0 flex-1 ' + (open ? 'text-mist-300' : 'text-mist-600 line-through')}>{t(`sources.ports.${door}`)}</span>
                </li>
              )
            })}
          </ul>
          <Banner tone="warn">{t('sources.ports.discord')}</Banner>
        </Card>
      </div>

      {adding && <AddSource initial={adding} onClose={closeAdd} />}
      {showing !== null && <SetupDialog id={showing} onClose={() => setShowing(null)} />}
    </>
  )
}

function SourceCard({ source, now, language, onShow }: { source: Source; now: number; language: string; onShow: () => void }) {
  const { t } = useTranslation()
  const notify = useNotice()
  const muted = isMuted(source, now)
  const [editing, setEditing] = useState(false)
  const [deleting, setDeleting] = useState(false)

  async function test() {
    try {
      await api.post(`/api/sources/${source.id}/test`)
      notify({ text: t('sources.testSent') })
    } catch (caught) {
      notify({ text: errorMessage(caught) })
    }
  }

  async function mute(minutes: number) {
    try {
      await api.post(`/api/sources/${source.id}/mute`, { minutes })
    } catch (caught) {
      notify({ text: errorMessage(caught) })
    }
  }

  return (
    <li className="flex flex-col gap-3 rounded-2xl border border-ink-700 bg-ink-850/80 p-4">
      <div className="flex items-start gap-3">
        <SourceMark kind={source.kind} protocol={source.protocol} className="h-10 w-10 text-xs" />
        <div className="min-w-0 flex-1">
          <p className="truncate font-semibold text-mist-100">{source.name}</p>
          <p className="text-xs text-mist-500">{t(`sources.preset.${presetOf(source.kind, source.protocol)}.name`)}</p>
        </div>
        <Badge tone="neutral">{t(`protocol.${source.protocol}`)}</Badge>
      </div>

      {source.last_seen_at === null ? (
        <p className="flex items-start gap-2 rounded-lg bg-ink-900 px-2.5 py-2 text-xs text-mist-400">
          <Symbol name="clock" className="mt-px h-3.5 w-3.5 shrink-0" />
          {t('sources.neverHeard')}
        </p>
      ) : (
        <dl className="grid grid-cols-2 gap-2 text-xs">
          <div>
            <dt className="text-mist-600">{t('sources.lastSeen')}</dt>
            <dd className="text-mist-300 tabular-nums">{relative(source.last_seen_at, language, now)}</dd>
          </div>
          <div>
            <dt className="text-mist-600">{t('sources.countTotal')}</dt>
            <dd className="text-mist-300 tabular-nums">{source.count_total}</dd>
          </div>
        </dl>
      )}

      {source.unrecognized_streak > 0 && (
        <Banner tone="warn">
          {t('sources.unrecognized', { count: source.unrecognized_streak })}{' '}
          <Help label={t('sources.unrecognizedTitle')}>{t('sources.unrecognizedHelp')}</Help>
        </Banner>
      )}

      <div className="mt-auto flex flex-wrap items-center gap-2">
        <Button size="sm" onClick={onShow}>
          <Symbol name="code" className="h-3.5 w-3.5" />
          {t('sources.setup')}
        </Button>
        <Button variant="ghost" size="sm" onClick={() => void test()} title={t('sources.testHelp')}>
          <Symbol name="play" className="h-3.5 w-3.5" />
          {t('sources.test')}
        </Button>
        <Button variant={muted ? 'danger' : 'ghost'} size="sm" onClick={() => void mute(muted ? 0 : 60)} title={t('sources.muteHelp')}>
          <Symbol name="mute" className="h-3.5 w-3.5" />
          {muted ? t('sources.unmute') : t('sources.mute')}
        </Button>
        <div className="ml-auto flex">
          <button type="button" onClick={() => setEditing(true)} className="rounded-full p-2 text-mist-500 hover:bg-ink-800 hover:text-mist-100" title={t('sources.rename')} aria-label={t('sources.rename')}>
            <Symbol name="pencil" className="h-3.5 w-3.5" />
          </button>
          <button type="button" onClick={() => setDeleting(true)} className="rounded-full p-2 text-mist-500 hover:bg-bad-500/10 hover:text-bad-500" title={t('sources.delete')} aria-label={t('sources.delete')}>
            <Symbol name="trash" className="h-3.5 w-3.5" />
          </button>
        </div>
      </div>
      {editing && <RenameDialog source={source} onClose={() => setEditing(false)} />}
      {deleting && <DeleteDialog source={source} onClose={() => setDeleting(false)} />}
    </li>
  )
}

function RenameDialog({ source, onClose }: { source: Source; onClose: () => void }) {
  const { t } = useTranslation()
  const [name, setName] = useState(source.name)
  const [error, setError] = useState<string | null>(null)

  async function save() {
    try {
      await api.put(`/api/sources/${source.id}`, { name })
      onClose()
    } catch (caught) {
      setError(errorMessage(caught))
    }
  }

  return (
    <Dialog title={t('sources.rename')} onClose={onClose}>
      <form
        className="flex flex-col gap-4"
        onSubmit={(event) => {
          event.preventDefault()
          void save()
        }}
      >
        <Field label={t('sources.dialog.name')} value={name} onChange={(event) => setName(event.target.value)} autoFocus error={error} />
        <div className="flex justify-end gap-2">
          <Button variant="ghost" onClick={onClose}>
            {t('common.cancel')}
          </Button>
          <Button type="submit" disabled={!name.trim()}>
            {t('common.save')}
          </Button>
        </div>
      </form>
    </Dialog>
  )
}

function DeleteDialog({ source, onClose }: { source: Source; onClose: () => void }) {
  const { t } = useTranslation()
  const notify = useNotice()
  async function remove() {
    try {
      await api.delete(`/api/sources/${source.id}`)
      notify({ text: t('sources.deleted', { name: source.name }) })
      onClose()
    } catch (caught) {
      notify({ text: errorMessage(caught) })
    }
  }
  return (
    <Dialog title={t('sources.deleteTitle', { name: source.name })} onClose={onClose}>
      <p className="text-sm text-mist-300">{t('sources.deleteText')}</p>
      <div className="mt-5 flex justify-end gap-2">
        <Button variant="ghost" onClick={onClose}>
          {t('common.cancel')}
        </Button>
        <Button variant="danger" onClick={() => void remove()}>
          {t('sources.delete')}
        </Button>
      </div>
    </Dialog>
  )
}

/** What to enter in the sender, for an existing source: the same view the add dialog ends with. */
function SetupDialog({ id, onClose }: { id: number; onClose: () => void }) {
  const { t } = useTranslation()
  const notify = useNotice()
  const version = useLiveVersion(['source'])
  const source = useLoad(() => api.get<SourceWithConnection>(`/api/sources/${id}`), [id, version])
  const [confirmRenew, setConfirmRenew] = useState(false)

  async function renew() {
    try {
      source.set(await api.post<SourceWithConnection>(`/api/sources/${id}/token`))
      setConfirmRenew(false)
      notify({ text: t('sources.renewed') })
    } catch (caught) {
      notify({ text: errorMessage(caught) })
    }
  }

  if (!source.data) {
    return (
      <Dialog title={t('sources.setup')} onClose={onClose}>
        {source.error ? <Banner tone="bad">{source.error}</Banner> : <Spinner />}
      </Dialog>
    )
  }
  const data = source.data
  const hasToken = ['gotify', 'webhook', 'discord'].includes(data.protocol)
  return (
    <Dialog title={t('sources.setupFor', { name: data.name })} onClose={onClose} wide>
      <SetupInstructions source={data} />
      <div className="mt-5 flex flex-wrap items-center justify-between gap-2 border-t border-ink-700 pt-4">
        {hasToken ? (
          confirmRenew ? (
            <span className="flex flex-wrap items-center gap-2 text-sm text-mist-300">
              {t('sources.renewConfirm')}
              <Button variant="danger" size="sm" onClick={() => void renew()}>
                {t('sources.renew')}
              </Button>
              <Button variant="ghost" size="sm" onClick={() => setConfirmRenew(false)}>
                {t('common.cancel')}
              </Button>
            </span>
          ) : (
            <Button variant="ghost" size="sm" onClick={() => setConfirmRenew(true)} title={t('sources.renewHelp')}>
              <Symbol name="refresh" className="h-3.5 w-3.5" />
              {t('sources.renew')}
            </Button>
          )
        ) : (
          <span />
        )}
        <Button onClick={onClose}>{t('common.done')}</Button>
      </div>
    </Dialog>
  )
}

function SetupInstructions({ source }: { source: SourceWithConnection }) {
  const { t } = useTranslation()
  const preset = presetOf(source.kind, source.protocol)
  return (
    <div className="flex flex-col gap-3">
      <h3 className="text-sm font-semibold text-mist-200">{t('sources.dialog.howTitle')}</h3>
      <ol className="flex list-decimal flex-col gap-1.5 pl-5 text-sm text-mist-300">
        {Object.values(t(`sources.preset.${preset}.steps`, { returnObjects: true }) as Record<string, string>).map((step) => (
          <li key={step}>{step}</li>
        ))}
      </ol>
      <h3 className="mt-2 text-sm font-semibold text-mist-200">{t('sources.dialog.valuesTitle')}</h3>
      {setupLines(preset, source.connection).map((line) => (
        <CopyField key={line.label} label={t(`sources.field.${line.label}`)} value={line.value} multiline={line.multiline} hint={line.hint ? t(`sources.lineHint.${line.hint}`) : undefined} />
      ))}
    </div>
  )
}

/** Where the operator is in adding a source: pick, name, enter over there. */
function StepChip({ step, sender }: { step: 1 | 2 | 3; sender?: string }) {
  const { t } = useTranslation()
  return (
    <ol className="mb-4 flex flex-wrap items-center gap-x-2 gap-y-1 text-xs" aria-label={t('sources.dialog.stepsLabel')}>
      {([1, 2, 3] as const).map((number) => (
        <li key={number} className="flex items-center gap-2" aria-current={number === step ? 'step' : undefined}>
          {number > 1 && <span className="text-mist-600" aria-hidden="true">›</span>}
          <span className={number === step ? 'font-semibold text-accent-300' : number < step ? 'text-mist-400' : 'text-mist-600'}>
            {number}. {t(`sources.dialog.step${number}`, { sender: sender ?? t('sources.dialog.theSender') })}
          </span>
        </li>
      ))}
    </ol>
  )
}

/** Three steps: what sends, what it is called, what to enter over there. Then wait for the first message. */
function AddSource({ initial, onClose }: { initial: { preset?: string; key?: string; hostname?: string }; onClose: () => void }) {
  const { t } = useTranslation()
  const presets = useLoad(() => api.get<Preset[]>('/api/sources/presets'), [])
  const [preset, setPreset] = useState<string | null>(initial.preset ?? null)
  // A sender that already knocked is named after itself ("gw", "synology"), not after the kind of door.
  const [name, setName] = useState(initial.hostname || initial.key || (initial.preset ? t(`sources.preset.${initial.preset}.name`) : ''))
  const [hostname, setHostname] = useState(initial.hostname ?? '')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [created, setCreated] = useState<SourceWithConnection | null>(null)
  const version = useLiveVersion(['source'])
  const [heard, setHeard] = useState(false)

  // Waiting for the first message: every change of a source is a reason to look.
  useEffect(() => {
    if (!created || heard) return
    api
      .get<SourceWithConnection>(`/api/sources/${created.id}`)
      .then((fresh) => {
        if (fresh.last_seen_at) setHeard(true)
      })
      .catch(() => undefined)
  }, [created, heard, version])

  async function create() {
    if (!preset) return
    setBusy(true)
    setError(null)
    try {
      setCreated(await api.post<SourceWithConnection>('/api/sources', { preset, name, hostname, key: initial.key ?? '' }))
    } catch (caught) {
      setError(errorMessage(caught))
    } finally {
      setBusy(false)
    }
  }

  async function test() {
    if (!created) return
    await api.post(`/api/sources/${created.id}/test`).catch(() => undefined)
  }

  if (!preset) {
    const offered = new Map((presets.data ?? []).map((item) => [item.key, item]))
    const card = (key: string, showWay: boolean) => {
      const item = offered.get(key)
      if (!item) return null
      return (
        <button
          key={key}
          type="button"
          onClick={() => {
            setPreset(key)
            setName(t(`sources.preset.${key}.name`))
          }}
          className="flex items-start gap-3 rounded-xl border border-ink-700 bg-ink-900 p-3 text-left transition-colors hover:border-accent-500/50 hover:bg-ink-800"
        >
          <SourceMark kind={item.kind} protocol={item.protocol} className="h-8 w-8 text-[10px]" />
          <span className="min-w-0">
            <span className="flex flex-wrap items-center gap-x-2 text-sm font-medium text-mist-100">
              {t(`sources.preset.${key}.name`)}
              {showWay && <span className="text-[11px] font-normal text-mist-500">{t(`sources.via.${item.protocol}`)}</span>}
            </span>
            <span className="block text-xs text-mist-500">{t(`sources.preset.${key}.short`)}</span>
          </span>
        </button>
      )
    }
    return (
      <Dialog title={t('sources.dialog.pick')} onClose={onClose} wide>
        <StepChip step={1} />
        <p className="mb-5 text-sm text-mist-400">{t('sources.dialog.pickLead')}</p>
        <h3 className="mb-1 flex items-center gap-2 text-sm font-semibold text-mist-200">
          {t('sources.dialog.knownTitle')}
          <Help label={t('sources.dialog.knownTitle')}>{t('sources.dialog.knownHelp')}</Help>
        </h3>
        <p className="mb-2 text-xs text-mist-500">{t('sources.dialog.knownLead')}</p>
        <div className="grid gap-2 sm:grid-cols-2">{KNOWN.map((key) => card(key, true))}</div>
        <h3 className="mt-6 mb-1 flex items-center gap-2 text-sm font-semibold text-mist-200">
          {t('sources.dialog.waysTitle')}
          <Help label={t('sources.dialog.waysTitle')}>{t('sources.dialog.waysHelp')}</Help>
        </h3>
        <p className="mb-2 text-xs text-mist-500">{t('sources.dialog.waysLead')}</p>
        <div className="grid gap-2 sm:grid-cols-2">{WAYS.map((key) => card(key, false))}</div>
      </Dialog>
    )
  }

  return (
    <Dialog title={t(`sources.preset.${preset}.name`)} onClose={onClose} wide>
      {!created ? (
        <form
          className="flex flex-col gap-4"
          onSubmit={(event) => {
            event.preventDefault()
            void create()
          }}
        >
          <StepChip step={2} />
          <p className="text-sm text-mist-400">
            {t(`sources.preset.${preset}.short`)} {t('sources.dialog.nameLead')}
          </p>
          <Field label={t('sources.dialog.name')} value={name} onChange={(event) => setName(event.target.value)} help={t('sources.dialog.nameHelp')} autoFocus />
          {preset === 'syslog' && (
            <Field
              label={t('sources.dialog.hostname')}
              value={hostname}
              onChange={(event) => setHostname(event.target.value)}
              hint={t('sources.dialog.hostnameHint')}
              help={t('sources.dialog.hostnameHelp')}
              required
            />
          )}
          {initial.key && <Banner tone="info">{t('sources.dialog.ownKey', { key: initial.key })}</Banner>}
          {error && <Banner tone="bad">{error}</Banner>}
          <div className="flex justify-between gap-2">
            <Button variant="ghost" onClick={() => (initial.preset ? onClose() : setPreset(null))}>
              <Symbol name="chevronLeft" />
              {t('common.back')}
            </Button>
            <Button type="submit" loading={busy} disabled={!name.trim() || (preset === 'syslog' && !hostname.trim())}>
              {t('sources.dialog.create')}
            </Button>
          </div>
        </form>
      ) : (
        <div className="flex flex-col gap-5">
          <StepChip step={3} sender={t(`sources.preset.${preset}.name`)} />
          <SetupInstructions source={created} />
          {heard ? (
            <Banner tone="ok">
              {t('sources.dialog.arrived')}{' '}
              <Link to="/" className="font-medium underline">
                {t('sources.dialog.toInbox')}
              </Link>
            </Banner>
          ) : (
            <div className="flex flex-wrap items-center gap-3 rounded-xl border border-ink-700 bg-ink-900 px-3.5 py-2.5 text-sm text-mist-400" role="status">
              <Spinner />
              <span className="flex-1">{t('sources.dialog.waiting')}</span>
              <Button variant="ghost" size="sm" onClick={() => void test()} title={t('sources.testHelp')}>
                {t('sources.test')}
              </Button>
            </div>
          )}
          <div className="flex justify-end">
            <Button onClick={onClose}>{t('common.done')}</Button>
          </div>
        </div>
      )}
    </Dialog>
  )
}
