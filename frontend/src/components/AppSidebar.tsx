import { Link, useLocation, useSearchParams } from 'react-router-dom'
import { Layers, Mic2, Upload, Volume2, type LucideIcon } from 'lucide-react'

/**
 * Persistent workspace navigation (Phase 8a, simplified).
 *
 * Data-driven: each entry owns its route and an `isActive` predicate evaluated
 * against the current location + query string, so active states stay exact —
 * e.g. Voice Design is NOT active while the Voice Cloning modal query param is
 * present. Mode switching (Single Voice / Multi-Speech) lives inside the TTS
 * Studio page itself and is deliberately not mirrored in the sidebar.
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

export function AppSidebar({ open, onNavigate }: { open: boolean; onNavigate: () => void }) {
  const { pathname } = useLocation()
  const [params] = useSearchParams()

  return (
    <aside className={`app-sidebar ${open ? 'open' : ''}`} aria-label="Voice Studio workspace">
      <div className="sidebar-brand">
        <Mic2 size={17} strokeWidth={2.5} className="sidebar-brand-icon" />
        <span>Voice Studio</span>
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
            >
              <Icon size={15} strokeWidth={2} className="nav-icon" />
              <span className="nav-label">{entry.label}</span>
            </Link>
          )
        })}
      </nav>
    </aside>
  )
}
