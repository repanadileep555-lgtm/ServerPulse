import { useEffect, useState } from 'react'
import { listHosts, type Host } from '../api/monitoring'
import { useAuth } from '../auth/useAuth'
import { DashboardLayout } from './DashboardLayout'
import { MachinesMonitoring } from './MachinesMonitoring'
import { ProfileCard } from './ProfileCard'
import { SessionCard } from './SessionCard'
import { StatStrip } from './StatStrip'
import type { NavGroup } from './navigation'

type UserSection = 'overview' | 'machines' | 'account'

interface HostState {
  items: Host[]
  loading: boolean
  error: string | null
}

function UserOverview({ onNavigate }: { onNavigate: (section: UserSection) => void }) {
  const [hosts, setHosts] = useState<HostState>({ items: [], loading: true, error: null })

  useEffect(() => {
    const controller = new AbortController()
    listHosts(controller.signal)
      .then((items) => setHosts({ items, loading: false, error: null }))
      .catch(() => {
        if (controller.signal.aborted) return
        setHosts({ items: [], loading: false, error: 'Could not load your machines. Check the API connection and try again.' })
      })
    return () => controller.abort()
  }, [])

  const countsReady = !hosts.loading && !hosts.error
  const onlineCount = hosts.items.filter((host) => host.connectivity === 'online').length
  const hasMachines = hosts.items.length > 0

  return (
    <>
      <StatStrip
        items={[
          { label: 'Role', value: 'Member', tone: 'accent' },
          { label: 'Account', value: 'Active', tone: 'success' },
          { label: 'Machines', value: countsReady ? String(hosts.items.length) : '—' },
          { label: 'Online', value: countsReady ? String(onlineCount) : '—', tone: onlineCount > 0 ? 'success' : undefined },
        ]}
      />
      {hosts.error && <p className="machine-alert machine-alert-error" role="alert">{hosts.error}</p>}
      {hosts.loading ? (
        <p className="muted"><span className="spinner" aria-hidden="true" /> Loading your machines…</p>
      ) : hosts.error ? null : hasMachines ? (
        <section className="grid">
          <article className="card">
            <div className="card-header">
              <h2>Your machines</h2>
            </div>
            <dl className="meta">
              {hosts.items.map((host) => (
                <div key={host.id}>
                  <dt>{host.name}</dt>
                  <dd>
                    {host.platform === 'windows' ? 'Windows' : 'Linux'} · {host.deployment_type} · {host.connectivity === 'online' ? 'Online' : host.connectivity === 'disabled' ? 'Disabled' : 'Not online'}
                  </dd>
                </div>
              ))}
            </dl>
          </article>
        </section>
      ) : (
        <section className="grid">
          <article className="card">
            <div className="card-header">
              <h2>Get started</h2>
            </div>
            <p className="muted">No machines are registered yet. Add one to start monitoring its CPU, memory, and processes.</p>
            <ol className="setup-steps">
              <li>
                <strong>Register a machine.</strong> Open Machines, enter a name, platform, and deployment type, then copy the collector token shown once.
              </li>
              <li>
                <strong>Run the collector.</strong> Follow Collector setup help on the Machines page to install it and start it with that token.
              </li>
              <li>
                <strong>Confirm the first snapshot.</strong> The machine shows Online and its resource readings once the collector uploads data.
              </li>
            </ol>
          </article>
        </section>
      )}
      <section className="quick-actions" aria-label="Quick actions">
        <button type="button" className="action-tile" onClick={() => onNavigate('machines')}>
          <strong>{hasMachines ? 'Open machines' : 'Register a machine'}</strong>
          <span>{hasMachines ? 'Review resource and process health for your hosts.' : 'Add a Windows or Linux host to start monitoring.'}</span>
        </button>
        <button type="button" className="action-tile" onClick={() => onNavigate('account')}>
          <strong>Review your account</strong>
          <span>Profile and current session details.</span>
        </button>
      </section>
    </>
  )
}

const NAV: NavGroup[] = [
  {
    label: 'Workspace',
    items: [
      { id: 'overview', label: 'Overview', icon: 'overview' },
      { id: 'machines', label: 'Machines', icon: 'machines' },
      { id: 'account', label: 'Account', icon: 'account' },
    ],
  },
]

export function UserDashboard() {
  const { user } = useAuth()
  const [section, setSection] = useState<UserSection>('overview')

  const isOverview = section === 'overview'
  const title = isOverview ? `Welcome back, ${user?.username ?? ''}` : section === 'machines' ? 'Machines' : 'Account'
  const description = isOverview
    ? 'Your ServerPulse workspace. Server monitoring for your account appears here.'
    : section === 'machines'
      ? 'Resource and process health for your registered Windows and Linux hosts.'
      : 'Your profile and current session.'

  return (
    <DashboardLayout
      isAdmin={false}
      groups={NAV}
      activeId={section}
      onSelect={(id) => setSection(id as UserSection)}
      title={title}
      description={description}
    >
      {section === 'machines' ? (
        <MachinesMonitoring />
      ) : isOverview ? (
        <UserOverview onNavigate={setSection} />
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
                <dt>Display name</dt>
                <dd>{user?.display_name || '—'}</dd>
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
          <ProfileCard />
        </section>
      )}
    </DashboardLayout>
  )
}
