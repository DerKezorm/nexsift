import { Route, Routes } from 'react-router-dom'

import { useAuth } from './auth'
import { AppShell } from './components/AppShell'
import { Spinner } from './components/ui'
import { InboxPage } from './pages/InboxPage'
import { RulesPage } from './pages/RulesPage'
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
        <Route path="*" element={<InboxPage />} />
      </Route>
    </Routes>
  )
}
