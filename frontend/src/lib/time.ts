import { useEffect, useState } from 'react'

const UNITS: [Intl.RelativeTimeFormatUnit, number][] = [
  ['day', 86_400_000],
  ['hour', 3_600_000],
  ['minute', 60_000],
]

function stamp(at: number | string): number {
  return typeof at === 'number' ? at : Date.parse(at)
}

/** "5 min ago", "yesterday". Below a minute: "now". */
export function relative(at: number | string, language: string, now = Date.now()): string {
  const diff = stamp(at) - now
  const format = new Intl.RelativeTimeFormat(language, { numeric: 'auto', style: 'short' })
  for (const [unit, size] of UNITS) {
    if (Math.abs(diff) >= size) return format.format(Math.round(diff / size), unit)
  }
  return format.format(0, 'minute')
}

/** Clock time today, date and time otherwise. */
export function clock(at: number | string, language: string): string {
  const date = new Date(stamp(at))
  const sameDay = date.toDateString() === new Date().toDateString()
  return new Intl.DateTimeFormat(language, sameDay ? { hour: '2-digit', minute: '2-digit', second: '2-digit' } : { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' }).format(date)
}

export function duration(ms: number, language: string): string {
  const minutes = Math.max(1, Math.round(ms / 60_000))
  if (minutes < 60) return new Intl.NumberFormat(language, { style: 'unit', unit: 'minute', unitDisplay: 'short' }).format(minutes)
  if (minutes < 60 * 48) return new Intl.NumberFormat(language, { style: 'unit', unit: 'hour', unitDisplay: 'short', maximumFractionDigits: 1 }).format(minutes / 60)
  return new Intl.NumberFormat(language, { style: 'unit', unit: 'day', unitDisplay: 'short', maximumFractionDigits: 0 }).format(minutes / 1440)
}

/** Re-renders every half minute, so relative times do not freeze. */
export function useNow(interval = 30_000): number {
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => {
    const timer = window.setInterval(() => setNow(Date.now()), interval)
    return () => window.clearInterval(timer)
  }, [interval])
  return now
}
