import { useId } from 'react'

/**
 * nexsift mark: a funnel, many in, one out; the drop beside it is what gets through. Within the style of the
 * nexapps marks. The colors come from --color-mark-*, so the tile turns white in light mode.
 */
export function Logo({ className = 'h-8 w-8', withWordmark = false }: { className?: string; withWordmark?: boolean }) {
  // One id per mark: two marks on a page must not share a gradient.
  const gradient = `nexsift-mark-${useId().replace(/:/g, '')}`
  const mark = (
    <svg viewBox="0 0 64 64" className={className} aria-hidden="true">
      <defs>
        {/* userSpaceOnUse, so the gradient runs across the whole mark instead of restarting for each stroke. */}
        <linearGradient id={gradient} gradientUnits="userSpaceOnUse" x1="8" y1="8" x2="56" y2="56">
          <stop offset="0" style={{ stopColor: 'var(--color-mark-light)' }} />
          <stop offset=".5" style={{ stopColor: 'var(--color-mark-mid)' }} />
          <stop offset="1" style={{ stopColor: 'var(--color-mark-dark)' }} />
        </linearGradient>
      </defs>
      <rect x="2" y="2" width="60" height="60" rx="16" style={{ fill: 'var(--color-mark-bg)' }} />
      <rect x="2" y="2" width="60" height="60" rx="16" fill="none" stroke={`url(#${gradient})`} strokeWidth="2.5" strokeOpacity=".55" />
      <path d="M15 17h34L36.5 32v10L27.5 47V32Z" fill="none" stroke={`url(#${gradient})`} strokeWidth="4.5" strokeLinejoin="round" />
      <circle cx="44" cy="46" r="3" style={{ fill: 'var(--color-mark-mid)' }} />
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
