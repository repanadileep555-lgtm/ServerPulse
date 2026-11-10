import { useState } from 'react'
import { useAuth } from '../auth/useAuth'
import { DashboardLayout } from './DashboardLayout'
import { SessionCard } from './SessionCard'
import { StatStrip } from './StatStrip'
import type { NavGroup } from './navigation'

type UserSection = 'overview' | 'account'

const NAV: NavGroup[] = [
  {
    label: 'Workspace',
    items: [
      { id: 'overview', label: 'Overview', icon: 'overview' },
      { id: 'account', label: 'Account', icon: 'account' },
    ],
  },
]

export function UserDashboard() {
  const { user } = useAuth()
  const [section, setSection] = useState<UserSection>('overview')
  const [query, setQuery] = useState('')

  const isOverview = section === 'overview'
  const title = isOverview ? `Welcome back, ${user?.username ?? ''}` : 'Account'
  const description = isOverview
    ? 'Your ServerPulse workspace. Server monitoring for your account appears here.'
    : 'Your profile and current session.'

  return (
    <DashboardLayout
      isAdmin={false}
      groups={NAV}
      activeId={section}
      onSelect={(id) => setSection(id as UserSection)}
      query={query}
      onQueryChange={setQuery}
      title={title}
      description={description}
    >
      {isOverview ? (
        <>
          <StatStrip
            items={[
              { label: 'Role', value: 'Member', tone: 'accent' },
              { label: 'Account', value: 'Active', tone: 'success' },
            ]}
          />
          <section className="grid">
            <article className="card">
              <div className="card-header">
                <h2>Getting started</h2>
              </div>
              <p className="muted">
                Open Account to review your profile and session. Administrators manage access and system settings.
              </p>
            </article>
          </section>
        </>
      ) : (
        <section className="grid">
          <article className="card">
            <div className="card-header">
              <h2>Profile</h2>
              <span className="badge badge-online">Active</span>
            </div>
            <dl className="meta">
              <div>
                <dt>Username</dt>
                <dd>{user?.username}</dd>
              </div>
              <div>
                <dt>Role</dt>
                <dd>Member</dd>
              </div>
              <div>
                <dt>Member since</dt>
                <dd>{user ? new Date(user.created_at).toLocaleDateString() : '—'}</dd>
              </div>
            </dl>
          </article>
          <SessionCard username={user?.username ?? ''} privileges="Member" />
        </section>
      )}
    </DashboardLayout>
  )
}
