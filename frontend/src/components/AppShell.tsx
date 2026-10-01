import { useTranslation } from 'react-i18next'
import { NavLink, Outlet, useLocation } from 'react-router-dom'

import { useAuth } from '../auth'
import { useCounts } from '../lib/data'
import { useLiveConnected } from '../lib/live'
import { LanguageSwitcher } from './LanguageSwitcher'
import { Logo } from './Logo'
import { Symbol, type SymbolName } from './Symbol'
import { ThemeSwitcher } from './ThemeSwitcher'
import { WhatsNewAfterUpdate } from './WhatsNewAfterUpdate'

type NavItem = { to: string; label: string; symbol: SymbolName; end: boolean; right?: boolean }

function navClass(isActive: boolean, compact: boolean, right = false): string {
  return (
    (compact ? 'shrink-0 px-3 ' : 'px-3.5 ') +
    (right ? 'ml-auto ' : '') +
    'inline-flex items-center gap-2 rounded-full py-1.5 text-sm font-medium transition-colors ' +
    (isActive ? 'bg-accent-500/15 text-accent-400' : 'text-mist-500 hover:bg-ink-850 hover:text-mist-100')
  )
}

/**
 * Shell like the other nexapps: header with pills, settings on the right, everything in a centered column.
 * The inbox fills the window height, with no footer, like the workspace in nextrmnl.
 */
export function AppShell() {
  const { t } = useTranslation()
  const { account, signOut } = useAuth()
  const counts = useCounts()
  const live = useLiveConnected()
  const location = useLocation()
  const inbox = location.pathname === '/'
  const unread = counts.data?.views.unread ?? 0

  const items: NavItem[] = [
    { to: '/', label: t('nav.inbox'), symbol: 'inbox', end: true },
    { to: '/sources', label: t('nav.sources'), symbol: 'plug', end: false },
    { to: '/rules', label: t('nav.rules'), symbol: 'rules', end: false },
    { to: '/settings', label: t('nav.settings'), symbol: 'settings', end: false, right: true },
  ]

  const render = (item: NavItem, compact: boolean) => (
    <NavLink key={item.to} to={item.to} end={item.end} className={({ isActive }) => navClass(isActive, compact, item.right)}>
      <span className={compact ? 'hidden min-[441px]:inline' : ''}>
        <Symbol name={item.symbol} />
      </span>
      {item.label}
      {item.to === '/' && unread > 0 && (
        <span className="rounded-full bg-accent-500 px-1.5 text-[10px] leading-4 font-bold text-on-accent tabular-nums">{unread}</span>
      )}
    </NavLink>
  )

  return (
    <div className={'ns-glow flex flex-col ' + (inbox ? 'h-dvh overflow-hidden' : 'min-h-dvh')}>
      <header className="sticky top-0 z-20 shrink-0 border-b border-ink-700/80 bg-ink-950/80 backdrop-blur-xl">
        <div className="mx-auto flex max-w-[96rem] items-center gap-4 px-4 py-3 sm:px-6">
          <NavLink to="/" className="shrink-0" aria-label={t('nav.home')}>
            <Logo withWordmark />
          </NavLink>
          <nav className="hidden flex-1 items-center gap-1 lg:flex" aria-label={t('nav.main')}>
            {items.map((item) => render(item, false))}
          </nav>
          <div className="ml-auto flex items-center gap-2 sm:gap-3">
            <span
              title={live ? t('live.onHelp') : t('live.offHelp')}
              className={
                'inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1.5 text-xs font-medium ' +
                (live ? 'border-ok-500/30 bg-ok-500/10 text-ok-500' : 'border-warn-500/40 bg-warn-500/10 text-warn-500')
              }
            >
              <span className={'h-1.5 w-1.5 rounded-full ' + (live ? 'bg-ok-500' : 'animate-pulse bg-warn-500')} aria-hidden="true" />
              <span className="hidden sm:inline">{live ? t('live.on') : t('live.off')}</span>
            </span>
            <ThemeSwitcher />
            <LanguageSwitcher />
            <span
              className="hidden h-8 w-8 items-center justify-center rounded-full border border-ink-700 bg-ink-850 text-xs font-semibold text-mist-300 uppercase sm:flex"
              title={account?.name}
            >
              {account?.name.slice(0, 1)}
            </span>
            <button
              type="button"
              onClick={() => void signOut()}
              className="rounded-full border border-ink-700 bg-ink-850 p-1.5 text-mist-500 hover:text-mist-100"
              title={t('nav.signOut')}
              aria-label={t('nav.signOut')}
            >
              <Symbol name="logout" />
            </button>
          </div>
        </div>
        <nav className="flex gap-1 overflow-x-auto border-t border-ink-700/60 px-4 py-2 lg:hidden" aria-label={t('nav.main')}>
          {items.map((item) => render(item, true))}
        </nav>
      </header>

      {inbox ? (
        <main className="relative z-10 mx-auto flex min-h-0 w-full max-w-[96rem] flex-1 sm:px-6 sm:py-5">
          <Outlet />
        </main>
      ) : (
        <>
          <main className="relative z-10 mx-auto w-full max-w-7xl flex-1 px-4 pt-8 pb-16 sm:px-6">
            <Outlet />
          </main>
          <footer className="relative z-10 border-t border-ink-700/60">
            <div className="mx-auto flex max-w-7xl flex-wrap items-center justify-center gap-x-4 gap-y-2 px-4 py-5 text-xs text-mist-600 sm:px-6">
              <span>nexsift</span>
              <NavLink to="/about" className="hover:text-mist-300">
                {t('about.title')}
              </NavLink>
            </div>
          </footer>
        </>
      )}
      <WhatsNewAfterUpdate />
    </div>
  )
}
