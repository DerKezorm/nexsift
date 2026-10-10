import { Navigate, Route, Routes, useLocation } from 'react-router-dom'

import { useAuth } from './auth'
import { AppShell } from './components/AppShell'
import { Spinner } from './components/ui'
import { InboxPage } from './pages/InboxPage'
import { RulesPage } from './pages/RulesPage'
import { AboutPage } from './pages/AboutPage'
import { SettingsPage } from './pages/SettingsPage'
import { SourcesPage } from './pages/SourcesPage'
import { LoginScreen, SetupScreen, UnreachableScreen } from './pages/auth/AuthScreens'

export default function App() {
  const { state, refresh } = useAuth()
  if (state === 'loading') {
    return (
      <div className="flex min-h-dvh items-center justify-center text-mist-600">
        <Spinner />
      </div>
    )
  }
  if (state === 'setup') return <SetupScreen />
  if (state === 'signed_out') return <LoginScreen />
  if (state === 'unreachable') return <UnreachableScreen onRetry={() => void refresh()} />
  return (
    <Routes>
      <Route element={<AppShell />}>
        <Route index element={<InboxPage />} />
        <Route path="sources" element={<SourcesPage />} />
        <Route path="rules" element={<RulesPage />} />
        <Route path="settings" element={<SettingsPage />} />
        <Route path="about" element={<AboutPage />} />
        <Route path="account" element={<ToAccount />} />
        <Route path="login" element={<Navigate to="/" replace />} />
        <Route path="*" element={<InboxPage />} />
      </Route>
    </Routes>
  )
}

/**
 * `/account`: where the shared sign-in module ends a linking (`?linked=<slug>` or `?error=<code>`). nexsift has no page
 * of its own for the one account; its part is Settings, Account.
 */
function ToAccount() {
  const { search } = useLocation()
  const params = new URLSearchParams(search)
  const kept = new URLSearchParams()
  for (const key of ['linked', 'error']) {
    const value = params.get(key)
    if (value) kept.set(key, value)
  }
  const rest = kept.toString()
  return <Navigate to={`/settings${rest ? `?${rest}` : ''}`} replace />
}
