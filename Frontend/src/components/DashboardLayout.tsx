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
  controls,
  health,
  title,
  description,
  children,
}: DashboardLayoutProps) {
  const [collapsed, setCollapsed] = useState(false)
  const toggleLabel = collapsed ? 'Expand sidebar' : 'Collapse sidebar'

  return (
    <div className={`app-shell ${collapsed ? 'app-shell-collapsed' : ''}`}>
      <TopBar isAdmin={isAdmin} controls={controls} />

      <aside className="sidebar">
        <div className="sidebar-header">
          <span className="sidebar-title collapse-hide">Menu</span>
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
                    onClick={() => onSelect(item.id)}
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
