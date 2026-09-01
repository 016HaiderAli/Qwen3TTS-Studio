import { useEffect, useRef, useState } from 'react'
import { Link, useLocation, useSearchParams } from 'react-router-dom'
import {
  Layers,
  Mic2,
  Upload,
  Volume2,
  PanelLeftClose,
  PanelLeftOpen,
  LogOut,
  Star,
  MessageCircle,
  User,
  ChevronDown,
  type LucideIcon,
} from 'lucide-react'
import type { Me } from '../api'

/**
 * Persistent workspace navigation (Phase 8a, ElevenLabs/HeyGen-style density).
 *
 * Data-driven entries with per-item `isActive` predicates (location + query),
 * a brand header carrying the collapse toggle, a divider, a worker status
 * card, and the user account block anchored at the bottom — no empty floating
 * topbar space. Collapse state persists via localStorage.
 */
interface NavEntry {
  key: string
  label: string
  to: string
  icon: LucideIcon
  isActive: (pathname: string, params: URLSearchParams) => boolean
}

const NAV_ENTRIES: NavEntry[] = [
  {
    key: 'voice-design',
    label: 'Voice Design',
    to: '/voices',
    icon: Layers,
    // Not active while the cloning modal deep link is open.
    isActive: (pathname, params) =>
      pathname === '/voices' && params.get('action') !== 'clone',
  },
  {
    key: 'voice-cloning',
    label: 'Voice Cloning',
    to: '/voices?action=clone',
    icon: Upload,
    isActive: (pathname, params) =>
      pathname === '/voices' && params.get('action') === 'clone',
  },
  {
    key: 'tts-studio',
    label: 'TTS Studio',
    to: '/tts-studio',
    icon: Volume2,
    isActive: (pathname) => pathname === '/tts-studio' || pathname === '/narration',
  },
]

const COLLAPSE_KEY = 'voice-studio.sidebar.collapsed'

function readCollapsedPreference(): boolean {
  try {
    return window.localStorage.getItem(COLLAPSE_KEY) === '1'
  } catch {
    return false
  }
}

export function AppSidebar({
  open,
  me,
  onNavigate,
  onLogout,
}: {
  open: boolean
  me: Me
  onNavigate: () => void
  onLogout: () => Promise<void>
}) {
  const { pathname } = useLocation()
  const [params] = useSearchParams()
  const [collapsed, setCollapsed] = useState<boolean>(() => readCollapsedPreference())
  const [dropdownOpen, setDropdownOpen] = useState(false)
  const dropdownRef = useRef<HTMLDivElement>(null)

  // Persist the preference; storage failures are non-fatal.
  useEffect(() => {
    try {
      window.localStorage.setItem(COLLAPSE_KEY, collapsed ? '1' : '0')
    } catch {
      // private mode / quota — ignore
    }
  }, [collapsed])

  // Close the account dropdown on outside click.
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

  const toggleCollapsed = () => setCollapsed((prev) => !prev)

  return (
    <aside
      className={`app-sidebar ${open ? 'open' : ''} ${collapsed ? 'collapsed' : ''}`}
      aria-label="Voice Studio workspace"
    >
      <div className="sidebar-brand">
        <Mic2 size={17} strokeWidth={2.5} className="sidebar-brand-icon" />
        {!collapsed && <span className="sidebar-brand-text">Voice Studio</span>}
        <button
          type="button"
          className="sidebar-collapse-toggle"
          onClick={toggleCollapsed}
          aria-pressed={collapsed}
          aria-label={collapsed ? 'Expand sidebar' : 'Collapse sidebar'}
          title={collapsed ? 'Expand sidebar' : 'Collapse sidebar'}
        >
          {collapsed ? (
            <PanelLeftOpen size={14} strokeWidth={2} />
          ) : (
            <PanelLeftClose size={14} strokeWidth={2} />
          )}
        </button>
      </div>

      <nav className="sidebar-nav" aria-label="Workspace navigation">
        {NAV_ENTRIES.map((entry) => {
          const active = entry.isActive(pathname, params)
          const Icon = entry.icon
          return (
            <Link
              key={entry.key}
              to={entry.to}
              className={`nav-item ${active ? 'active' : ''}`}
              onClick={onNavigate}
              aria-current={active ? 'page' : undefined}
              data-nav={entry.key}
              title={entry.label}
            >
              <Icon size={15} strokeWidth={2} className="nav-icon" />
              {!collapsed && <span className="nav-label">{entry.label}</span>}
            </Link>
          )
        })}
      </nav>

      <div className="sidebar-footer">
        {!collapsed && (
          <div className="engine-status" role="status" title="GPU worker connection status">
            <span className="engine-dot" aria-hidden="true" />
            <div className="engine-status-text">
              <span className="engine-status-label">Engine</span>
              <span className="engine-status-value">Qwen3-TTS · Worker Ready</span>
            </div>
          </div>
        )}
        {collapsed && (
          <span
            className="engine-dot engine-dot-collapsed"
            role="status"
            aria-label="Worker Ready"
            title="Worker Ready"
          />
        )}

        <div className="sidebar-divider" role="separator" />

        {/* Account block anchored at the bottom of the sidebar. */}
        <div className="account-dropdown" ref={dropdownRef}>
          <button
            type="button"
            className="sidebar-account"
            onClick={() => setDropdownOpen((prev) => !prev)}
            aria-label={me.name || me.email}
            aria-expanded={dropdownOpen}
            title={collapsed ? me.name || me.email : undefined}
          >
            <span className="sidebar-account-avatar">
              <User size={16} strokeWidth={2.2} />
            </span>
            {!collapsed && (
              <span className="sidebar-account-text">
                <span className="sidebar-account-name">{me.name || me.email}</span>
                <span className="sidebar-account-hint">Account</span>
              </span>
            )}
            {!collapsed && (
              <ChevronDown
                size={13}
                strokeWidth={2.4}
                className={`sidebar-account-chevron ${dropdownOpen ? 'open' : ''}`}
              />
            )}
          </button>
          {dropdownOpen && (
            <div className="profile-menu sidebar-profile-menu" role="menu">
              {!collapsed && (
                <>
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
                    <span className="menu-item-icon">
                      <MessageCircle size={15} strokeWidth={2} />
                    </span>
                    <span className="menu-item-label">Feedback / Report</span>
                    <span className="menu-item-badge">Soon</span>
                  </button>
                  <div className="profile-menu-divider" />
                </>
              )}
              <button className="profile-menu-item danger" onClick={onLogout}>
                <span className="menu-item-icon"><LogOut size={15} strokeWidth={2} /></span>
                <span className="menu-item-label">Log out</span>
              </button>
            </div>
          )}
        </div>
      </div>
    </aside>
  )
}
