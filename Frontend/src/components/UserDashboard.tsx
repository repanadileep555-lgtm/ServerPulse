import { useEffect, useState } from 'react'
import { listHosts, type Host } from '../api/monitoring'
import { useAuth } from '../auth/useAuth'
import { DashboardLayout } from './DashboardLayout'
import { MachinesMonitoring } from './MachinesMonitoring'
import { ProfileCard } from './ProfileCard'
import { SessionCard } from './SessionCard'
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
  const attentionCount = hosts.items.filter((host) => host.connectivity === 'offline' || host.connectivity === 'never_seen').length
  const hasMachines = hosts.items.length > 0

  return (
    <section className="overview-page member-overview">
      <div className="overview-hero overview-hero-member">
        <div className="overview-hero-copy">
          <p className="overview-kicker">YOUR WORKSPACE <span>/</span> LIVE MONITORING</p>
          <h2>Every machine.<br />One clear picture.</h2>
          <p>Keep an eye on host status and resource health from a single place.</p>
          <div className="overview-hero-actions">
            <button type="button" className="btn btn-primary" onClick={() => onNavigate('machines')}>
              {hasMachines ? 'Open machines' : 'Add your first machine'} <span aria-hidden="true">→</span>
            </button>
            <button type="button" className="btn btn-ghost" onClick={() => onNavigate('account')}>
              Account settings
            </button>
          </div>
        </div>
        <div className="overview-member-art" aria-hidden="true">
          <div className="overview-orbit overview-orbit-outer" />
          <div className="overview-orbit overview-orbit-inner" />
          <div className="overview-orbit-core"><span /></div>
          <span className="overview-orbit-node overview-orbit-node-one" />
          <span className="overview-orbit-node overview-orbit-node-two" />
          <span className="overview-orbit-node overview-orbit-node-three" />
          <span className="overview-art-label">HOST NETWORK</span>
        </div>
      </div>

      <div className="overview-metrics" aria-label="Machine summary">
        <article className="overview-metric-card">
          <span className="overview-metric-icon overview-metric-icon-blue" aria-hidden="true">▦</span>
          <div><span>Registered machines</span><strong>{countsReady ? hosts.items.length : '—'}</strong></div>
          <span className="overview-metric-note">in your workspace</span>
        </article>
        <article className="overview-metric-card">
          <span className="overview-metric-icon overview-metric-icon-green" aria-hidden="true">↗</span>
          <div><span>Online</span><strong>{countsReady ? onlineCount : '—'}</strong></div>
          <span className="overview-metric-note">reporting normally</span>
        </article>
        <article className={`overview-metric-card${attentionCount > 0 ? ' overview-metric-attention' : ''}`}>
          <span className="overview-metric-icon overview-metric-icon-amber" aria-hidden="true">!</span>
          <div><span>Needs attention</span><strong>{countsReady ? attentionCount : '—'}</strong></div>
          <span className="overview-metric-note">offline or not connected</span>
        </article>
      </div>

      {hosts.error && <p className="machine-alert machine-alert-error" role="alert">{hosts.error}</p>}
      <section className="overview-host-section" aria-labelledby="overview-hosts-title">
        <div className="overview-section-heading">
          <div>
            <p className="overview-kicker">FLEET SNAPSHOT</p>
            <h2 id="overview-hosts-title">Your machines</h2>
          </div>
          <button type="button" className="overview-text-link" onClick={() => onNavigate('machines')}>
            View all machines <span aria-hidden="true">→</span>
          </button>
        </div>
        {hosts.loading ? (
          <div className="overview-state-card"><span className="spinner" aria-hidden="true" /> Loading your machines…</div>
        ) : hosts.error ? null : hasMachines ? (
          <div className="overview-host-grid">
            {hosts.items.slice(0, 4).map((host) => {
              const statusLabel = host.connectivity === 'never_seen'
                ? 'Not connected'
                : host.connectivity === 'disabled'
                  ? 'Disabled'
                  : host.connectivity === 'online' ? 'Online' : 'Offline'
              const cpu = host.cpu_percent === null ? null : Math.max(0, Math.min(100, host.cpu_percent))
              const memory = host.memory_percent === null ? null : Math.max(0, Math.min(100, host.memory_percent))
              return (
                <article className="overview-host-card" key={host.id}>
                  <div className="overview-host-heading">
                    <span className={`overview-host-symbol overview-host-symbol-${host.platform}`} aria-hidden="true">
                      {host.platform === 'windows' ? 'W' : 'L'}
                    </span>
                    <span className={`overview-host-status overview-host-status-${host.connectivity}`}>
                      <span aria-hidden="true" />{statusLabel}
                    </span>
                  </div>
                  <h3>{host.name}</h3>
                  <p className="overview-host-meta">{host.platform === 'windows' ? 'Windows' : 'Linux'} <span>·</span> {host.deployment_type}</p>
                  <div className="overview-host-meters">
                    <div className="overview-host-meter">
                      <div><span>CPU</span><strong>{cpu === null ? '—' : `${cpu.toFixed(1)}%`}</strong></div>
                      <span className="overview-host-track"><span style={{ width: `${cpu ?? 0}%` }} /></span>
                    </div>
                    <div className="overview-host-meter">
                      <div><span>Memory</span><strong>{memory === null ? '—' : `${memory.toFixed(1)}%`}</strong></div>
                      <span className="overview-host-track overview-host-track-memory"><span style={{ width: `${memory ?? 0}%` }} /></span>
                    </div>
                  </div>
                  {host.metrics_sampled_at && (
                    <p className="overview-host-updated">Updated {new Date(host.metrics_sampled_at).toLocaleTimeString()}</p>
                  )}
                </article>
              )
            })}
          </div>
        ) : (
          <div className="overview-empty-state">
            <span className="overview-empty-icon" aria-hidden="true">＋</span>
            <div>
              <p className="overview-kicker">GET STARTED</p>
              <h3>Bring your first machine online</h3>
              <p>Register a host, start its collector, and live CPU and memory readings will appear here.</p>
            </div>
            <button type="button" className="btn btn-primary" onClick={() => onNavigate('machines')}>
              Set up a machine <span aria-hidden="true">→</span>
            </button>
          </div>
        )}
      </section>
    </section>
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
