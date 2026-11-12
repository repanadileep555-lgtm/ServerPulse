import type { ReactNode } from 'react'
import { useAuth } from '../auth/useAuth'
import { NavIcon } from './icons'
import { NotificationBell } from './NotificationBell'
import { UserAvatar } from './UserAvatar'
interface TopBarProps {
  isAdmin: boolean
  controls?: ReactNode
}

export function TopBar({ isAdmin, controls }: TopBarProps) {
  const { user, signOut } = useAuth()
  const username = user?.username ?? ''
  const name = user?.display_name || username

  return (
    <header className="topbar">
      <div className="brand topbar-brand">
        <img className="brand-mark" src="/logo.svg" alt="" aria-hidden="true" />
        <span>ServerPulse</span>
      </div>

      {controls && <div className="topbar-controls">{controls}</div>}

      <div className="topbar-actions">
        <NotificationBell />
        <div className="topbar-account">
          <div className="account-chip" tabIndex={0} aria-label={`Signed in as ${name}`}>
            <UserAvatar avatar={user?.avatar} />
            <div className="account-popover" role="tooltip">
              <span className="account-name">{name}</span>
              <span className="muted small">@{username}</span>
              <span className={`role-pill ${isAdmin ? 'role-pill-admin' : ''}`}>
                {isAdmin ? 'Administrator' : 'Member'}
              </span>
            </div>
          </div>
          <button type="button" className="signout-btn" onClick={signOut} aria-label="Sign out" title="Sign out">
            <NavIcon name="signout" />
            <span className="signout-label">Sign out</span>
          </button>
        </div>
      </div>
    </header>
  )
}
