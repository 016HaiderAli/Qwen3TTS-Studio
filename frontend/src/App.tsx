import { useCallback, useEffect, useRef, useState } from 'react'
import { Link, NavLink, Route, Routes, useNavigate } from 'react-router-dom'
import { Mic2, Layers, Clock, LogOut, Wand2, User, ChevronDown, Star, MessageCircle } from 'lucide-react'
import { api, ApiError, SESSION_EXPIRED_EVENT, type Me } from './api'
import { LoginPage } from './pages/LoginPage'
import { VoiceLibraryPage } from './pages/VoiceLibraryPage'
import { NarrationStudioPage } from './pages/NarrationStudioPage'
import { HistoryPage } from './pages/HistoryPage'
import { BuiltinVoicesPage } from './pages/BuiltinVoicesPage'

export default function App() {
  const [me, setMe] = useState<Me | null>(null)
  const [loading, setLoading] = useState(true)
  const [dropdownOpen, setDropdownOpen] = useState(false)
  const dropdownRef = useRef<HTMLDivElement>(null)
  const navigate = useNavigate()

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

  const logout = async () => {
    setDropdownOpen(false)
    try {
      await fetch('/auth/logout', { method: 'POST', credentials: 'same-origin' })
    } catch {
      // Network failure: still clear the local session.
    } finally {
      setMe(null)
      navigate('/')
    }
  }

  if (loading) {
    return <div className="app-loading">Loading…</div>
  }

  if (!me) {
    return <LoginPage />
  }

  return (
    <div className="app">
      <header className="topbar">
        <Link to="/voices" className="brand">
          <Mic2 size={18} strokeWidth={2.5} />
          Voice Studio
        </Link>
        <nav className="topnav">
          <div className="nav-links">
            <NavLink to="/voices">
              <Layers size={15} strokeWidth={2} />
              Voice Design
            </NavLink>
            <NavLink to="/tts-studio">
              <Wand2 size={15} strokeWidth={2} />
              Generate Speech (TTS)
            </NavLink>
            <NavLink to="/history">
              <Clock size={15} strokeWidth={2} />
              History
            </NavLink>
          </div>
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
        </nav>
      </header>
      <main className="content">
        <Routes>
          <Route path="/voices" element={<VoiceLibraryPage />} />
          <Route path="/tts-studio" element={<BuiltinVoicesPage />} />
          <Route path="/narration" element={<NarrationStudioPage />} />
          <Route path="/history" element={<HistoryPage />} />
          <Route path="*" element={<VoiceLibraryPage />} />
        </Routes>
      </main>
    </div>
  )
}
