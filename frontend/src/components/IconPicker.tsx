import { useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'

import { api } from '../api/client'
import type { IconName, Protocol } from '../api/types'
import { iconPreview, isOwnIcon } from '../lib/icons'
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
      <div className="grid max-h-[55vh] grid-cols-3 gap-1.5 overflow-y-auto sm:grid-cols-6">
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
            <img src={iconPreview(entry.icon) ?? undefined} alt="" loading="lazy" decoding="async" className="h-8 w-8 object-contain" />
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
