import { useState, type ReactNode } from 'react'
import { useTranslation } from 'react-i18next'
import { Link } from 'react-router-dom'

import type { Source, ThreadDetail as Detail } from '../../api/types'
import { isMuted } from '../../lib/data'
import { PRIORITY_CHIP, PRIORITY_DOT, RESOLVED_BY_HAND, resolvable } from '../../lib/priority'
import { ruleName } from '../../lib/ruleNames'
import { textBody, textTitle } from '../../lib/senderTexts'
import { threadTitle } from '../../lib/threadTitle'
import { clock, duration, relative } from '../../lib/time'
import { Help } from '../Help'
import { SourceMark } from '../SourceMark'
import { Symbol, type SymbolName } from '../Symbol'

/** How many events of a bundle show before "show all". */
const FOLDED = 5

export function ThreadDetail({
  thread,
  source,
  now,
  onBack,
  onArchive,
  onToggleRead,
  onResolve,
  onDelete,
  onMute,
}: {
  thread: Detail
  source?: Source
  now: number
  onBack: () => void
  onArchive: () => void
  onToggleRead: () => void
  onResolve: () => void
  onDelete: () => void
  onMute: () => void
}) {
  const { t, i18n } = useTranslation()
  const language = i18n.language
  const [expanded, setExpanded] = useState<number | null>(null)
  const [showAll, setShowAll] = useState(false)
  const events = showAll ? thread.events : thread.events.slice(0, FOLDED)
  const latest = thread.events[0]
  const links = latest?.links ?? []
  const muted = isMuted(source, now)
  const sent = thread.deliveries.filter((delivery) => delivery.status === 'sent')
  const waiting = thread.deliveries.filter((delivery) => delivery.status === 'pending')
  const failed = thread.deliveries.filter((delivery) => delivery.status === 'failed')
  // The all-clear that closed it, in the chosen language when nexsift worded it.
  const closer = thread.events.find((event) => event.title === thread.resolved_by)
  const resolvedBy = textTitle(t, closer?.texts) ?? thread.resolved_by

  return (
    <article className="flex min-h-0 w-full flex-col border-ink-700 bg-ink-900/60 sm:rounded-2xl sm:border">
      <header className="flex flex-col gap-3 border-b border-ink-700 p-4 sm:p-5">
        <div className="flex items-center gap-2">
          <button type="button" onClick={onBack} className="rounded-full p-1.5 text-mist-500 hover:bg-ink-850 hover:text-mist-100 lg:hidden" aria-label={t('inbox.back')}>
            <Symbol name="chevronLeft" />
          </button>
          <div className="ml-auto flex items-center gap-1">
            {resolvable(thread) && (
              <button
                type="button"
                onClick={onResolve}
                title={`${t('inbox.resolveHelp')} (r)`}
                aria-keyshortcuts="r"
                className="mr-1 inline-flex items-center gap-1.5 rounded-full border border-ok-500/40 bg-ok-500/10 py-1.5 pr-3.5 pl-2.5 text-xs font-semibold text-ok-500 hover:bg-ok-500/20"
              >
                <Symbol name="resolved" />
                {t('inbox.action.resolve')}
              </button>
            )}
            <ToolButton symbol="archive" label={thread.state === 'archived' ? t('inbox.action.unarchive') : t('inbox.action.archive')} shortcut="e" onClick={onArchive} />
            <ToolButton symbol="unread" label={thread.state === 'unread' ? t('inbox.action.markRead') : t('inbox.action.markUnread')} shortcut="u" onClick={onToggleRead} />
            <ToolButton symbol="mute" label={muted ? t('inbox.action.unmute') : t('inbox.action.mute')} shortcut="m" onClick={onMute} active={muted} />
            <ToolButton symbol="trash" label={t('inbox.action.delete')} shortcut="d" onClick={onDelete} danger />
          </div>
        </div>

        <div className="flex items-start gap-3">
          <SourceMark kind={source?.kind} protocol={source?.protocol} src={thread.icon_url ?? source?.icon_url} className="h-10 w-10 text-xs" />
          <div className="min-w-0 flex-1">
            <h2 className="text-lg leading-snug font-semibold break-words text-mist-100">{threadTitle(thread, t)}</h2>
            <p className="mt-1 flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-mist-500">
              <span className="font-medium text-mist-300">{source?.name}</span>
              <span aria-hidden="true">·</span>
              <span>{t('inbox.via', { protocol: t(`protocol.${source?.protocol ?? 'webhook'}`) })}</span>
              <span aria-hidden="true">·</span>
              <span className="tabular-nums">
                {thread.event_count > 1
                  ? t('inbox.span', { count: thread.event_count, from: clock(thread.first_at, language), to: clock(thread.last_at, language) })
                  : clock(thread.last_at, language)}
              </span>
            </p>
          </div>
          <span className={'inline-flex shrink-0 items-center gap-1.5 rounded-full border px-2.5 py-0.5 text-xs font-semibold ' + PRIORITY_CHIP[thread.priority]}>
            <span className={'h-1.5 w-1.5 rounded-full ' + PRIORITY_DOT[thread.priority]} />
            {t(`priority.${thread.priority}`)}
          </span>
        </div>

        {links.length > 0 && (
          <div className="flex flex-wrap gap-2">
            {links.map((link, index) => (
              <a
                key={link.url}
                href={link.url}
                target="_blank"
                rel="noreferrer noopener"
                className="inline-flex max-w-full items-center gap-2 rounded-full bg-accent-500 px-4 py-2 text-sm font-semibold text-on-accent shadow-lg shadow-accent-700/25 hover:bg-accent-400"
              >
                <Symbol name="external" />
                <span className="truncate">{link.label || t('inbox.openLink')}</span>
                {index === 0 && <kbd className="border-on-accent/30 bg-on-accent/10 text-on-accent">o</kbd>}
              </a>
            ))}
          </div>
        )}
      </header>

      <div className="ns-scroll flex min-h-0 flex-1 flex-col gap-4 overflow-y-auto p-4 sm:p-5">
        {/* Why it looks like this: the part that sets nexsift apart from a plain relay. */}
        <div className="grid gap-2 sm:grid-cols-2">
          {thread.resolved_at && (
            <Fact symbol="resolved" tone="ok" title={t('inbox.fact.resolved', { after: duration(Date.parse(thread.resolved_at) - Date.parse(thread.first_at), language) })}>
              {thread.resolved_by === RESOLVED_BY_HAND ? t('inbox.fact.byHand') : resolvedBy}
            </Fact>
          )}
          {thread.throttled_count > 0 && (
            <Fact symbol="shieldAlert" tone="warn" title={t('inbox.fact.throttled', { count: thread.throttled_count })} help={t('inbox.fact.throttledHelp')}>
              {t('inbox.fact.throttledText')}
            </Fact>
          )}
          <Fact
            symbol="phone"
            tone={sent.length > 0 ? 'accent' : failed.length > 0 ? 'warn' : 'neutral'}
            title={sent.length > 0 ? t('inbox.fact.pushed') : waiting.length > 0 ? t('inbox.fact.pushWaiting') : failed.length > 0 ? t('inbox.fact.pushFailed') : t('inbox.fact.notPushed')}
            help={t('inbox.fact.pushHelp')}
          >
            {thread.deliveries.length > 0 ? (
              thread.deliveries.map((delivery) => (
                <span key={delivery.id} className="block tabular-nums">
                  {clock(delivery.sent_at ?? delivery.created_at, language)} · {delivery.target} · {t(`inbox.delivery.${delivery.kind}`)}
                  {delivery.status !== 'sent' && ` · ${t(`inbox.deliveryStatus.${delivery.status}`)}`}
                  {delivery.last_error && delivery.status !== 'sent' && <span className="block text-warn-500">{delivery.last_error}</span>}
                </span>
              ))
            ) : (
              <>
                {thread.push_mode === 'never'
                  ? t('inbox.fact.neverPush')
                  : muted
                    ? t('inbox.fact.notPushedMuted')
                    : t('inbox.fact.notPushedWhy', { priority: t(`priority.${thread.priority}`) })}{' '}
                <Link to="/rules#targets" className="text-accent-400 hover:text-accent-300">
                  {t('inbox.fact.targetsLink')}
                </Link>
              </>
            )}
          </Fact>
          <Fact symbol="rules" title={t('inbox.fact.rule')} help={t('inbox.fact.ruleHelp')}>
            {thread.rule_names.length > 0 ? thread.rule_names.map((name) => ruleName(t, name)).join(', ') : t('inbox.fact.noRule')}{' '}
            <Link to="/rules" className="text-accent-400 hover:text-accent-300">
              {t('inbox.fact.rulesLink')}
            </Link>
          </Fact>
        </div>

        <ol className="flex flex-col">
          {events.map((event) => (
            <li key={event.id} className="relative border-l border-ink-700 pb-4 pl-5 last:pb-0">
              <span className={'absolute top-1.5 -left-[5px] h-2.5 w-2.5 rounded-full border-2 border-ink-900 ' + PRIORITY_DOT[event.priority]} aria-hidden="true" />
              <div className="flex items-baseline gap-2">
                <p className="min-w-0 text-sm font-medium break-words text-mist-200">{textTitle(t, event.texts) ?? event.title}</p>
                <span className="ml-auto shrink-0 text-xs text-mist-600 tabular-nums" title={clock(event.received_at, language)}>
                  {relative(event.received_at, language, now)}
                </span>
              </div>
              {(textBody(t, event.texts) ?? event.body) && (
                <p className="mt-1 text-sm break-words whitespace-pre-line text-mist-400">{textBody(t, event.texts) ?? event.body}</p>
              )}
              {!event.recognized && (
                <p className="mt-1.5 inline-flex items-center gap-1.5 rounded-md bg-warn-500/10 px-2 py-0.5 text-xs text-warn-500">
                  <Symbol name="warn" className="h-3.5 w-3.5" />
                  {t('inbox.unrecognized')}
                  <Help label={t('inbox.unrecognized')}>{t('inbox.unrecognizedHelp')}</Help>
                </p>
              )}
              {event.raw && (
                <div>
                  <button
                    type="button"
                    onClick={() => setExpanded(expanded === event.id ? null : event.id)}
                    aria-expanded={expanded === event.id}
                    className="mt-1.5 inline-flex items-center gap-1 text-xs text-mist-600 hover:text-mist-300"
                  >
                    <Symbol name="code" className="h-3.5 w-3.5" />
                    {expanded === event.id ? t('inbox.hideRaw') : t('inbox.showRaw')}
                  </button>
                  {expanded === event.id && (
                    <pre className="ns-scroll mt-2 max-h-80 overflow-auto rounded-xl border border-ink-700 bg-ink-950 p-3 font-mono text-xs whitespace-pre-wrap text-mist-400">{event.raw}</pre>
                  )}
                </div>
              )}
            </li>
          ))}
        </ol>
        {thread.events.length > FOLDED && (
          <button type="button" onClick={() => setShowAll(!showAll)} className="self-start rounded-full bg-ink-850 px-3.5 py-1.5 text-xs font-medium text-mist-300 hover:text-mist-100">
            {showAll ? t('inbox.showFewer') : t('inbox.showAll', { count: thread.events.length - FOLDED })}
          </button>
        )}
        {thread.event_count > thread.events.length && <p className="text-xs text-mist-600">{t('inbox.olderGone', { count: thread.event_count - thread.events.length })}</p>}
      </div>
    </article>
  )
}

function ToolButton({ symbol, label, shortcut, onClick, danger = false, active = false }: { symbol: SymbolName; label: string; shortcut: string; onClick: () => void; danger?: boolean; active?: boolean }) {
  return (
    <button
      type="button"
      onClick={onClick}
      title={`${label} (${shortcut})`}
      aria-label={label}
      aria-keyshortcuts={shortcut}
      className={
        'rounded-full p-2 transition-colors ' +
        (danger ? 'text-mist-500 hover:bg-bad-500/10 hover:text-bad-500' : active ? 'bg-warn-500/10 text-warn-500' : 'text-mist-500 hover:bg-ink-850 hover:text-mist-100')
      }
    >
      <Symbol name={symbol} />
    </button>
  )
}

function Fact({ symbol, title, tone = 'neutral', help, children }: { symbol: SymbolName; title: string; tone?: 'neutral' | 'ok' | 'warn' | 'accent'; help?: ReactNode; children: ReactNode }) {
  const styles = {
    neutral: 'border-ink-700 bg-ink-850/60 text-mist-500',
    ok: 'border-ok-500/30 bg-ok-500/8 text-ok-500',
    warn: 'border-warn-500/30 bg-warn-500/8 text-warn-500',
    accent: 'border-accent-500/30 bg-accent-500/8 text-accent-400',
  }[tone]
  return (
    <div className={'flex gap-2.5 rounded-xl border px-3 py-2.5 ' + styles}>
      <Symbol name={symbol} className="mt-0.5 h-4 w-4 shrink-0" />
      <div className="min-w-0">
        <p className="flex items-center gap-1.5 text-xs font-semibold">
          {title}
          {help && <Help label={title}>{help}</Help>}
        </p>
        <div className="mt-0.5 text-xs text-mist-400">{children}</div>
      </div>
    </div>
  )
}
