import { useCallback, useEffect, useRef, useState } from 'react'
import { Link, Route, Routes, useLocation, useNavigate } from 'react-router-dom'
import { Mic2, LogOut, Menu, User, ChevronDown, Star, MessageCircle } from 'lucide-react'
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
 * Phase 8a workspace shell: persistent sidebar + compact topbar + routed
 * content. Authentication state is owned by `App` and passed down; the shell
 * itself holds only presentation state (mobile drawer open/closed).
 */
function AppShell({ me, onClearSession }: { me: Me; onClearSession: () => void }) {
  const [sidebarOpen, setSidebarOpen] = useState(false)
  const [dropdownOpen, setDropdownOpen] = useState(false)
  const dropdownRef = useRef<HTMLDivElement>(null)
  const navigate = useNavigate()
  const location = useLocation()

  useEffect(() => {
    const handleClickOutside = (e: MouseEvent) => {
      if (dropdownRef.current && !dropdownRef.current.contains(e.target as Node)) {
        setDropdownOpen(false)
      }
    }
    if (dropdownOpen) {
      document.addEventListener('mousedown', handleClickOutside)
    }
    return () => {
      document.removeEventListener('mousedown', handleClickOutside)
    }
  }, [dropdownOpen])

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
    setDropdownOpen(false)
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
      <AppSidebar open={sidebarOpen} onNavigate={() => setSidebarOpen(false)} />
      {sidebarOpen && (
        <div className="sidebar-backdrop" onClick={() => setSidebarOpen(false)} aria-hidden="true" />
      )}
      <div className="shell-main">
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
          <Link to="/voices" className="brand topbar-brand">
            <Mic2 size={18} strokeWidth={2.5} />
            Voice Studio
          </Link>
          <div className="topnav">
            <div className="account-dropdown" ref={dropdownRef}>
              <button
                className="avatar-btn"
                onClick={() => setDropdownOpen(!dropdownOpen)}
                aria-label={me.name || me.email}
                aria-expanded={dropdownOpen}
              >
                <User size={20} strokeWidth={2} />
                <span className="avatar-chevron">
                  <ChevronDown size={10} strokeWidth={2.5} />
                </span>
              </button>
              {dropdownOpen && (
                <div className="profile-menu">
                  <div className="profile-menu-header">
                    <div className="profile-menu-avatar">
                      <User size={22} strokeWidth={2} />
                    </div>
                    <span className="profile-menu-name">{me.name || me.email}</span>
                  </div>
                  <div className="profile-menu-divider" />
                  <button className="profile-menu-item" disabled>
                    <span className="menu-item-icon"><Star size={15} strokeWidth={2} /></span>
                    <span className="menu-item-label">Rate Us</span>
                    <span className="menu-item-badge">Soon</span>
                  </button>
                  <button className="profile-menu-item" disabled>
                    <span className="menu-item-icon"><MessageCircle size={15} strokeWidth={2} /></span>
                    <span className="menu-item-label">Feedback / Report</span>
                    <span className="menu-item-badge">Soon</span>
                  </button>
                  <div className="profile-menu-divider" />
                  <button className="profile-menu-item danger" onClick={logout}>
                    <span className="menu-item-icon"><LogOut size={15} strokeWidth={2} /></span>
                    <span className="menu-item-label">Log out</span>
                  </button>
                </div>
              )}
            </div>
          </div>
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
