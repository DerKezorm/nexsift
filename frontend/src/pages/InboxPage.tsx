import { useCallback, useEffect, useMemo, useRef, useState, type MouseEvent, type ReactNode } from 'react'
import { useTranslation } from 'react-i18next'
import { Link, useSearchParams } from 'react-router-dom'

import { api, errorMessage } from '../api/client'
import type { Source, ThreadDetail as Detail, ThreadSummary, View } from '../api/types'
import { ContextMenu, type MenuEntry } from '../components/ContextMenu'
import { Help } from '../components/Help'
import { useNotice } from '../components/Notice'
import { SourceMark } from '../components/SourceMark'
import { Symbol, type SymbolName } from '../components/Symbol'
import { ShortcutHelp } from '../components/inbox/ShortcutHelp'
import { ThreadDetail } from '../components/inbox/ThreadDetail'
import { Welcome } from '../components/inbox/Welcome'
import { isMuted, useCounts, useSources, useTargets } from '../lib/data'
import { useLiveVersion } from '../lib/live'
import { PRIORITY_DOT, RESOLVED_BY_HAND, resolvable } from '../lib/priority'
import { threadPreview, threadTitle } from '../lib/threadTitle'
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
  const [searchParams, setSearchParams] = useSearchParams()

  // A tap on a push notification opens /?thread=<id>: show that line, then tidy the address.
  useEffect(() => {
    const wanted = Number(searchParams.get('thread'))
    if (!wanted) return
    setSelectedId(wanted)
    setDetailOpen(true)
    setSearchParams({}, { replace: true })
  }, [searchParams, setSearchParams])

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

  // Several lines at once: Ctrl or Shift with a click, x, Ctrl+A, or "Select" in the menu. The actions then act on all of them.
  const [picked, setPicked] = useState<Set<number>>(new Set())
  const anchor = useRef<number | null>(null)
  const pickedThreads = useMemo(() => threads.filter((thread) => picked.has(thread.id)), [threads, picked])
  const acting = useMemo(() => (pickedThreads.length > 0 ? pickedThreads : selected ? [selected] : []), [pickedThreads, selected])
  const [menu, setMenu] = useState<{ x: number; y: number; label: string; entries: MenuEntry[] } | null>(null)
  const closeMenu = useCallback(() => setMenu(null), [])

  // Another view, source or search shows other lines; a selection from before would act on what is out of sight.
  useEffect(() => setPicked(new Set()), [params])

  const togglePick = useCallback(
    (id: number, withOpen = false) => {
      setPicked((current) => {
        const next = new Set(current)
        // Like in a file manager: Ctrl+click next to the open line takes that one along.
        if (withOpen && current.size === 0 && selectedId !== null && selectedId !== id) next.add(selectedId)
        if (next.has(id)) next.delete(id)
        else next.add(id)
        return next
      })
      anchor.current = id
    },
    [selectedId],
  )

  const pickRange = useCallback(
    (id: number) => {
      const from = threads.findIndex((thread) => thread.id === (anchor.current ?? selectedId))
      const to = threads.findIndex((thread) => thread.id === id)
      if (from < 0 || to < 0) return togglePick(id)
      const [low, high] = from < to ? [from, to] : [to, from]
      setPicked(new Set(threads.slice(low, high + 1).map((thread) => thread.id)))
      setSelectedId(id)
    },
    [threads, selectedId, togglePick],
  )

  const pickAll = useCallback(() => setPicked(new Set(threads.map((thread) => thread.id))), [threads])

  /** Threads leave the view: the next one below the open one takes its place (or the one above at the end). */
  const leave = useCallback(
    (ids: number[]) => {
      const gone = new Set(ids)
      if (selectedId !== null && gone.has(selectedId)) {
        const index = threads.findIndex((thread) => thread.id === selectedId)
        const after = threads.slice(index + 1).find((thread) => !gone.has(thread.id)) ?? [...threads.slice(0, index)].reverse().find((thread) => !gone.has(thread.id))
        setSelectedId(after?.id ?? null)
      }
      setThreads((current) => current.filter((thread) => !gone.has(thread.id)))
      setPicked((current) => new Set([...current].filter((id) => !gone.has(id))))
    },
    [threads, selectedId],
  )

  /** Undo for a state change: every thread goes back to the state it had. */
  const putBack = useCallback(
    (list: ThreadSummary[]) => {
      const byState = new Map<string, number[]>()
      for (const thread of list) byState.set(thread.state, [...(byState.get(thread.state) ?? []), thread.id])
      for (const [state, ids] of byState) void api.post('/api/threads/state', { ids, state }).catch((caught) => notify({ text: errorMessage(caught) }))
    },
    [notify],
  )

  const archive = useCallback(
    async (list: ThreadSummary[]) => {
      if (list.length === 0) return
      const back = list.every((thread) => thread.state === 'archived')
      const ids = list.map((thread) => thread.id)
      leave(ids)
      try {
        await api.post('/api/threads/state', { ids, state: back ? 'read' : 'archived' })
        notify({
          text: back ? t('inbox.movedBack', { count: ids.length }) : t('inbox.archived', { count: ids.length }),
          action: { label: t('inbox.undo'), run: () => putBack(list) },
        })
      } catch (caught) {
        notify({ text: errorMessage(caught) })
      }
    },
    [leave, notify, putBack, t],
  )

  const toggleRead = useCallback(
    async (list: ThreadSummary[]) => {
      if (list.length === 0) return
      const state = list.some((thread) => thread.state === 'unread') ? 'read' : 'unread'
      const ids = new Set(list.map((thread) => thread.id))
      setThreads((current) => current.map((item) => (ids.has(item.id) ? { ...item, state } : item)))
      await api.post('/api/threads/state', { ids: [...ids], state }).catch((caught) => notify({ text: errorMessage(caught) }))
    },
    [notify],
  )

  const destroy = useCallback(
    async (list: ThreadSummary[]) => {
      if (list.length === 0) return
      const ids = list.map((thread) => thread.id)
      leave(ids)
      try {
        await api.post('/api/threads/delete', { ids })
        notify({ text: t('inbox.deleted', { count: ids.length }), action: { label: t('inbox.undo'), run: () => void api.post('/api/threads/restore', { ids }) } })
      } catch (caught) {
        notify({ text: errorMessage(caught) })
      }
    },
    [leave, notify, t],
  )

  /** After closing by hand: out of "critical open", elsewhere the line stays and shows it as done. */
  const closed = useCallback(
    (ids: number[]) => {
      if (view === 'crit') return leave(ids)
      const done = new Set(ids)
      const at = new Date().toISOString()
      setThreads((current) => current.map((thread) => (done.has(thread.id) ? { ...thread, resolved_at: at, resolved_by: RESOLVED_BY_HAND } : thread)))
    },
    [view, leave],
  )

  const reopenAction = useCallback(
    (ids: number[]) => ({ label: t('inbox.undo'), run: () => void api.post('/api/threads/reopen', { ids }).catch((caught) => notify({ text: errorMessage(caught) })) }),
    [notify, t],
  )

  const resolve = useCallback(
    async (list: ThreadSummary[]) => {
      const ids = list.filter(resolvable).map((thread) => thread.id)
      if (ids.length === 0) return
      closed(ids)
      try {
        const result = await api.post<{ changed: number[] }>('/api/threads/resolve', { ids })
        notify({ text: t('inbox.resolvedNow', { count: result.changed.length }), action: reopenAction(result.changed) })
      } catch (caught) {
        notify({ text: errorMessage(caught) })
        void load()
      }
    },
    [closed, notify, reopenAction, load, t],
  )

  const resolveAll = useCallback(
    async (sourceId: number | null) => {
      try {
        const result = await api.post<{ changed: number[] }>('/api/threads/resolve-all', { source_id: sourceId })
        if (result.changed.length === 0) return notify({ text: t('inbox.nothingOpen') })
        closed(result.changed)
        notify({ text: t('inbox.resolvedNow', { count: result.changed.length }), action: reopenAction(result.changed) })
      } catch (caught) {
        notify({ text: errorMessage(caught) })
      }
    },
    [closed, notify, reopenAction, t],
  )

  const muteSource = useCallback(
    async (source: Source | undefined) => {
      if (!source) return
      const muted = isMuted(source)
      try {
        await api.post(`/api/sources/${source.id}/mute`, { minutes: muted ? 0 : 60 })
        notify({ text: muted ? t('inbox.unmuted', { name: source.name }) : t('inbox.muted', { name: source.name }) })
      } catch (caught) {
        notify({ text: errorMessage(caught) })
      }
    },
    [notify, t],
  )

  const markAllRead = useCallback(
    async (inView: View, sourceId: number | null) => {
      try {
        const result = await api.post<{ changed: number }>('/api/threads/read-all', { view: inView, source_id: sourceId })
        notify({ text: t('inbox.markedRead', { count: result.changed }) })
        void load()
      } catch (caught) {
        notify({ text: errorMessage(caught) })
      }
    },
    [notify, load, t],
  )

  const modifier = /Mac|iPhone|iPad/.test(navigator.platform) ? '⌘' : t('inbox.menu.ctrl')

  const threadMenu = useCallback(
    (list: ThreadSummary[]): MenuEntry[] => {
      const one = list.length === 1 ? list[0] : null
      const entries: MenuEntry[] = []
      if (!one) entries.push({ heading: t('inbox.menu.count', { count: list.length }) })
      if (list.some(resolvable)) entries.push({ label: t('inbox.action.resolve'), symbol: 'resolved', shortcut: 'r', run: () => void resolve(list) })
      entries.push({
        label: list.every((thread) => thread.state === 'archived') ? t('inbox.action.unarchive') : t('inbox.action.archive'),
        symbol: 'archive',
        shortcut: 'e',
        run: () => void archive(list),
      })
      entries.push({
        label: list.some((thread) => thread.state === 'unread') ? t('inbox.action.markRead') : t('inbox.action.markUnread'),
        symbol: 'unread',
        shortcut: 'u',
        run: () => void toggleRead(list),
      })
      const link = one?.links[0]
      if (link) entries.push({ label: t('inbox.menu.openLink'), symbol: 'external', shortcut: 'o', run: () => window.open(link.url, '_blank', 'noopener,noreferrer') })
      entries.push('separator')
      if (one) {
        const source = sourceById.get(one.source_id)
        if (source) {
          entries.push({
            label: sourceFilter === source.id ? t('inbox.showAllSources') : t('inbox.onlySource', { name: source.name }),
            symbol: 'rules',
            run: () => setSourceFilter(sourceFilter === source.id ? null : source.id),
          })
          entries.push({ label: isMuted(source) ? t('inbox.action.unmute') : t('inbox.action.mute'), symbol: 'mute', shortcut: 'm', run: () => void muteSource(source) })
        }
        entries.push({ label: t('inbox.menu.select'), symbol: 'check', shortcut: 'x', run: () => togglePick(one.id) })
      } else {
        entries.push({ label: t('inbox.menu.selectAll'), symbol: 'list', shortcut: `${modifier}+A`, run: pickAll })
        entries.push({ label: t('inbox.menu.clearSelection'), symbol: 'close', shortcut: 'Esc', run: () => setPicked(new Set()) })
      }
      entries.push('separator')
      entries.push({ label: t('inbox.action.delete'), symbol: 'trash', shortcut: 'd', danger: true, run: () => void destroy(list) })
      return entries
    },
    [archive, destroy, modifier, muteSource, pickAll, resolve, sourceById, sourceFilter, t, togglePick, toggleRead],
  )

  /** Right click on a line: on a picked one the menu is for all picked ones, otherwise for that line alone. */
  const openThreadMenu = useCallback(
    (thread: ThreadSummary, x: number, y: number) => {
      let list = [thread]
      if (picked.has(thread.id) && pickedThreads.length > 1) list = pickedThreads
      else {
        setPicked(new Set())
        setSelectedId(thread.id)
      }
      setMenu({ x, y, label: list.length > 1 ? t('inbox.menu.count', { count: list.length }) : threadTitle(thread, t), entries: threadMenu(list) })
    },
    [picked, pickedThreads, threadMenu, t],
  )

  function openSourceMenu(source: Source, x: number, y: number) {
    const entries: MenuEntry[] = [
      {
        label: sourceFilter === source.id ? t('inbox.showAllSources') : t('inbox.onlySource', { name: source.name }),
        symbol: 'rules',
        run: () => setSourceFilter(sourceFilter === source.id ? null : source.id),
      },
      { label: t('inbox.menu.readAllSource'), symbol: 'check', run: () => void markAllRead('inbox', source.id) },
      { label: t('inbox.menu.resolveAllSource'), symbol: 'resolved', run: () => void resolveAll(source.id) },
      'separator',
      { label: isMuted(source) ? t('inbox.action.unmute') : t('inbox.action.mute'), symbol: 'mute', run: () => void muteSource(source) },
    ]
    setMenu({ x, y, label: source.name, entries })
  }

  function openViewMenu(key: View, x: number, y: number): boolean {
    const entries: MenuEntry[] = []
    if (key !== 'archived') entries.push({ label: t('inbox.menu.readAllView'), symbol: 'check', run: () => void markAllRead(key, null) })
    if (key === 'crit') entries.push({ label: t('inbox.menu.resolveAll'), symbol: 'resolved', run: () => void resolveAll(null) })
    if (entries.length === 0) return false
    setMenu({ x, y, label: t(`inbox.view.${key}`), entries })
    return true
  }

  useEffect(() => {
    function onKey(event: KeyboardEvent) {
      if (typing(event.target)) {
        if (event.key === 'Escape') (event.target as HTMLElement).blur()
        return
      }
      const key = event.key
      if ((event.ctrlKey || event.metaKey) && !event.altKey && key.toLowerCase() === 'a') {
        pickAll()
        event.preventDefault()
        return
      }
      if ((key === 'ContextMenu' || (event.shiftKey && key === 'F10')) && selected) {
        const row = listRef.current?.querySelector(`[data-thread="${selected.id}"]`)?.getBoundingClientRect()
        openThreadMenu(selected, row ? row.left + 48 : 0, row ? row.top + row.height / 2 : 0)
        event.preventDefault()
        return
      }
      if (event.ctrlKey || event.metaKey || event.altKey) return
      if (key === '?') setHelp((open) => !open)
      else if (key === 'Escape') {
        if (help) setHelp(false)
        else if (picked.size > 0) setPicked(new Set())
        else setDetailOpen(false)
      } else if (event.shiftKey && (key === 'J' || key === 'ArrowDown' || key === 'K' || key === 'ArrowUp')) {
        // Shift with up or down takes the next line into the selection, like in a file manager.
        const index = threads.findIndex((thread) => thread.id === selectedId)
        const target = threads[Math.min(threads.length - 1, Math.max(0, index + (key === 'J' || key === 'ArrowDown' ? 1 : -1)))]
        if (!selected || !target) return
        setPicked((current) => new Set([...current, selected.id, target.id]))
        setSelectedId(target.id)
      } else if (key === 'j' || key === 'ArrowDown') move(1)
      else if (key === 'k' || key === 'ArrowUp') move(-1)
      else if (key === 'Enter' && selected) setDetailOpen(true)
      else if (key === 'x' && selected) togglePick(selected.id)
      else if (key === 'e') void archive(acting)
      else if (key === 'u') void toggleRead(acting)
      else if (key === 'r') void resolve(acting)
      else if (key === 'd' || key === 'Delete' || key === '#') void destroy(acting)
      else if (key === 'm' && selected) void muteSource(sourceById.get(selected.source_id))
      else if (key === 'o' && selected?.links[0]) window.open(selected.links[0].url, '_blank', 'noopener,noreferrer')
      else if (key === '/') searchBox.current?.focus()
      else if (['1', '2', '3', '4'].includes(key)) setView(VIEWS[Number(key) - 1].key)
      else return
      event.preventDefault()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [help, move, selected, selectedId, threads, picked, acting, archive, toggleRead, resolve, destroy, muteSource, sourceById, pickAll, togglePick, openThreadMenu])

  function clickRow(thread: ThreadSummary, event: MouseEvent) {
    if (event.shiftKey) return pickRange(thread.id)
    if (event.ctrlKey || event.metaKey) return togglePick(thread.id, true)
    // While picking on a phone, a tap adds or removes; with a mouse a plain click starts over, as everywhere else.
    if (picked.size > 0 && (event.nativeEvent as PointerEvent).pointerType === 'touch') return togglePick(thread.id)
    setPicked(new Set())
    anchor.current = thread.id
    setSelectedId(thread.id)
    setDetailOpen(true)
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
              onContextMenu={(event) => {
                if (openViewMenu(key, event.clientX, event.clientY)) event.preventDefault()
              }}
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
              onMenu={(x, y) => openSourceMenu(source, x, y)}
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
          {pickedThreads.length > 0 ? (
            <div className="flex min-h-[38px] items-center gap-1" role="toolbar" aria-label={t('inbox.menu.count', { count: pickedThreads.length })}>
              <button type="button" onClick={() => setPicked(new Set())} title={`${t('inbox.menu.clearSelection')} (Esc)`} aria-label={t('inbox.menu.clearSelection')} className="rounded-full p-2 text-mist-500 hover:bg-ink-850 hover:text-mist-100">
                <Symbol name="close" />
              </button>
              <span className="mr-auto text-sm font-semibold text-mist-100 tabular-nums">{t('inbox.menu.count', { count: pickedThreads.length })}</span>
              {pickedThreads.length < threads.length && (
                <button type="button" onClick={pickAll} className="mr-1 rounded-full px-2.5 py-1 text-xs font-medium text-accent-400 hover:bg-accent-500/10">
                  {t('inbox.menu.selectAll')}
                </button>
              )}
              {pickedThreads.some(resolvable) && <BarButton symbol="resolved" label={t('inbox.action.resolve')} shortcut="r" onClick={() => void resolve(pickedThreads)} />}
              <BarButton
                symbol="archive"
                label={pickedThreads.every((thread) => thread.state === 'archived') ? t('inbox.action.unarchive') : t('inbox.action.archive')}
                shortcut="e"
                onClick={() => void archive(pickedThreads)}
              />
              <BarButton
                symbol="unread"
                label={pickedThreads.some((thread) => thread.state === 'unread') ? t('inbox.action.markRead') : t('inbox.action.markUnread')}
                shortcut="u"
                onClick={() => void toggleRead(pickedThreads)}
              />
              <BarButton symbol="trash" label={t('inbox.action.delete')} shortcut="d" danger onClick={() => void destroy(pickedThreads)} />
            </div>
          ) : (
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
            {view === 'crit' && threads.length > 0 && (
              <button
                type="button"
                onClick={() => void resolveAll(sourceFilter)}
                title={sourceFilter ? t('inbox.resolveAllSourceHelp', { name: sourceById.get(sourceFilter)?.name }) : t('inbox.resolveAllHelp')}
                className="inline-flex shrink-0 items-center gap-1.5 rounded-full border border-ok-500/40 bg-ok-500/10 py-2 pr-3.5 pl-2.5 text-xs font-semibold text-ok-500 hover:bg-ok-500/20"
              >
                <Symbol name="resolved" />
                {t('inbox.resolveAll')}
              </button>
            )}
            <button
              type="button"
              onClick={() => void markAllRead(view, sourceFilter)}
              title={t('inbox.markAllRead')}
              aria-label={t('inbox.markAllRead')}
              className="rounded-full border border-ink-700 bg-ink-850 p-2 text-mist-500 hover:text-mist-100"
            >
              <Symbol name="check" />
            </button>
          </div>
          )}
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
          <ul ref={listRef} className="ns-scroll min-h-0 flex-1 overflow-y-auto" role="listbox" aria-multiselectable="true" aria-label={t('inbox.list')}>
            {threads.map((thread) => (
              <ThreadRow
                key={thread.id}
                thread={thread}
                source={sourceById.get(thread.source_id)}
                selected={thread.id === selectedId}
                picked={picked.has(thread.id)}
                picking={pickedThreads.length > 0}
                fresh={fresh.has(thread.id)}
                now={now}
                language={i18n.language}
                onClick={(event) => clickRow(thread, event)}
                onPick={() => togglePick(thread.id)}
                onMenu={(x, y) => openThreadMenu(thread, x, y)}
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
            onArchive={() => void archive([selected])}
            onToggleRead={() => void toggleRead([selected])}
            onResolve={() => void resolve([selected])}
            onDelete={() => void destroy([selected])}
            onMute={() => void muteSource(sourceById.get(selected.source_id))}
          />
        ) : (
          <div className="flex flex-1 items-center justify-center rounded-2xl border border-dashed border-ink-700 px-6 text-center text-sm text-mist-600">
            {noSources ? t('inbox.nothingYet') : t('inbox.nothingSelected')}
          </div>
        )}
      </section>

      {help && <ShortcutHelp onClose={() => setHelp(false)} />}
      {menu && <ContextMenu x={menu.x} y={menu.y} label={menu.label} entries={menu.entries} onClose={closeMenu} />}
    </div>
  )
}

function BarButton({ symbol, label, shortcut, danger = false, onClick }: { symbol: SymbolName; label: string; shortcut: string; danger?: boolean; onClick: () => void }) {
  return (
    <button
      type="button"
      onClick={onClick}
      title={`${label} (${shortcut})`}
      aria-label={label}
      aria-keyshortcuts={shortcut}
      className={'rounded-full p-2 transition-colors ' + (danger ? 'text-mist-500 hover:bg-bad-500/10 hover:text-bad-500' : 'text-mist-500 hover:bg-ink-850 hover:text-mist-100')}
    >
      <Symbol name={symbol} />
    </button>
  )
}

function SourceFilterButton({
  source,
  active,
  unread,
  muted,
  onClick,
  onMenu,
}: {
  source: Source
  active: boolean
  unread: number
  muted: boolean
  onClick: () => void
  onMenu: (x: number, y: number) => void
}) {
  const { t } = useTranslation()
  return (
    <button
      type="button"
      onClick={onClick}
      onContextMenu={(event) => {
        event.preventDefault()
        onMenu(event.clientX, event.clientY)
      }}
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
  picked,
  picking,
  fresh,
  now,
  language,
  onClick,
  onPick,
  onMenu,
}: {
  thread: ThreadSummary
  source?: Source
  selected: boolean
  picked: boolean
  picking: boolean
  fresh: boolean
  now: number
  language: string
  onClick: (event: MouseEvent) => void
  onPick: () => void
  onMenu: (x: number, y: number) => void
}) {
  const { t } = useTranslation()
  const unread = thread.state === 'unread'
  const title = threadTitle(thread, t)
  const preview = threadPreview(thread, t)
  return (
    <li
      data-thread={thread.id}
      role="option"
      aria-selected={picking ? picked : selected}
      onClick={onClick}
      // Shift+click picks a range; without this the browser would also mark the text in between.
      onMouseDown={(event) => {
        if (event.shiftKey) event.preventDefault()
      }}
      onContextMenu={(event) => {
        event.preventDefault()
        onMenu(event.clientX, event.clientY)
      }}
      className={
        'group relative flex cursor-pointer gap-3 border-b border-ink-700/60 px-4 py-3 transition-colors ' +
        (picked ? 'bg-accent-500/15 ' : selected ? 'bg-accent-500/10 ' : 'hover:bg-ink-850 ') +
        (fresh ? 'ns-arrive' : '')
      }
    >
      {selected && <span className="absolute inset-y-0 left-0 w-0.5 bg-accent-500" aria-hidden="true" />}
      <div className="relative self-start">
        <SourceMark kind={source?.kind} protocol={source?.protocol} />
        {/* Like Gmail: under the pointer, or while picking, the source mark turns into a box to tick. */}
        <button
          type="button"
          role="checkbox"
          aria-checked={picked}
          aria-label={t('inbox.menu.select')}
          onClick={(event) => {
            event.stopPropagation()
            onPick()
          }}
          className={
            'absolute inset-0 flex items-center justify-center rounded-lg border transition-opacity ' +
            (picked ? 'border-accent-500 bg-accent-500 text-on-accent opacity-100 ' : 'border-ink-600 bg-ink-850 text-transparent ') +
            (picked || picking ? 'opacity-100' : 'opacity-0 group-hover:opacity-100 focus-visible:opacity-100')
          }
        >
          <Symbol name="check" className="h-4 w-4" />
        </button>
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
          <span className={'truncate ' + (thread.resolved_at ? 'text-mist-500' : '')}>{title}</span>
        </p>
        {preview && preview !== title && <p className="mt-0.5 truncate text-xs text-mist-500">{preview}</p>}
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
