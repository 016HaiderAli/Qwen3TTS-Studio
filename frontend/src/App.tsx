import { useCallback, useEffect, useState } from 'react'
import { Route, Routes, useLocation, useNavigate } from 'react-router-dom'
import { Menu } from 'lucide-react'
import { api, ApiError, SESSION_EXPIRED_EVENT, type Me } from './api'
import { LoginPage } from './pages/LoginPage'
import { VoiceLibraryPage } from './pages/VoiceLibraryPage'
import { NarrationStudioPage } from './pages/NarrationStudioPage'
import { BuiltinVoicesPage } from './pages/BuiltinVoicesPage'
import { AppSidebar } from './components/AppSidebar'

export default function App() {
  const [me, setMe] = useState<Me | null>(null)
  const [loading, setLoading] = useState(true)

  const refreshMe = useCallback(async () => {
    setLoading(true)
    try {
      setMe(await api.me())
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) setMe(null)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    void refreshMe()
  }, [refreshMe])

  useEffect(() => {
    const onSessionExpired = () => setMe(null)
    window.addEventListener(SESSION_EXPIRED_EVENT, onSessionExpired)
    return () => window.removeEventListener(SESSION_EXPIRED_EVENT, onSessionExpired)
  }, [])

  if (loading) {
    return <div className="app-loading">Loading…</div>
  }

  if (!me) {
    // Unauthenticated: login screen replaces the ENTIRE shell — no sidebar,
    // no topbar, exactly as before Phase 8a.
    return <LoginPage />
  }

  return <AppShell me={me} onClearSession={() => setMe(null)} />
}

/**
 * Phase 8a workspace shell: persistent sidebar (brand, nav, status, account)
 * + routed content. Authentication state is owned by `App` and passed down;
 * the shell itself holds only presentation state (mobile drawer open/closed).
 * The legacy topbar survives ONLY as the compact mobile bar hosting the
 * navigation toggle — on desktop the sidebar owns the whole chrome.
 */
function AppShell({ me, onClearSession }: { me: Me; onClearSession: () => void }) {
  const [sidebarOpen, setSidebarOpen] = useState(false)
  const navigate = useNavigate()
  const location = useLocation()

  // Close the mobile drawer whenever the route changes.
  useEffect(() => {
    setSidebarOpen(false)
  }, [location.pathname, location.search])

  // Escape closes the mobile drawer.
  useEffect(() => {
    if (!sidebarOpen) return
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setSidebarOpen(false)
    }
    document.addEventListener('keydown', onKeyDown)
    return () => document.removeEventListener('keydown', onKeyDown)
  }, [sidebarOpen])

  const logout = async () => {
    try {
      await fetch('/auth/logout', { method: 'POST', credentials: 'same-origin' })
    } catch {
      // Network failure: still clear the local session.
    } finally {
      onClearSession()
      navigate('/')
    }
  }

  return (
    <div className="app app-shell">
      <AppSidebar
        open={sidebarOpen}
        me={me}
        onNavigate={() => setSidebarOpen(false)}
        onLogout={logout}
      />
      {sidebarOpen && (
        <div className="sidebar-backdrop" onClick={() => setSidebarOpen(false)} aria-hidden="true" />
      )}
      <div className="shell-main">
        {/* Mobile-only bar: hosts the navigation toggle. Hidden on desktop. */}
        <header className="topbar">
          <button
            type="button"
            className="sidebar-toggle"
            onClick={() => setSidebarOpen((prev) => !prev)}
            aria-label="Toggle navigation"
            aria-expanded={sidebarOpen}
          >
            <Menu size={18} strokeWidth={2.2} />
          </button>
        </header>
        <main className="content">
          <Routes>
            <Route path="/voices" element={<VoiceLibraryPage />} />
            <Route path="/tts-studio" element={<BuiltinVoicesPage />} />
            <Route path="/narration" element={<NarrationStudioPage />} />
            <Route path="*" element={<VoiceLibraryPage />} />
          </Routes>
        </main>
      </div>
    </div>
  )
}
