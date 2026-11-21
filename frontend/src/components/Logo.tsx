import { useId } from 'react'

/**
 * nexsift mark: a funnel, many in, one out; the dot beside it is what gets through.
 *
 * The source of every version is nexapps/icons-vergleich/neu.py; the same shape is in public/logo.svg (favicon) and
 * scripts/app-icons.mjs (home screen and notifications). The colors come from --color-mark-* in styles/index.css and
 * follow the theme: a dark tile in dark mode, a white one in light mode.
 */
export function Logo({ className = 'h-8 w-8', withWordmark = false }: { className?: string; withWordmark?: boolean }) {
  // One id per mark: two marks on a page must not share a gradient.
  const gradient = `nexsift-mark-${useId().replace(/[^a-zA-Z0-9_-]/g, '')}`
  const mark = (
    <svg viewBox="0 0 64 64" className={className} aria-hidden="true">
      <defs>
        {/* userSpaceOnUse, so the gradient runs across the whole mark instead of restarting for each stroke. */}
        <linearGradient id={gradient} gradientUnits="userSpaceOnUse" x1="10" y1="10" x2="54" y2="54">
          <stop offset="0" style={{ stopColor: 'var(--color-mark-light)' }} />
          <stop offset=".5" style={{ stopColor: 'var(--color-mark-mid)' }} />
          <stop offset="1" style={{ stopColor: 'var(--color-mark-dark)' }} />
        </linearGradient>
      </defs>
      <rect x="2" y="2" width="60" height="60" rx="16" style={{ fill: 'var(--color-mark-bg)' }} />
      <rect x="2.75" y="2.75" width="58.5" height="58.5" rx="15.3" fill="none" strokeWidth="1.5" style={{ stroke: 'var(--color-mark-rim)' }} />
      <path d="M13.5 15.5h37L37 32.5v11L27 49.5V32.5Z" fill="none" stroke={`url(#${gradient})`} strokeWidth="4.4" strokeLinejoin="round" />
      <circle cx="45" cy="47" r="3.8" strokeWidth="1.8" style={{ fill: 'var(--color-mark-dot)', stroke: 'var(--color-mark-bg)' }} />
    </svg>
  )
  if (!withWordmark) return mark
  return (
    <span className="flex items-center gap-2.5">
      {mark}
      <span className="hidden text-lg font-bold tracking-tight sm:inline">
        <span className="text-mist-500">NEX</span>
        <span className="text-accent-500">SIFT</span>
      </span>
    </span>
  )
}
