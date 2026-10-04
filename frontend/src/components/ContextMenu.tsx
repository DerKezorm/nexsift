import { useEffect, useLayoutEffect, useRef, useState, type KeyboardEvent as ReactKeyboardEvent } from 'react'

import { Symbol, type SymbolName } from './Symbol'

export type MenuEntry =
  | { label: string; symbol?: SymbolName; shortcut?: string; danger?: boolean; run: () => void }
  | { heading: string }
  | 'separator'

/**
 * The menu behind a right click (or a long press, or Shift+F10). Opens at the pointer, stays inside the window,
 * works with arrow keys, and closes on Escape, on a click elsewhere, on scrolling and when the window changes.
 */
export function ContextMenu({ x, y, entries, label, onClose }: { x: number; y: number; entries: MenuEntry[]; label: string; onClose: () => void }) {
  const menu = useRef<HTMLDivElement>(null)
  const [place, setPlace] = useState({ left: x, top: y })

  // Measured after the first paint: a menu near the right or bottom edge opens towards the inside.
  useLayoutEffect(() => {
    const box = menu.current?.getBoundingClientRect()
    if (!box) return
    const margin = 8
    setPlace({
      left: Math.max(margin, Math.min(x, window.innerWidth - box.width - margin)),
      top: Math.max(margin, y + box.height > window.innerHeight - margin ? Math.max(margin, y - box.height) : y),
    })
  }, [x, y])

  useEffect(() => {
    items()[0]?.focus()
    function away(event: Event) {
      if (!menu.current?.contains(event.target as Node)) onClose()
    }
    function scrolled(event: Event) {
      if (!menu.current?.contains(event.target as Node)) onClose()
    }
    document.addEventListener('pointerdown', away, true)
    document.addEventListener('scroll', scrolled, true)
    window.addEventListener('resize', onClose)
    window.addEventListener('blur', onClose)
    return () => {
      document.removeEventListener('pointerdown', away, true)
      document.removeEventListener('scroll', scrolled, true)
      window.removeEventListener('resize', onClose)
      window.removeEventListener('blur', onClose)
    }
  }, [onClose])

  function items(): HTMLButtonElement[] {
    return Array.from(menu.current?.querySelectorAll<HTMLButtonElement>('[role="menuitem"]') ?? [])
  }

  function onKey(event: ReactKeyboardEvent) {
    // The inbox listens on the window for its own keys; inside the menu every key is the menu's.
    event.stopPropagation()
    const all = items()
    const index = all.indexOf(document.activeElement as HTMLButtonElement)
    let next: HTMLButtonElement | undefined
    if (event.key === 'ArrowDown') next = all[(index + 1) % all.length]
    else if (event.key === 'ArrowUp') next = all[(index - 1 + all.length) % all.length]
    else if (event.key === 'Home') next = all[0]
    else if (event.key === 'End') next = all[all.length - 1]
    else if (event.key === 'Escape' || event.key === 'Tab') onClose()
    else return
    event.preventDefault()
    next?.focus()
  }

  return (
    <div
      ref={menu}
      role="menu"
      aria-label={label}
      onKeyDown={onKey}
      onContextMenu={(event) => event.preventDefault()}
      style={{ left: place.left, top: place.top }}
      className="fixed z-50 flex max-h-[calc(100vh-16px)] min-w-56 flex-col overflow-y-auto rounded-xl border border-ink-700 bg-ink-850 p-1 shadow-2xl shadow-black/50"
    >
      {entries.map((entry, index) => {
        if (entry === 'separator') return <div key={index} role="separator" className="my-1 border-t border-ink-700" />
        if ('heading' in entry) {
          return (
            <p key={index} className="px-3 pt-1.5 pb-1 text-xs font-semibold text-mist-500">
              {entry.heading}
            </p>
          )
        }
        return (
          <button
            key={index}
            type="button"
            role="menuitem"
            onClick={() => {
              onClose()
              entry.run()
            }}
            className={
              'flex items-center gap-2.5 rounded-lg px-3 py-1.5 text-left text-sm focus:outline-none ' +
              (entry.danger ? 'text-bad-500 hover:bg-bad-500/10 focus:bg-bad-500/10' : 'text-mist-200 hover:bg-ink-800 focus:bg-ink-800')
            }
          >
            {entry.symbol ? <Symbol name={entry.symbol} className="h-4 w-4 shrink-0 opacity-80" /> : <span className="w-4" />}
            <span className="flex-1">{entry.label}</span>
            {entry.shortcut && <kbd className="ml-4">{entry.shortcut}</kbd>}
          </button>
        )
      })}
    </div>
  )
}
