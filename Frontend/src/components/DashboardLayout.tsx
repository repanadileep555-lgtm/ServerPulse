import { useState, type ReactNode } from 'react'
import type { HealthMonitor } from '../hooks/useHealth'
import { ApiStatus } from './ApiStatus'
import { NavIcon } from './icons'
import type { NavGroup } from './navigation'
import { TopBar } from './TopBar'

interface DashboardLayoutProps {
  isAdmin: boolean
  groups: NavGroup[]
  activeId: string
  onSelect: (id: string) => void
  query: string
  onQueryChange: (query: string) => void
  controls?: ReactNode
  health?: HealthMonitor
  title: string
  description: string
  children: ReactNode
}

export function DashboardLayout({
  isAdmin,
  groups,
  activeId,
  onSelect,
  query,
  onQueryChange,
  controls,
  health,
  title,
  description,
  children,
}: DashboardLayoutProps) {
  const [collapsed, setCollapsed] = useState(false)
  const toggleLabel = collapsed ? 'Expand sidebar' : 'Collapse sidebar'
  const pages = groups.flatMap((group) => group.items)

  function selectPage(id: string) {
    onQueryChange('')
    onSelect(id)
  }

  return (
    <div className={`app-shell ${collapsed ? 'app-shell-collapsed' : ''}`}>
      <aside className="sidebar">
        <div className="sidebar-brand">
          <img className="brand-mark" src="/logo.svg" alt="" aria-hidden="true" />
          <span className="collapse-hide">ServerPulse</span>
          <button
            type="button"
            className="sidebar-toggle"
            aria-label={toggleLabel}
            aria-expanded={!collapsed}
            title={toggleLabel}
            onClick={() => setCollapsed((value) => !value)}
          >
            <NavIcon name="collapse" />
          </button>
        </div>

        <nav className="sidebar-nav" aria-label={isAdmin ? 'Administrator navigation' : 'Member navigation'}>
          {groups.map((group) => (
            <div key={group.label} className="nav-group">
              <p className="nav-group-label collapse-hide">{group.label}</p>
              {group.items.map((item) => {
                const active = item.id === activeId
                return (
                  <button
                    key={item.id}
                    type="button"
                    className={`nav-item ${active ? 'nav-item-active' : ''}`}
                    aria-current={active ? 'page' : undefined}
                    aria-label={collapsed ? item.label : undefined}
                    title={collapsed ? item.label : undefined}
                    onClick={() => selectPage(item.id)}
                  >
                    <NavIcon name={item.icon} />
                    <span className="collapse-hide">{item.label}</span>
                  </button>
                )
              })}
            </div>
          ))}
        </nav>

        {isAdmin && health && (
          <div className="sidebar-footer">
            <ApiStatus health={health} onCheck={health.check} />
          </div>
        )}
      </aside>

      <div className="shell-main">
        <TopBar
          isAdmin={isAdmin}
          pages={pages}
          query={query}
          onQueryChange={onQueryChange}
          onSelectPage={selectPage}
          controls={controls}
        />
        <main className="workspace">
          <header className="page-header">
            <p className="eyebrow">{isAdmin ? 'Administration' : 'Workspace'}</p>
            <h1>{title}</h1>
            <p>{description}</p>
          </header>
          {children}
        </main>
      </div>
    </div>
  )
}
