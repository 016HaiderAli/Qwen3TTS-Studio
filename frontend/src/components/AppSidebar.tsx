import { useEffect, useState } from 'react'
import { Link, useLocation, useSearchParams } from 'react-router-dom'
import { Layers, Mic2, Upload, Volume2, PanelLeftClose, PanelLeftOpen, type LucideIcon } from 'lucide-react'

/**
 * Persistent workspace navigation (Phase 8a, collapsible).
 *
 * Data-driven: each entry owns its route and an `isActive` predicate evaluated
 * against the current location + query string, so active states stay exact —
 * e.g. Voice Design is NOT active while the Voice Cloning modal query param is
 * present. Mode switching (Single Voice / Multi-Speech) lives inside the TTS
 * Studio page itself and is deliberately not mirrored in the sidebar.
 *
 * Collapse state persists via localStorage so the user's layout preference
 * survives reloads.
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

export function AppSidebar({ open, onNavigate }: { open: boolean; onNavigate: () => void }) {
  const { pathname } = useLocation()
  const [params] = useSearchParams()
  const [collapsed, setCollapsed] = useState<boolean>(() => readCollapsedPreference())

  // Persist the preference; storage failures are non-fatal.
  useEffect(() => {
    try {
      window.localStorage.setItem(COLLAPSE_KEY, collapsed ? '1' : '0')
    } catch {
      // private mode / quota — ignore
    }
  }, [collapsed])

  const toggleCollapsed = () => setCollapsed((prev) => !prev)

  return (
    <aside
      className={`app-sidebar ${open ? 'open' : ''} ${collapsed ? 'collapsed' : ''}`}
      aria-label="Voice Studio workspace"
    >
      <div className="sidebar-brand">
        <Mic2 size={17} strokeWidth={2.5} className="sidebar-brand-icon" />
        {!collapsed && <span className="sidebar-brand-text">Voice Studio</span>}
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
      <button
        type="button"
        className="sidebar-collapse-toggle"
        onClick={toggleCollapsed}
        aria-pressed={collapsed}
        aria-label={collapsed ? 'Expand sidebar' : 'Collapse sidebar'}
        title={collapsed ? 'Expand sidebar' : 'Collapse sidebar'}
      >
        {collapsed ? <PanelLeftOpen size={15} strokeWidth={2} /> : <PanelLeftClose size={15} strokeWidth={2} />}
      </button>
    </aside>
  )
}
