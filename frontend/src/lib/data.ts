/** Data many pages need, kept fresh by the live stream. */

import { useEffect } from 'react'

import { api } from '../api/client'
import type { Counts, Source, Target } from '../api/types'
import { useLiveVersion } from './live'
import { useLoad } from './useLoad'

export function useSources() {
  const version = useLiveVersion(['source'])
  const result = useLoad(() => api.get<Source[]>('/api/sources'), [])
  const { reload } = result
  useEffect(() => {
    if (version > 0) void reload()
  }, [version, reload])
  return result
}

export function useCounts() {
  const version = useLiveVersion(['thread', 'threads'])
  const result = useLoad(() => api.get<Counts>('/api/threads/counts'), [])
  const { reload } = result
  useEffect(() => {
    if (version > 0) void reload()
  }, [version, reload])
  return result
}

export function useTargets() {
  const version = useLiveVersion(['target'])
  const result = useLoad(() => api.get<Target[]>('/api/targets'), [])
  const { reload } = result
  useEffect(() => {
    if (version > 0) void reload()
  }, [version, reload])
  return result
}

export function isMuted(source: Source | undefined, now = Date.now()): boolean {
  return !!source?.muted_until && Date.parse(source.muted_until) > now
}
