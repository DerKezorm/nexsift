/**
 * Live changes from the server (GET /api/stream, server-sent events). One connection for the whole page.
 *
 * The server only says *what* changed ("thread 12", "source 3"). Pages listen for the kinds they show and fetch
 * again; `useLiveVersion` gives them a number that counts up, a little delayed so a burst of messages causes one
 * reload, not fifty.
 */

import { useEffect, useState, useSyncExternalStore } from 'react'

export interface LiveMessage {
  type: 'thread' | 'threads' | 'source' | 'target' | 'strangers'
  id?: number
}

type Listener = (message: LiveMessage) => void

const listeners = new Set<Listener>()
let source: EventSource | null = null
let connected = false
const statusListeners = new Set<() => void>()

function setConnected(value: boolean) {
  if (connected === value) return
  connected = value
  statusListeners.forEach((listener) => listener())
}

function open() {
  if (source || typeof EventSource === 'undefined') return
  source = new EventSource('/api/stream')
  source.onopen = () => setConnected(true)
  source.onerror = () => setConnected(false)
  source.onmessage = (event) => {
    try {
      const message = JSON.parse(event.data) as LiveMessage
      listeners.forEach((listener) => listener(message))
    } catch {
      // A line that is not ours; ignore it.
    }
  }
}

export function closeLive() {
  source?.close()
  source = null
  setConnected(false)
}

export function subscribeLive(listener: Listener): () => void {
  open()
  listeners.add(listener)
  return () => listeners.delete(listener)
}

/** Whether the live connection stands. Shown in the header, so a frozen page is noticed. */
export function useLiveConnected(): boolean {
  return useSyncExternalStore(
    (listener) => {
      statusListeners.add(listener)
      open()
      return () => statusListeners.delete(listener)
    },
    () => connected,
  )
}

/** Counts up after changes of the given kinds, at most every `delay` milliseconds. */
export function useLiveVersion(kinds: LiveMessage['type'][], delay = 400): number {
  const [version, setVersion] = useState(0)
  const key = kinds.join(',')
  useEffect(() => {
    const wanted = new Set(key.split(','))
    let timer: number | undefined
    const unsubscribe = subscribeLive((message) => {
      if (!wanted.has(message.type)) return
      if (timer !== undefined) return
      timer = window.setTimeout(() => {
        timer = undefined
        setVersion((value) => value + 1)
      }, delay)
    })
    return () => {
      unsubscribe()
      if (timer !== undefined) window.clearTimeout(timer)
    }
  }, [key, delay])
  return version
}
