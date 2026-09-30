import { createContext, useCallback, useContext, useEffect, useState } from 'react'
import type { ReactNode } from 'react'

import { Symbol } from './Symbol'

interface Notice {
  text: string
  action?: { label: string; run: () => void }
}

const NoticeContext = createContext<(notice: Notice) => void>(() => {})

/** A short sentence at the bottom center that disappears again on its own, optionally with one action (undo). */
export function NoticeProvider({ children }: { children: ReactNode }) {
  const [notice, setNotice] = useState<Notice | null>(null)
  const notify = useCallback((next: Notice) => setNotice(next), [])

  useEffect(() => {
    if (!notice) return
    const timer = window.setTimeout(() => setNotice(null), notice.action ? 6000 : 2600)
    return () => window.clearTimeout(timer)
  }, [notice])

  return (
    <NoticeContext.Provider value={notify}>
      {children}
      <div className="pointer-events-none fixed inset-x-0 bottom-6 z-50 flex justify-center px-4" role="status" aria-live="polite">
        {notice && (
          <p className="pointer-events-auto flex items-center gap-3 rounded-full border border-accent-500/40 bg-ink-850 py-2 pr-2 pl-4 text-sm text-mist-200 shadow-2xl shadow-black/50">
            <Symbol name="info" className="h-4 w-4 text-accent-400" />
            {notice.text}
            {notice.action && (
              <button
                type="button"
                onClick={() => {
                  notice.action?.run()
                  setNotice(null)
                }}
                className="rounded-full bg-accent-500/15 px-3 py-1 text-xs font-semibold text-accent-400 hover:bg-accent-500/25"
              >
                {notice.action.label}
              </button>
            )}
          </p>
        )}
      </div>
    </NoticeContext.Provider>
  )
}

// eslint-disable-next-line react-refresh/only-export-components
export function useNotice(): (notice: Notice) => void {
  return useContext(NoticeContext)
}
