import { useState } from 'react'

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

/** The icon the operator picked for the source, or two letters: without one, and when the picture does not load. */
export function SourceMark({ kind, protocol, src, className = 'h-8 w-8 text-[11px]' }: { kind?: string; protocol?: Protocol; src?: string | null; className?: string }) {
  const [failed, setFailed] = useState<string | null>(null)
  const letters = (kind && BY_KIND[kind]) || (protocol && BY_PROTOCOL[protocol]) || '?'
  const box = 'flex shrink-0 items-center justify-center rounded-lg border border-ink-700 bg-ink-800 '
  if (src && failed !== src) {
    return (
      <span className={box + 'overflow-hidden ' + className} aria-hidden="true">
        <img src={src} alt="" className="h-[76%] w-[76%] object-contain" decoding="async" onError={() => setFailed(src)} />
      </span>
    )
  }
  return (
    <span className={box + 'font-mono font-semibold text-mist-300 ' + className} aria-hidden="true">
      {letters}
    </span>
  )
}
