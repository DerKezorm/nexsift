import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import { useTranslation } from 'react-i18next'
import { Link } from 'react-router-dom'

import { api, errorMessage } from '../api/client'
import type { Source, ThreadDetail as Detail, ThreadSummary, View } from '../api/types'
import { Help } from '../components/Help'
import { useNotice } from '../components/Notice'
import { SourceMark } from '../components/SourceMark'
import { Symbol, type SymbolName } from '../components/Symbol'
import { ShortcutHelp } from '../components/inbox/ShortcutHelp'
import { ThreadDetail } from '../components/inbox/ThreadDetail'
import { Welcome } from '../components/inbox/Welcome'
import { isMuted, useCounts, useSources, useTargets } from '../lib/data'
import { useLiveVersion } from '../lib/live'
import { PRIORITY_DOT } from '../lib/priority'
import { threadTitle } from '../lib/threadTitle'
import { relative, useNow } from '../lib/time'

const VIEWS: { key: View; symbol: SymbolName }[] = [
  { key: 'inbox', symbol: 'inbox' },
  { key: 'unread', symbol: 'unread' },
  { key: 'crit', symbol: 'bolt' },
  { key: 'archived', symbol: 'archive' },
]

type Page = { items: ThreadSummary[]; next: string | null }

function typing(target: EventTarget | null): boolean {
  const element = target as HTMLElement | null
  return !!element && (element.tagName === 'INPUT' || element.tagName === 'TEXTAREA' || element.tagName === 'SELECT' || element.isContentEditable)
}

/**
 * The inbox: views and sources on the left, threads in the middle, the open thread on the right.
 * Everything can be done with the keyboard; the mouse works too.
 */
export function InboxPage() {
  const { t, i18n } = useTranslation()
  const notify = useNotice()
  const now = useNow()
  const sources = useSources()
  const targets = useTargets()
  const counts = useCounts()
  const [view, setView] = useState<View>('inbox')
  const [sourceFilter, setSourceFilter] = useState<number | null>(null)
  const [query, setQuery] = useState('')
  const [search, setSearch] = useState('')
  const [threads, setThreads] = useState<ThreadSummary[]>([])
  const [next, setNext] = useState<string | null>(null)
  const [loaded, setLoaded] = useState(false)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [selectedId, setSelectedId] = useState<number | null>(null)
  const [detail, setDetail] = useState<Detail | null>(null)
  const [detailOpen, setDetailOpen] = useState(false)
  const [help, setHelp] = useState(false)
  const [fresh, setFresh] = useState<Set<number>>(new Set())
  const searchBox = useRef<HTMLInputElement>(null)
  const listRef = useRef<HTMLUListElement>(null)
  const version = useLiveVersion(['thread', 'threads', 'source'])

  const sourceById = useMemo(() => new Map((sources.data ?? []).map((source) => [source.id, source])), [sources.data])

  // Typing in the search waits a moment before asking the server.
  useEffect(() => {
    const timer = window.setTimeout(() => setSearch(query.trim()), 250)
    return () => window.clearTimeout(timer)
  }, [query])

  const params = useMemo(() => {
    const values = new URLSearchParams({ view })
    if (sourceFilter) values.set('source_id', String(sourceFilter))
    if (search) values.set('q', search)
    return values.toString()
  }, [view, sourceFilter, search])

  const knownIds = useRef<Set<number>>(new Set())
  const load = useCallback(async () => {
    try {
      const page = await api.get<Page>(`/api/threads?${params}`)
      // Rows that were not there at the last load glow once.
      const known = knownIds.current
      setFresh(new Set(page.items.filter((item) => known.size > 0 && !known.has(item.id)).map((item) => item.id)))
      knownIds.current = new Set(page.items.map((item) => item.id))
      setThreads(page.items)
      setNext(page.next)
      setLoadError(null)
    } catch (caught) {
      setLoadError(errorMessage(caught))
    } finally {
      setLoaded(true)
    }
  }, [params])

  useEffect(() => {
    knownIds.current = new Set()
    void load()
  }, [load])
  useEffect(() => {
    if (version > 0) void load()
  }, [version, load])

  async function loadMore() {
    if (!next) return
    const page = await api.get<Page>(`/api/threads?${params}&before=${encodeURIComponent(next)}`)
    setThreads((current) => [...current, ...page.items.filter((item) => !current.some((known) => known.id === item.id))])
    setNext(page.next)
  }

  // Keep a selection as long as there is something to select.
  const selected = threads.find((thread) => thread.id === selectedId) ?? null
  useEffect(() => {
    if (!selected && threads.length > 0 && !detailOpen) setSelectedId(threads[0].id)
  }, [selected, threads, detailOpen])

  // The open thread in full, fetched again when anything changed.
  useEffect(() => {
    if (selectedId === null) {
      setDetail(null)
      return
    }
    let cancelled = false
    api
      .get<Detail>(`/api/threads/${selectedId}`)
      .then((data) => {
        if (!cancelled) setDetail(data)
      })
      .catch(() => {
        if (!cancelled) setDetail(null)
      })
    return () => {
      cancelled = true
    }
  }, [selectedId, version])

  // Opening a thread marks it read after a short look, like a mail client. "u" brings it back.
  const selectedUnread = selected?.state === 'unread' ? selected.id : null
  useEffect(() => {
    if (!selectedUnread) return
    const timer = window.setTimeout(() => {
      void api.post('/api/threads/state', { ids: [selectedUnread], state: 'read' }).catch(() => undefined)
      setThreads((current) => current.map((thread) => (thread.id === selectedUnread ? { ...thread, state: 'read' } : thread)))
    }, 900)
    return () => window.clearTimeout(timer)
  }, [selectedUnread])

  useEffect(() => {
    if (selectedId === null) return
    listRef.current?.querySelector(`[data-thread="${selectedId}"]`)?.scrollIntoView({ block: 'nearest' })
  }, [selectedId])

  const move = useCallback(
    (step: number) => {
      if (threads.length === 0) return
      const index = threads.findIndex((thread) => thread.id === selectedId)
      const target = Math.min(threads.length - 1, Math.max(0, index + step))
      setSelectedId(threads[target].id)
    },
    [threads, selectedId],
  )

  /** A thread leaves the view: the next one below takes its place (or the one above at the end). */
  const leave = useCallback(
    (id: number) => {
      const index = threads.findIndex((thread) => thread.id === id)
      setSelectedId(threads[index + 1]?.id ?? threads[index - 1]?.id ?? null)
      setThreads((current) => current.filter((thread) => thread.id !== id))
    },
    [threads],
  )

  const archive = useCallback(
    async (thread: ThreadSummary) => {
      const back = thread.state === 'archived'
      leave(thread.id)
      try {
        await api.post('/api/threads/state', { ids: [thread.id], state: back ? 'read' : 'archived' })
        notify({
          text: back ? t('inbox.movedBack') : t('inbox.archived'),
          action: back ? undefined : { label: t('inbox.undo'), run: () => void api.post('/api/threads/state', { ids: [thread.id], state: 'read' }) },
        })
      } catch (caught) {
        notify({ text: errorMessage(caught) })
      }
    },
    [leave, notify, t],
  )

  const toggleRead = useCallback(
    async (thread: ThreadSummary) => {
      const state = thread.state === 'unread' ? 'read' : 'unread'
      setThreads((current) => current.map((item) => (item.id === thread.id ? { ...item, state } : item)))
      await api.post('/api/threads/state', { ids: [thread.id], state }).catch((caught) => notify({ text: errorMessage(caught) }))
    },
    [notify],
  )

  const destroy = useCallback(
    async (thread: ThreadSummary) => {
      leave(thread.id)
      try {
        await api.delete(`/api/threads/${thread.id}`)
        notify({ text: t('inbox.deleted'), action: { label: t('inbox.undo'), run: () => void api.post(`/api/threads/${thread.id}/restore`) } })
      } catch (caught) {
        notify({ text: errorMessage(caught) })
      }
    },
    [leave, notify, t],
  )

  const muteSource = useCallback(
    async (thread: ThreadSummary) => {
      const source = sourceById.get(thread.source_id)
      if (!source) return
      const muted = isMuted(source)
      try {
        await api.post(`/api/sources/${source.id}/mute`, { minutes: muted ? 0 : 60 })
        notify({ text: muted ? t('inbox.unmuted', { name: source.name }) : t('inbox.muted', { name: source.name }) })
      } catch (caught) {
        notify({ text: errorMessage(caught) })
      }
    },
    [sourceById, notify, t],
  )

  useEffect(() => {
    function onKey(event: KeyboardEvent) {
      if (event.ctrlKey || event.metaKey || event.altKey) return
      if (typing(event.target)) {
        if (event.key === 'Escape') (event.target as HTMLElement).blur()
        return
      }
      const key = event.key
      if (key === '?') setHelp((open) => !open)
      else if (key === 'Escape') {
        if (help) setHelp(false)
        else setDetailOpen(false)
      } else if (key === 'j' || key === 'ArrowDown') move(1)
      else if (key === 'k' || key === 'ArrowUp') move(-1)
      else if (key === 'Enter' && selected) setDetailOpen(true)
      else if (key === 'e' && selected) void archive(selected)
      else if (key === 'u' && selected) void toggleRead(selected)
      else if ((key === 'd' || key === 'Delete' || key === '#') && selected) void destroy(selected)
      else if (key === 'm' && selected) void muteSource(selected)
      else if (key === 'o' && selected?.links[0]) window.open(selected.links[0].url, '_blank', 'noopener,noreferrer')
      else if (key === '/') searchBox.current?.focus()
      else if (['1', '2', '3', '4'].includes(key)) setView(VIEWS[Number(key) - 1].key)
      else return
      event.preventDefault()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [help, move, selected, archive, toggleRead, destroy, muteSource])

  async function markAllRead() {
    try {
      const result = await api.post<{ changed: number }>('/api/threads/read-all', { view, source_id: sourceFilter })
      notify({ text: t('inbox.markedRead', { count: result.changed }) })
      void load()
    } catch (caught) {
      notify({ text: errorMessage(caught) })
    }
  }

  const noSources = sources.data !== undefined && sources.data.length === 0
  const viewCounts = counts.data?.views

  return (
    <div className="flex min-h-0 w-full gap-4">
      <aside className="ns-scroll hidden w-56 shrink-0 flex-col gap-6 overflow-y-auto md:flex" aria-label={t('inbox.filters')}>
        <nav className="flex flex-col gap-0.5">
          {VIEWS.map(({ key, symbol }) => (
            <button
              key={key}
              type="button"
              onClick={() => setView(key)}
              aria-current={view === key ? 'page' : undefined}
              title={t(`inbox.viewHelp.${key}`)}
              className={
                'flex items-center gap-2.5 rounded-xl px-3 py-2 text-left text-sm font-medium transition-colors ' +
                (view === key ? 'bg-accent-500/15 text-accent-400' : 'text-mist-400 hover:bg-ink-850 hover:text-mist-100')
              }
            >
              <Symbol name={symbol} className={'h-4 w-4 ' + (key === 'crit' ? 'text-crit-500' : '')} />
              <span className="flex-1">{t(`inbox.view.${key}`)}</span>
              <span className="text-xs text-mist-600 tabular-nums">{viewCounts?.[key] || ''}</span>
            </button>
          ))}
        </nav>

        <div className="flex flex-col gap-0.5">
          <p className="flex items-center gap-1.5 px-3 pb-1 text-xs font-semibold tracking-wide text-mist-600 uppercase">
            {t('inbox.sources')}
            <Help label={t('inbox.sources')}>{t('inbox.sourcesHelp')}</Help>
          </p>
          {(sources.data ?? []).map((source) => (
            <SourceFilterButton
              key={source.id}
              source={source}
              active={sourceFilter === source.id}
              unread={counts.data?.unread_by_source[String(source.id)] ?? 0}
              muted={isMuted(source, now)}
              onClick={() => setSourceFilter(sourceFilter === source.id ? null : source.id)}
            />
          ))}
          <Link to="/sources?add=1" className="mt-1 flex items-center gap-2 rounded-xl px-3 py-1.5 text-sm text-mist-500 hover:bg-ink-850 hover:text-mist-100">
            <Symbol name="plus" className="h-4 w-4" />
            {t('inbox.addSource')}
          </Link>
        </div>

        <button type="button" onClick={() => setHelp(true)} className="mt-auto flex items-center gap-2 px-3 text-xs text-mist-600 hover:text-mist-300">
          <Symbol name="keyboard" className="h-4 w-4" />
          {t('inbox.shortcutsHint')} <kbd>?</kbd>
        </button>
      </aside>

      <section
        className={
          'flex min-h-0 min-w-0 flex-1 flex-col border-ink-700 bg-ink-900/60 sm:rounded-2xl sm:border lg:max-w-md xl:max-w-lg ' + (detailOpen ? 'hidden lg:flex' : 'flex')
        }
        aria-label={t('inbox.list')}
      >
        <div className="flex flex-col gap-2 border-b border-ink-700 p-3">
          <div className="flex items-center gap-2">
            <label className="flex min-w-0 flex-1 items-center gap-2 rounded-xl border border-ink-700 bg-ink-950/60 px-3 py-1.5 focus-within:border-accent-500">
              <Symbol name="search" className="h-4 w-4 shrink-0 text-mist-600" />
              <input
                ref={searchBox}
                value={query}
                onChange={(event) => setQuery(event.target.value)}
                placeholder={t('inbox.search')}
                aria-label={t('inbox.search')}
                className="min-w-0 flex-1 bg-transparent text-sm text-mist-100 placeholder:text-mist-600 focus:outline-none"
              />
              <kbd className="hidden sm:inline">/</kbd>
            </label>
            <button
              type="button"
              onClick={() => void markAllRead()}
              title={t('inbox.markAllRead')}
              aria-label={t('inbox.markAllRead')}
              className="rounded-full border border-ink-700 bg-ink-850 p-2 text-mist-500 hover:text-mist-100"
            >
              <Symbol name="check" />
            </button>
          </div>
          <div className="flex gap-1.5 overflow-x-auto md:hidden">
            {VIEWS.map(({ key }) => (
              <button
                key={key}
                type="button"
                onClick={() => setView(key)}
                className={'shrink-0 rounded-full px-3 py-1 text-xs font-medium ' + (view === key ? 'bg-accent-500/15 text-accent-400' : 'bg-ink-850 text-mist-500')}
              >
                {t(`inbox.view.${key}`)} {viewCounts?.[key] ? <span className="tabular-nums opacity-70">{viewCounts[key]}</span> : null}
              </button>
            ))}
          </div>
          {sourceFilter && (
            <button
              type="button"
              onClick={() => setSourceFilter(null)}
              className="inline-flex w-fit items-center gap-1.5 rounded-full bg-ink-800 px-2.5 py-1 text-xs text-mist-300 hover:text-mist-100"
            >
              {t('inbox.onlySource', { name: sourceById.get(sourceFilter)?.name })}
              <Symbol name="close" className="h-3 w-3" />
            </button>
          )}
        </div>

        {loadError ? (
          <p className="p-4 text-sm text-bad-500">{loadError}</p>
        ) : !loaded ? null : noSources ? (
          <Welcome />
        ) : threads.length === 0 ? (
          <EmptyList view={view} searching={!!search} hasTargets={(targets.data?.length ?? 0) > 0} />
        ) : (
          <ul ref={listRef} className="ns-scroll min-h-0 flex-1 overflow-y-auto" role="listbox" aria-label={t('inbox.list')}>
            {threads.map((thread) => (
              <ThreadRow
                key={thread.id}
                thread={thread}
                source={sourceById.get(thread.source_id)}
                selected={thread.id === selectedId}
                fresh={fresh.has(thread.id)}
                now={now}
                language={i18n.language}
                onSelect={() => {
                  setSelectedId(thread.id)
                  setDetailOpen(true)
                }}
              />
            ))}
            {next && (
              <li className="p-3 text-center">
                <button type="button" onClick={() => void loadMore()} className="rounded-full bg-ink-850 px-4 py-1.5 text-xs font-medium text-mist-300 hover:text-mist-100">
                  {t('inbox.loadMore')}
                </button>
              </li>
            )}
          </ul>
        )}
      </section>

      <section className={'min-h-0 min-w-0 flex-[1.4] ' + (detailOpen ? 'flex' : 'hidden lg:flex')} aria-label={t('inbox.detail')}>
        {selected && detail && detail.id === selected.id ? (
          <ThreadDetail
            key={detail.id}
            thread={detail}
            source={sourceById.get(detail.source_id)}
            now={now}
            onBack={() => setDetailOpen(false)}
            onArchive={() => void archive(selected)}
            onToggleRead={() => void toggleRead(selected)}
            onDelete={() => void destroy(selected)}
            onMute={() => void muteSource(selected)}
          />
        ) : (
          <div className="flex flex-1 items-center justify-center rounded-2xl border border-dashed border-ink-700 px-6 text-center text-sm text-mist-600">
            {noSources ? t('inbox.nothingYet') : t('inbox.nothingSelected')}
          </div>
        )}
      </section>

      {help && <ShortcutHelp onClose={() => setHelp(false)} />}
    </div>
  )
}

function SourceFilterButton({ source, active, unread, muted, onClick }: { source: Source; active: boolean; unread: number; muted: boolean; onClick: () => void }) {
  const { t } = useTranslation()
  return (
    <button
      type="button"
      onClick={onClick}
      aria-pressed={active}
      title={active ? t('inbox.showAllSources') : t('inbox.onlyThisSource')}
      className={'flex items-center gap-2.5 rounded-xl px-3 py-1.5 text-left text-sm transition-colors ' + (active ? 'bg-ink-800 text-mist-100' : 'text-mist-400 hover:bg-ink-850 hover:text-mist-100')}
    >
      <SourceMark kind={source.kind} protocol={source.protocol} className="h-6 w-6 text-[9px]" />
      <span className="min-w-0 flex-1 truncate">{source.name}</span>
      {source.unrecognized_streak > 0 && <Symbol name="warn" className="h-3.5 w-3.5 text-warn-500" />}
      {muted && <Symbol name="mute" className="h-3.5 w-3.5 text-mist-600" />}
      {unread > 0 && <span className="text-xs font-semibold text-accent-400 tabular-nums">{unread}</span>}
    </button>
  )
}

function EmptyList({ view, searching, hasTargets }: { view: View; searching: boolean; hasTargets: boolean }) {
  const { t } = useTranslation()
  return (
    <div className="flex flex-1 flex-col items-center justify-center gap-2 px-6 text-center">
      <Symbol name="resolved" className="h-10 w-10 text-accent-500/60" />
      <p className="font-semibold text-mist-200">{searching ? t('inbox.noHits') : t(`inbox.empty.${view}`)}</p>
      <p className="text-sm text-mist-500">{searching ? t('inbox.noHitsHint') : t('inbox.emptyHint')}</p>
      {!hasTargets && view === 'inbox' && !searching && (
        <Link to="/rules#targets" className="mt-3 text-sm font-medium text-accent-400 hover:text-accent-300">
          {t('inbox.setUpPhone')}
        </Link>
      )}
    </div>
  )
}

function ThreadRow({
  thread,
  source,
  selected,
  fresh,
  now,
  language,
  onSelect,
}: {
  thread: ThreadSummary
  source?: Source
  selected: boolean
  fresh: boolean
  now: number
  language: string
  onSelect: () => void
}) {
  const { t } = useTranslation()
  const unread = thread.state === 'unread'
  return (
    <li
      data-thread={thread.id}
      role="option"
      aria-selected={selected}
      onClick={onSelect}
      className={'relative flex cursor-pointer gap-3 border-b border-ink-700/60 px-4 py-3 transition-colors ' + (selected ? 'bg-accent-500/10 ' : 'hover:bg-ink-850 ') + (fresh ? 'ns-arrive' : '')}
    >
      {selected && <span className="absolute inset-y-0 left-0 w-0.5 bg-accent-500" aria-hidden="true" />}
      <div className="relative self-start">
        <SourceMark kind={source?.kind} protocol={source?.protocol} />
        <span
          className={'absolute -right-1 -bottom-1 h-3 w-3 rounded-full border-2 border-ink-900 ' + (thread.resolved_at ? 'bg-ok-500' : PRIORITY_DOT[thread.priority])}
          title={thread.resolved_at ? t('inbox.resolved') : t(`priority.${thread.priority}`)}
        />
      </div>
      <div className="min-w-0 flex-1">
        <div className="flex items-baseline gap-2">
          <span className={'truncate text-xs ' + (unread ? 'font-semibold text-mist-300' : 'text-mist-500')}>{source?.name ?? '?'}</span>
          <span className="ml-auto shrink-0 text-xs text-mist-600 tabular-nums">{relative(thread.last_at, language, now)}</span>
        </div>
        <p className={'mt-0.5 flex items-center gap-2 text-sm ' + (unread ? 'font-semibold text-mist-100' : 'text-mist-300')}>
          {unread && <span className="h-1.5 w-1.5 shrink-0 rounded-full bg-accent-500" aria-label={t('inbox.unread')} />}
          <span className={'truncate ' + (thread.resolved_at ? 'text-mist-500' : '')}>{threadTitle(thread, t)}</span>
        </p>
        {thread.preview && thread.preview !== thread.title && <p className="mt-0.5 truncate text-xs text-mist-500">{thread.preview}</p>}
        <div className="mt-1.5 flex flex-wrap gap-1.5 empty:hidden">
          {thread.event_count > 1 && <Chip symbol="stack">×{thread.event_count}</Chip>}
          {thread.resolved_at && (
            <Chip symbol="resolved" tone="ok">
              {t('inbox.resolved')}
            </Chip>
          )}
          {thread.throttled_count > 0 && (
            <Chip symbol="shieldAlert" tone="warn">
              {t('inbox.throttledChip', { count: thread.throttled_count })}
            </Chip>
          )}
          {thread.pushed && (
            <Chip symbol="phone" tone="accent">
              {t('inbox.pushed')}
            </Chip>
          )}
        </div>
      </div>
    </li>
  )
}

function Chip({ symbol, tone = 'neutral', children }: { symbol: SymbolName; tone?: 'neutral' | 'ok' | 'warn' | 'accent'; children: ReactNode }) {
  const styles = {
    neutral: 'bg-ink-800 text-mist-400',
    ok: 'bg-ok-500/10 text-ok-500',
    warn: 'bg-warn-500/10 text-warn-500',
    accent: 'bg-accent-500/10 text-accent-400',
  }[tone]
  return (
    <span className={'inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[11px] font-medium ' + styles}>
      <Symbol name={symbol} className="h-3 w-3" />
      {children}
    </span>
  )
}
