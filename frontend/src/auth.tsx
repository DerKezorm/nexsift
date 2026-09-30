/**
 * Signed in or not. The session cookie cannot be read by this script, so it asks /api/setup and /api/auth/me at
 * startup: first start (no account yet), signed out, signed in, or the server cannot be reached.
 */

import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from 'react'

import { ApiError, api } from './api/client'
import type { Account } from './api/types'
import { closeLive } from './lib/live'

export type AuthState = 'loading' | 'setup' | 'signed_out' | 'signed_in' | 'unreachable'

interface Auth {
  state: AuthState
  account: Account | null
  refresh: () => Promise<void>
  setAccount: (account: Account) => void
  signOut: () => Promise<void>
}

const AuthContext = createContext<Auth | null>(null)

export function AuthProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<AuthState>('loading')
  const [account, setAccountState] = useState<Account | null>(null)

  const refresh = useCallback(async () => {
    try {
      const setup = await api.get<{ needs_setup: boolean }>('/api/setup')
      if (setup.needs_setup) {
        setAccountState(null)
        setState('setup')
        return
      }
    } catch {
      setState('unreachable')
      return
    }
    try {
      setAccountState(await api.get<Account>('/api/auth/me'))
      setState('signed_in')
    } catch (error) {
      if (error instanceof ApiError && error.status === 401) {
        setAccountState(null)
        setState('signed_out')
      } else {
        setState('unreachable')
      }
    }
  }, [])

  useEffect(() => {
    void refresh()
  }, [refresh])

  const setAccount = useCallback((next: Account) => {
    setAccountState(next)
    setState('signed_in')
  }, [])

  const signOut = useCallback(async () => {
    try {
      await api.post('/api/auth/logout')
    } finally {
      // The live stream belongs to the session; the next sign-in opens a fresh one.
      closeLive()
      setAccountState(null)
      setState('signed_out')
    }
  }, [])

  const value = useMemo(() => ({ state, account, refresh, setAccount, signOut }), [state, account, refresh, setAccount, signOut])
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

// eslint-disable-next-line react-refresh/only-export-components
export function useAuth(): Auth {
  const context = useContext(AuthContext)
  if (!context) throw new Error('useAuth outside AuthProvider')
  return context
}
