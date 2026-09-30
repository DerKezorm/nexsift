import type { Protocol } from '../api/types'

const BY_KIND: Record<string, string> = {
  watchtower: 'WT',
  proxmox: 'PV',
  uptimekuma: 'UK',
  homeassistant: 'HA',
  synology: 'SY',
  paperless: 'PL',
  ups: 'UP',
  syslog: 'SL',
}

const BY_PROTOCOL: Record<Protocol, string> = {
  gotify: 'GO',
  ntfy: 'NT',
  discord: 'DC',
  webhook: 'WH',
  smtp: '@',
  syslog: 'SL',
}

/** Two letters instead of brand logos: the list stays calm, and no trademark is copied. */
export function SourceMark({ kind, protocol, className = 'h-8 w-8 text-[11px]' }: { kind?: string; protocol?: Protocol; className?: string }) {
  const letters = (kind && BY_KIND[kind]) || (protocol && BY_PROTOCOL[protocol]) || '?'
  return (
    <span
      className={'flex shrink-0 items-center justify-center rounded-lg border border-ink-700 bg-ink-800 font-mono font-semibold text-mist-300 ' + className}
      aria-hidden="true"
    >
      {letters}
    </span>
  )
}
