import { useState } from 'react'
import { useTranslation } from 'react-i18next'

import { api, downloadFile, errorMessage } from '../../api/client'
import type { Backup, BackupBrief, BackupList, BackupSchedule, Settings } from '../../api/types'
import { Dialog } from '../../components/Dialog'
import { FileField } from '../../components/FileField'
import { Help } from '../../components/Help'
import { useNotice } from '../../components/Notice'
import { Symbol } from '../../components/Symbol'
import { Badge, Banner, Button, Card, Field, PageLoading, Section, SelectField } from '../../components/ui'
import { useLoad } from '../../lib/useLoad'

const SCHEDULES: BackupSchedule[] = ['off', 'daily', 'weekly', 'monthly']
const MIN_PASSWORD = 12
const KEEP_MIN = 1
const KEEP_MAX = 100
const MIB = 1048576

function formatSize(bytes: number): string {
  if (bytes >= MIB) return `${(bytes / MIB).toFixed(1)} MiB`
  return `${Math.max(1, Math.round(bytes / 1024))} KiB`
}

function useDateTime() {
  const { i18n } = useTranslation()
  return (at: string) => new Intl.DateTimeFormat(i18n.language, { dateStyle: 'medium', timeStyle: 'short' }).format(new Date(at))
}

/**
 * Backups of the server: make, list, download, restore. Taken over from nextrmnl.
 *
 * The button that matters is "Download": the copies nexsift makes on its own lie on the same disk as the database.
 * Only an archive that leaves the machine is a backup.
 */
export function BackupTab({ onSettings }: { onSettings: (settings: Settings) => void }) {
  const { t } = useTranslation()
  const notify = useNotice()
  const when = useDateTime()
  const list = useLoad(() => api.get<BackupList>('/api/backups'), [])
  const [creating, setCreating] = useState(false)
  const [note, setNote] = useState('')
  const [download, setDownload] = useState<Backup | null>(null)
  const [remove, setRemove] = useState<Backup | null>(null)
  const [busy, setBusy] = useState(false)
  const [keep, setKeep] = useState<string | null>(null)

  async function saveSettings(values: Partial<Settings>) {
    try {
      onSettings(await api.put<Settings>('/api/settings', { values }))
      await list.reload()
      notify({ text: t('common.saved') })
    } catch (error) {
      notify({ text: errorMessage(error) })
    }
  }

  async function create() {
    setBusy(true)
    try {
      await api.post('/api/backups', { note: note.trim() })
      setCreating(false)
      setNote('')
      notify({ text: t('backups.created') })
      await list.reload()
    } catch (error) {
      notify({ text: errorMessage(error) })
    } finally {
      setBusy(false)
    }
  }

  async function deleteBackup() {
    if (!remove) return
    setBusy(true)
    try {
      await api.delete(`/api/backups/${encodeURIComponent(remove.name)}`)
      setRemove(null)
      await list.reload()
    } catch (error) {
      notify({ text: errorMessage(error) })
    } finally {
      setBusy(false)
    }
  }

  const data = list.data
  if (!data) return list.error ? <Banner tone="bad">{list.error}</Banner> : <PageLoading />
  const keepValue = keep ?? String(data.keep)
  const keepNumber = Number(keepValue)
  const keepValid = Number.isInteger(keepNumber) && keepNumber >= KEEP_MIN && keepNumber <= KEEP_MAX

  return (
    <div className="flex flex-col gap-6">
      <Section title={t('backups.title')} intro={t('backups.intro')} help={t('backups.help')}>
        <Banner tone="warn">
          <p className="font-medium">{t('backups.sameDiskTitle')}</p>
          <p className="mt-1">{t('backups.sameDisk')}</p>
        </Banner>
      </Section>

      <Section title={t('backups.autoTitle')} intro={t('backups.autoIntro')} help={t('backups.autoHelp')}>
        <div className="grid gap-4 sm:grid-cols-2 sm:items-start">
          <SelectField label={t('backups.scheduleLabel')} value={data.schedule} onChange={(value) => void saveSettings({ backup_schedule: value as BackupSchedule })} help={t('backups.scheduleHelp')}>
            {SCHEDULES.map((value) => (
              <option key={value} value={value}>
                {t(`backups.schedule.${value}`)}
              </option>
            ))}
          </SelectField>
          <div className="flex items-end gap-2">
            <div className="flex-1">
              <Field
                label={t('backups.keepLabel')}
                inputMode="numeric"
                value={keepValue}
                onChange={(event) => setKeep(event.target.value.replace(/\D/g, ''))}
                error={keepValid ? null : t('backups.keepRange', { min: KEEP_MIN, max: KEEP_MAX })}
                help={t('backups.keepHelp')}
              />
            </div>
            <Button
              variant="ghost"
              disabled={!keepValid || keepNumber === data.keep}
              onClick={() => {
                setKeep(null)
                void saveSettings({ backup_keep: keepNumber })
              }}
            >
              {t('common.save')}
            </Button>
          </div>
        </div>
        <p className="text-xs leading-relaxed text-mist-500">{t('backups.keepHint')}</p>
      </Section>

      <Section
        title={t('backups.listTitle')}
        help={t('backups.listHelp')}
        aside={
          <Button size="sm" onClick={() => setCreating(true)}>
            <Symbol name="plus" className="h-3.5 w-3.5" />
            {t('backups.createNow')}
          </Button>
        }
      >
        {data.entries.length === 0 ? (
          <p className="text-sm text-mist-500">{t('backups.empty')}</p>
        ) : (
          // relative: the hidden column heading is placed absolutely and would otherwise widen the whole page on a phone.
          <div className="relative overflow-x-auto rounded-xl border border-ink-700">
            <table className="w-full min-w-[40rem] text-left text-sm">
              <thead className="border-b border-ink-700 bg-ink-900 text-xs tracking-wide text-mist-600 uppercase">
                <tr>
                  <th className="px-4 py-3 font-medium">{t('backups.colWhen')}</th>
                  <th className="px-4 py-3 font-medium">
                    <span className="inline-flex items-center gap-1.5">
                      {t('backups.colKind')}
                      <Help label={t('backups.colKind')}>{t('backups.kindHelp')}</Help>
                    </span>
                  </th>
                  <th className="px-4 py-3 font-medium">{t('backups.colNote')}</th>
                  <th className="px-4 py-3 font-medium">{t('backups.colVersion')}</th>
                  <th className="px-4 py-3 text-right font-medium">{t('backups.colSize')}</th>
                  <th className="px-4 py-3">
                    <span className="sr-only">{t('backups.colActions')}</span>
                  </th>
                </tr>
              </thead>
              <tbody>
                {data.entries.map((backup) => (
                  <tr key={backup.name} className="border-b border-ink-800 last:border-0">
                    <td className="px-4 py-3 whitespace-nowrap text-mist-100">{when(backup.created)}</td>
                    <td className="px-4 py-3">
                      <Badge tone={backup.kind === 'manual' ? 'accent' : 'neutral'}>{t(`backups.kind.${backup.kind}`)}</Badge>
                    </td>
                    <td className="px-4 py-3 text-mist-500">{backup.note}</td>
                    <td className="px-4 py-3 whitespace-nowrap text-mist-500 tabular-nums">
                      <span className="inline-flex items-center gap-2">
                        {backup.version || t('backups.versionUnknown')}
                        {!backup.compatible && <Badge tone="warn">{t(backup.reason === 'backup_newer' ? 'backups.tooNew' : 'backups.unknownVersion')}</Badge>}
                      </span>
                    </td>
                    <td className="px-4 py-3 text-right whitespace-nowrap text-mist-500 tabular-nums">{formatSize(backup.size)}</td>
                    <td className="px-4 py-3">
                      <div className="flex items-center justify-end gap-1">
                        <button
                          type="button"
                          aria-label={t('backups.downloadOne', { when: when(backup.created) })}
                          title={t('backups.download')}
                          onClick={() => setDownload(backup)}
                          className="rounded-full border border-ink-700 p-2 text-mist-500 transition-colors hover:border-accent-600 hover:text-accent-400"
                        >
                          <Symbol name="download" />
                        </button>
                        <button
                          type="button"
                          aria-label={t('backups.deleteOne', { when: when(backup.created) })}
                          title={t('backups.delete')}
                          onClick={() => setRemove(backup)}
                          className="rounded-full border border-ink-700 p-2 text-mist-500 transition-colors hover:border-bad-500 hover:text-bad-500"
                        >
                          <Symbol name="trash" />
                        </button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        <p className="text-xs leading-relaxed text-mist-600">{t('backups.folderHint', { folder: data.folder })}</p>
      </Section>

      <RestoreSection />

      {creating && (
        <Dialog title={t('backups.createTitle')} onClose={() => setCreating(false)}>
          <form
            className="flex flex-col gap-4"
            onSubmit={(event) => {
              event.preventDefault()
              void create()
            }}
          >
            <p className="text-sm text-mist-500">{t('backups.createSub')}</p>
            <Field label={t('backups.noteLabel')} hint={t('backups.noteHint')} value={note} maxLength={200} onChange={(event) => setNote(event.target.value)} autoFocus help={t('backups.noteHelp')} />
            <div className="flex justify-end gap-2">
              <Button variant="ghost" onClick={() => setCreating(false)}>
                {t('common.cancel')}
              </Button>
              <Button type="submit" loading={busy}>
                {t('backups.createNow')}
              </Button>
            </div>
          </form>
        </Dialog>
      )}

      {download && <DownloadDialog backup={download} when={when(download.created)} onClose={() => setDownload(null)} />}

      {remove && (
        <Dialog title={t('backups.deleteTitle')} onClose={() => setRemove(null)}>
          <div className="flex flex-col gap-4">
            <p className="text-sm text-mist-300">{t('backups.deleteText', { when: when(remove.created) })}</p>
            <Banner tone="warn">{t('backups.deleteWarning')}</Banner>
            <div className="flex justify-end gap-2">
              <Button variant="ghost" onClick={() => setRemove(null)}>
                {t('common.cancel')}
              </Button>
              <Button variant="danger" loading={busy} onClick={() => void deleteBackup()}>
                {t('backups.delete')}
              </Button>
            </div>
          </div>
        </Dialog>
      )}
    </div>
  )
}

function DownloadDialog({ backup, when, onClose }: { backup: Backup; when: string; onClose: () => void }) {
  const { t } = useTranslation()
  const [password, setPassword] = useState('')
  const [repeat, setRepeat] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const ok = password.length >= MIN_PASSWORD && password === repeat

  async function fetchArchive() {
    setBusy(true)
    setError(null)
    try {
      await downloadFile(`/api/backups/${encodeURIComponent(backup.name)}/archive`, backup.name.replace(/\.db$/, '.zip'), { password })
      onClose()
    } catch (caught) {
      setError(errorMessage(caught))
    } finally {
      setBusy(false)
    }
  }

  return (
    <Dialog title={t('backups.downloadTitle')} onClose={onClose}>
      <form
        className="flex flex-col gap-4"
        onSubmit={(event) => {
          event.preventDefault()
          if (ok) void fetchArchive()
        }}
      >
        <p className="text-sm text-mist-500">{t('backups.downloadOf', { when })}</p>
        <p className="text-sm leading-relaxed text-mist-300">{t('backups.downloadWhat')}</p>
        <Banner tone="warn">{t('backups.passwordWarning')}</Banner>
        <Field label={t('backups.passwordLabel')} type="password" autoComplete="new-password" value={password} onChange={(event) => setPassword(event.target.value)} help={t('backups.passwordHelp')} autoFocus />
        <Field
          label={t('backups.passwordRepeat')}
          type="password"
          autoComplete="new-password"
          value={repeat}
          onChange={(event) => setRepeat(event.target.value)}
          error={repeat.length > 0 && password !== repeat ? t('backups.passwordMismatch') : null}
          hint={password.length > 0 && password.length < MIN_PASSWORD ? t('backups.passwordTooShort', { min: MIN_PASSWORD }) : undefined}
          help={t('backups.passwordRepeatHelp')}
        />
        {error && <Banner tone="bad">{error}</Banner>}
        <div className="flex justify-end gap-2">
          <Button variant="ghost" onClick={onClose}>
            {t('common.cancel')}
          </Button>
          <Button type="submit" disabled={!ok} loading={busy}>
            <Symbol name="download" />
            {t('backups.download')}
          </Button>
        </div>
      </form>
    </Dialog>
  )
}

/**
 * Restore, at the bottom and closed at first: the only button on this page that takes something away. Two steps,
 * first look at what is in the archive, then decide. The restore happens at the next start: nexsift ends itself,
 * Docker starts it again.
 */
function RestoreSection() {
  const { t } = useTranslation()
  const when = useDateTime()
  const [open, setOpen] = useState(false)
  const [file, setFile] = useState<File | null>(null)
  const [password, setPassword] = useState('')
  const [brief, setBrief] = useState<BackupBrief | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [restarting, setRestarting] = useState(false)

  function form(): FormData {
    const data = new FormData()
    data.append('file', file as File)
    data.append('password', password)
    return data
  }

  async function check() {
    setBusy(true)
    setError(null)
    try {
      setBrief(await api.post<BackupBrief>('/api/backups/check', form()))
    } catch (caught) {
      setError(errorMessage(caught))
    } finally {
      setBusy(false)
    }
  }

  async function restore() {
    setBusy(true)
    setError(null)
    try {
      await api.post('/api/backups/restore', form())
      setRestarting(true)
      // The server restarts. As soon as it answers again the page reloads and lands on the sign-in.
      const started = Date.now()
      const poll = window.setInterval(() => {
        void fetch('/api/health', { cache: 'no-store' })
          .then((response) => {
            if (response.ok && Date.now() - started > 4000) {
              window.clearInterval(poll)
              window.location.reload()
            }
          })
          .catch(() => undefined)
      }, 2000)
    } catch (caught) {
      setError(errorMessage(caught))
      setBusy(false)
    }
  }

  if (restarting) {
    return (
      <Card className="border-bad-500/30">
        <Banner tone="warn">{t('restore.restarting')}</Banner>
      </Card>
    )
  }

  return (
    <Card className="flex flex-col gap-4 border-bad-500/30">
      <div>
        <h2 className="flex items-center gap-2 text-lg font-semibold">
          {t('restore.title')}
          <Help label={t('restore.title')}>{t('restore.help')}</Help>
        </h2>
        <p className="mt-1 text-sm text-mist-500">{t('restore.intro')}</p>
      </div>
      {!open ? (
        <div>
          <Button variant="ghost" onClick={() => setOpen(true)}>
            {t('restore.open')}
          </Button>
        </div>
      ) : (
        <>
          <FileField
            label={t('restore.fileLabel')}
            accept=".zip,application/zip"
            help={t('restore.fileHelp')}
            onChange={(next) => {
              setFile(next)
              setBrief(null)
            }}
          />
          <Field
            label={t('restore.passwordLabel')}
            type="password"
            autoComplete="off"
            value={password}
            hint={t('restore.passwordHint')}
            help={t('restore.passwordHelp')}
            onChange={(event) => {
              setPassword(event.target.value)
              setBrief(null)
            }}
          />
          {error && <Banner tone="bad">{error}</Banner>}
          {brief === null ? (
            <div className="flex flex-wrap gap-3">
              <Button disabled={!file || password.length === 0} loading={busy} onClick={() => void check()}>
                {t('restore.check')}
              </Button>
              <Button variant="ghost" onClick={() => setOpen(false)}>
                {t('common.cancel')}
              </Button>
            </div>
          ) : (
            <div className="flex flex-col gap-4 rounded-xl border border-ink-700 bg-ink-900 p-4">
              <p className="flex items-center gap-2 text-sm font-semibold text-mist-100">
                {t('restore.previewTitle')}
                <Help label={t('restore.previewTitle')}>{t('restore.previewHelp')}</Help>
              </p>
              <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1.5 text-sm">
                <dt className="text-mist-600">{t('restore.fromWhen')}</dt>
                <dd className="text-mist-100">{when(brief.created)}</dd>
                <dt className="text-mist-600">{t('restore.fromVersion')}</dt>
                <dd className="text-mist-100 tabular-nums">{brief.version || t('backups.versionUnknown')}</dd>
                <dt className="text-mist-600">{t('restore.kind')}</dt>
                <dd className="text-mist-100">{t(`backups.kind.${brief.kind}`)}</dd>
                {brief.note && (
                  <>
                    <dt className="text-mist-600">{t('restore.note')}</dt>
                    <dd className="text-mist-100">{brief.note}</dd>
                  </>
                )}
                <dt className="text-mist-600">{t('restore.contents')}</dt>
                <dd className="text-mist-100">{t('restore.contentsText', { ...brief.counts })}</dd>
                <dt className="text-mist-600">{t('restore.key')}</dt>
                <dd className="text-mist-100">{brief.key_in_archive ? t('restore.keyIn') : t('restore.keyMissing')}</dd>
              </dl>
              {!brief.compatible && <Banner tone="bad">{t(brief.reason === 'backup_newer' ? 'restore.tooNew' : 'restore.unknownVersion', { version: brief.version })}</Banner>}
              {brief.key_from_env && <Banner tone="warn">{t('restore.envKey')}</Banner>}
              {!brief.key_in_archive && !brief.key_from_env && <Banner tone="bad">{t('restore.noKey')}</Banner>}
              <Banner tone="warn">
                <p>{t('restore.replaces')}</p>
                <p className="mt-1">{t('restore.signIn')}</p>
              </Banner>
              <div className="flex flex-wrap gap-3">
                <Button variant="ghost" onClick={() => setBrief(null)}>
                  {t('common.cancel')}
                </Button>
                <Button variant="danger" disabled={!brief.compatible} loading={busy} onClick={() => void restore()}>
                  {t('restore.restoreNow')}
                </Button>
              </div>
            </div>
          )}
        </>
      )}
    </Card>
  )
}
