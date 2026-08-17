import { useCallback, useEffect, useState } from 'react'
import { Link, NavLink, Route, Routes, useNavigate } from 'react-router-dom'
import { api, ApiError, SESSION_EXPIRED_EVENT, type Me } from './api'
import { LoginPage } from './pages/LoginPage'
import { VoiceLibraryPage } from './pages/VoiceLibraryPage'
import { NarrationStudioPage } from './pages/NarrationStudioPage'
import { HistoryPage } from './pages/HistoryPage'

export default function App() {
  const [me, setMe] = useState<Me | null>(null)
  const [loading, setLoading] = useState(true)
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

  // A session that dies mid-use (expired token, server restart, cleared cookie)
  // is reported by the API client; drop the current user so the login screen
  // renders instead of leaving pages stuck on auth-error banners.
  useEffect(() => {
    const onSessionExpired = () => setMe(null)
    window.addEventListener(SESSION_EXPIRED_EVENT, onSessionExpired)
    return () => window.removeEventListener(SESSION_EXPIRED_EVENT, onSessionExpired)
  }, [])

  const logout = async () => {
    try {
      await fetch('/auth/logout', { method: 'POST', credentials: 'same-origin' })
    } catch {
      // Network failure: still clear the local session so the user is not stuck.
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
          Voice Studio
        </Link>
        <nav className="topnav">
          <NavLink to="/voices">Voices</NavLink>
          <NavLink to="/narration">New narration</NavLink>
          <NavLink to="/history">History</NavLink>
        </nav>
        <div className="account">
          <span className="account-email" title={me.email}>
            {me.name || me.email}
          </span>
          <button className="btn btn-ghost" onClick={logout}>
            Sign out
          </button>
        </div>
      </header>
      <main className="content">
        <Routes>
          <Route path="/voices" element={<VoiceLibraryPage />} />
          <Route path="/narration" element={<NarrationStudioPage />} />
          <Route path="/history" element={<HistoryPage />} />
          <Route path="*" element={<VoiceLibraryPage />} />
        </Routes>
      </main>
    </div>
  )
}
