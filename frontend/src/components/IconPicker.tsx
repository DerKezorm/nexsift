import { useEffect, useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'

import { api } from '../api/client'
import type { IconName, Protocol } from '../api/types'
import { isOwnIcon } from '../lib/icons'
import { useLoad } from '../lib/useLoad'
import { Help } from './Help'
import { SourceMark } from './SourceMark'
import { Banner, Button, Field, INPUT_CLASS, Spinner } from './ui'

/**
 * The icon of a source or a rule: preview, pick a logo, no icon, or an own address. Picking opens in the same
 * dialog (``onBrowse``), so Escape never closes two at once.
 */
export function IconField({
  value,
  onChange,
  onBrowse,
  preview,
  kind,
  protocol,
  label,
  help,
  none,
}: {
  value: string
  onChange: (icon: string) => void
  onBrowse: () => void
  /** What to show: the saved picture while nothing changed, else the picker's preview of the new logo. */
  preview: string | null
  kind?: string
  protocol?: Protocol
  label: string
  help: string
  none: string
}) {
  const { t } = useTranslation()
  const own = isOwnIcon(value)
  return (
    <>
      <div className="flex flex-col gap-2">
        <span className="flex items-center gap-1.5 text-sm font-medium text-mist-300">
          {label}
          <Help label={label}>{help}</Help>
        </span>
        <div className="flex flex-wrap items-center gap-3">
          <SourceMark kind={kind} protocol={protocol} src={preview} className="h-12 w-12 text-sm" />
          {!value && <span className="min-w-0 flex-1 text-xs text-mist-500">{none}</span>}
          {value && !own && <span className="min-w-0 flex-1 truncate font-mono text-xs text-mist-400">{value.split('/')[1]}</span>}
          <div className="ml-auto flex flex-wrap gap-2">
            <Button size="sm" variant="ghost" onClick={onBrowse}>
              {value && !own ? t('icon.change') : t('icon.pick')}
            </Button>
            {value && (
              <Button size="sm" variant="ghost" onClick={() => onChange('')}>
                {t('icon.remove')}
              </Button>
            )}
          </div>
        </div>
      </div>
      <Field
        label={t('icon.own')}
        help={t('icon.ownHelp')}
        hint={t('icon.ownHint')}
        type="url"
        inputMode="url"
        placeholder="https://"
        value={own ? value : ''}
        onChange={(event) => onChange(event.target.value.trim())}
        spellCheck={false}
        autoComplete="off"
      />
    </>
  )
}

/** Tiles per page: enough to browse, few enough to stay quick while typing. */
const PAGE = 120

/** Logos per request; the server takes up to 60. */
const BATCH = 48
/** Pictures already here, as data addresses; null: nexsift could not get this one. Kept while the page lives. */
const pictures = new Map<string, string | null>()
/** Tiles waiting for their picture, by logo. */
const wanting = new Map<string, Set<(src: string | null) => void>>()
/** Logos in a request on its way, so the second request does not ask for them again. */
const asked = new Set<string>()
let timer: number | undefined
/** Requests on their way; two, so typing does not wait for the tiles of the last search. */
let inFlight = 0

/**
 * Tiles ask here, and every few milliseconds the ones in view go to nexsift in one request.
 *
 * ⚠️ One request per tile was the first way, and it was slow twice over: a browser sends six requests to one server
 * at a time, and nexsift fetches each logo from GitHub the first time. "Save" waited 2.9 s behind 100 tiles, and
 * with only the visible 42 in three slots, the first look still took 12 s (05.10.2026). One request lets nexsift
 * fetch them side by side, and leaves the browser's other connections free.
 */
function wantPicture(icon: string, show: (src: string | null) => void): () => void {
  if (pictures.has(icon)) {
    show(pictures.get(icon) ?? null)
    return () => undefined
  }
  const waiting = wanting.get(icon) ?? new Set()
  waiting.add(show)
  wanting.set(icon, waiting)
  schedule()
  // A tile that went away (the search changed, the picker closed) asks for nothing more.
  return () => {
    waiting.delete(show)
    if (waiting.size === 0) wanting.delete(icon)
  }
}

function schedule() {
  if (timer === undefined && inFlight < 2) timer = window.setTimeout(send, 30)
}

async function send() {
  timer = undefined
  const batch = [...wanting.keys()].filter((icon) => !asked.has(icon)).slice(0, BATCH)
  if (batch.length === 0) return
  inFlight += 1
  for (const icon of batch) asked.add(icon)
  let found: Record<string, string> = {}
  try {
    found = await api.get<Record<string, string>>('/api/icons/batch?' + new URLSearchParams(batch.map((icon) => ['icon', icon])).toString())
  } catch {
    // Offline or signed out: these tiles stay empty, and the next look asks again.
  }
  for (const icon of batch) {
    const src = found[icon] ?? null
    if (src) pictures.set(icon, src)
    for (const show of wanting.get(icon) ?? []) show(src)
    wanting.delete(icon)
    asked.delete(icon)
  }
  inFlight -= 1
  if (wanting.size > 0) schedule()
}

/** A tile's picture, asked for once the tile scrolls into the grid's view. Not `loading="lazy"`: Chromium loads
 * far ahead with it, and the picker asked for all 100 tiles at once. */
function TilePicture({ icon, root }: { icon: string; root: HTMLElement | null }) {
  const [box, setBox] = useState<HTMLSpanElement | null>(null)
  const [seen, setSeen] = useState(false)
  const [src, setSrc] = useState<string | null>(null)
  useEffect(() => {
    if (!box || !root || seen) return
    const observer = new IntersectionObserver((entries) => entries.some((entry) => entry.isIntersecting) && setSeen(true), { root, rootMargin: '40px 0px' })
    observer.observe(box)
    return () => observer.disconnect()
  }, [box, root, seen])
  useEffect(() => (seen ? wantPicture(icon, setSrc) : undefined), [seen, icon])
  return <span ref={setBox} className="flex h-8 w-8 items-center justify-center">{src && <img src={src} alt="" decoding="async" className="h-8 w-8 object-contain" />}</span>
}

/** Every logo of both collections, filtered as you type. The list comes from nexsift once; filtering stays here. */
export function IconPicker({ value, onPick, onBack }: { value: string; onPick: (icon: string) => void; onBack: () => void }) {
  const { t } = useTranslation()
  const names = useLoad(() => api.get<IconName[]>('/api/icons'), [])
  const [query, setQuery] = useState('')
  const [shown, setShown] = useState(PAGE)
  const needle = query.trim().toLowerCase()
  const logos = useMemo(() => {
    const all = names.data ?? []
    if (!needle) return all
    return all
      .filter((entry) => entry.name.includes(needle))
      .sort((a, b) => Number(!a.name.startsWith(needle)) - Number(!b.name.startsWith(needle)) || a.name.length - b.name.length)
  }, [names.data, needle])
  const failed = Boolean(names.error) || names.data?.length === 0
  const [grid, setGrid] = useState<HTMLDivElement | null>(null)

  return (
    <div className="flex flex-col gap-4">
      <input
        className={INPUT_CLASS}
        autoFocus
        type="search"
        aria-label={t('icon.search')}
        placeholder={t('icon.search')}
        value={query}
        onChange={(event) => {
          setQuery(event.target.value)
          setShown(PAGE)
        }}
        autoComplete="off"
        spellCheck={false}
      />
      {names.loading && !names.data && <Spinner />}
      {failed && <Banner tone="bad">{t('icon.failed')}</Banner>}
      {!failed && names.data && (
        <p className="text-xs text-mist-500" role="status">
          {logos.length === 0 ? t('icon.nothing', { query: needle }) : t('icon.count', { count: logos.length })}
        </p>
      )}
      <div ref={setGrid} className="grid max-h-[55vh] grid-cols-3 gap-1.5 overflow-y-auto sm:grid-cols-6">
        {logos.slice(0, shown).map((entry) => (
          <button
            key={entry.icon}
            type="button"
            onClick={() => onPick(entry.icon)}
            aria-pressed={value === entry.icon}
            title={entry.name}
            className={
              'flex h-20 flex-col items-center justify-center gap-1.5 rounded-xl border px-1 ' +
              (value === entry.icon ? 'border-accent-500 bg-accent-500/10' : 'border-ink-700 hover:bg-ink-800')
            }
          >
            <TilePicture icon={entry.icon} root={grid} />
            <span className="max-w-full truncate text-[10px] text-mist-400">{entry.name}</span>
          </button>
        ))}
      </div>
      <div className="flex flex-wrap justify-between gap-2">
        <Button variant="ghost" onClick={onBack}>
          {t('icon.back')}
        </Button>
        {logos.length > shown && (
          <Button variant="ghost" onClick={() => setShown((current) => current + PAGE)}>
            {t('icon.more', { count: logos.length - shown })}
          </Button>
        )}
      </div>
    </div>
  )
}
