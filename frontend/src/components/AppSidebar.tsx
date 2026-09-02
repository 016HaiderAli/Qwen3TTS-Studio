import { useEffect, useRef, useState } from 'react'
import { Link, useLocation, useSearchParams } from 'react-router-dom'
import {
  Layers,
  LogOut,
  Mic2,
  PanelLeftClose,
  PanelLeftOpen,
  Upload,
  User,
  Volume2,
  type LucideIcon,
} from 'lucide-react'
import type { Me } from '../api'

/**
 * Persistent workspace navigation (Phase 8a, collapsible).
 *
 * Data-driven entries with per-item `isActive` predicates (location + query),
 * a brand header carrying the collapse toggle, and the account popover
 * anchored above the bottom user pill.
 *
 * Layout is strictly 100vh with no internal scrollbars: brand / nav / footer
 * share the fixed height via space-between, so opening the account popover
 * can never push content off-screen.
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
  const [accountOpen, setAccountOpen] = useState(false)
  const accountRef = useRef<HTMLDivElement>(null)

  // Persist the preference; storage failures are non-fatal.
  useEffect(() => {
    try {
      window.localStorage.setItem(COLLAPSE_KEY, collapsed ? '1' : '0')
    } catch {
      // private mode / quota — ignore
    }
  }, [collapsed])

  // Close the account popover on outside click or Escape.
  useEffect(() => {
    if (!accountOpen) return
    const onPointerDown = (e: MouseEvent | TouchEvent) => {
      if (accountRef.current && !accountRef.current.contains(e.target as Node)) {
        setAccountOpen(false)
      }
    }
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setAccountOpen(false)
    }
    document.addEventListener('mousedown', onPointerDown)
    document.addEventListener('touchstart', onPointerDown)
    document.addEventListener('keydown', onKeyDown)
    return () => {
      document.removeEventListener('mousedown', onPointerDown)
      document.removeEventListener('touchstart', onPointerDown)
      document.removeEventListener('keydown', onKeyDown)
    }
  }, [accountOpen])

  const toggleCollapsed = () => setCollapsed((prev) => !prev)

  return (
    <aside
      className={`app-sidebar ${open ? 'open' : ''} ${collapsed ? 'collapsed' : ''}`}
      aria-label="Voice Studio workspace"
    >
      <div className="sidebar-brand">
        <span className="sidebar-brand-id">
          <Mic2 size={17} strokeWidth={2.5} className="sidebar-brand-icon" />
          {!collapsed && <span className="sidebar-brand-text">Voice Studio</span>}
        </span>
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

        {/* Account pill + floating popover (renders above the pill, never in
            the sidebar flow — the sidebar cannot scroll because of it). */}
        <div className="sidebar-divider" role="separator" />

        <div className="account-pill-wrap" ref={accountRef}>
          <button
            type="button"
            className="sidebar-account"
            onClick={() => setAccountOpen((prev) => !prev)}
            aria-label={`Account: ${me.name || me.email}`}
            aria-haspopup="dialog"
            aria-expanded={accountOpen}
            title={collapsed ? me.name || me.email : undefined}
          >
            <span className="sidebar-account-avatar">
              <User size={15} strokeWidth={2.2} />
            </span>
            {!collapsed && (
              <span className="sidebar-account-text">
                <span className="sidebar-account-name">{me.name || me.email}</span>
                <span className="sidebar-account-hint">Account</span>
              </span>
            )}
          </button>

          {accountOpen && (
            <div className="account-popover" role="dialog" aria-label="Account">
              <div className="account-popover-header">
                <span className="account-popover-avatar" aria-hidden="true">
                  <User size={18} strokeWidth={2.2} />
                </span>
                <div className="account-popover-id">
                  <span className="account-popover-name">{me.name || me.email}</span>
                  {me.name && me.email && (
                    <span className="account-popover-email">{me.email}</span>
                  )}
                </div>
              </div>
              <div className="account-popover-divider" role="separator" />
              <button
                type="button"
                className="account-popover-item logout"
                onClick={() => void onLogout()}
              >
                <LogOut size={15} strokeWidth={2} className="account-popover-item-icon" />
                <span>Log out</span>
              </button>
            </div>
          )}
        </div>
      </div>
    </aside>
  )
}
