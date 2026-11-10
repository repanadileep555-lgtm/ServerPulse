import type { ReactNode } from 'react'
import { useAuth } from '../auth/useAuth'
import { NavIcon } from './icons'
import type { NavGroup } from './navigation'

type NavItem = NavGroup['items'][number]

interface TopBarProps {
  isAdmin: boolean
  pages: NavItem[]
  query: string
  onQueryChange: (query: string) => void
  onSelectPage: (id: string) => void
  controls?: ReactNode
}

export function TopBar({ isAdmin, pages, query, onQueryChange, onSelectPage, controls }: TopBarProps) {
  const { user, signOut } = useAuth()
  const username = user?.username ?? ''
  const initials = username.slice(0, 2).toUpperCase()
  const needle = query.trim().toLowerCase()
  const pageMatches = needle ? pages.filter((page) => page.label.toLowerCase().includes(needle)) : []

  return (
    <header className="topbar">
      <div className="topbar-search">
        <input
          type="search"
          className="search-input"
          placeholder={isAdmin ? 'Search pages and accounts' : 'Search pages'}
          aria-label={isAdmin ? 'Search pages and accounts' : 'Search pages'}
          value={query}
          onChange={(event) => onQueryChange(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === 'Escape') onQueryChange('')
          }}
        />
        {pageMatches.length > 0 && (
          <ul className="search-results" aria-label="Matching pages">
            {pageMatches.map((page) => (
              <li key={page.id}>
                <button type="button" onClick={() => onSelectPage(page.id)}>
                  <NavIcon name={page.icon} />
                  {page.label}
                </button>
              </li>
            ))}
          </ul>
        )}
      </div>

      {controls && <div className="topbar-controls">{controls}</div>}

      <div className="topbar-account">
        <span className="avatar" aria-hidden="true">
          {initials}
        </span>
        <div className="account-meta">
          <span className="account-name">{username}</span>
          <span className={`account-role ${isAdmin ? 'account-role-admin' : ''}`}>
            {isAdmin ? 'Administrator' : 'Member'}
          </span>
        </div>
        <button type="button" className="btn btn-ghost" onClick={signOut} title="Sign out">
          <NavIcon name="signout" />
          Sign out
        </button>
      </div>
    </header>
  )
}
