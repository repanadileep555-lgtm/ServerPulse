import { useState } from 'react'
import { useAuth } from '../auth/useAuth'
import { useHealth } from '../hooks/useHealth'
import { API_BASE_URL } from '../api/client'
import { AccountsDirectory } from './AccountsDirectory'
import { AdminPanel } from './AdminPanel'
import { DashboardLayout } from './DashboardLayout'
import { HealthCard } from './HealthCard'
import { MachinesMonitoring } from './MachinesMonitoring'
import { ProfileCard } from './ProfileCard'
import { SessionCard } from './SessionCard'
import { healthStats } from './healthStats'
import type { NavGroup } from './navigation'

const HEALTH_POLL_INTERVAL_MS = 10_000

type AdminSection = 'overview' | 'system' | 'machines' | 'accounts' | 'session'

const NAV: NavGroup[] = [
  {
    label: 'Monitor',
    items: [
      { id: 'overview', label: 'Overview', icon: 'overview' },
      { id: 'system', label: 'System health', icon: 'system' },
      { id: 'machines', label: 'Machines', icon: 'machines' },
    ],
  },
  {
    label: 'Administration',
    items: [
      { id: 'accounts', label: 'Administrators', icon: 'accounts' },
      { id: 'session', label: 'My session', icon: 'session' },
    ],
  },
]

const SECTION_META: Record<AdminSection, { title: string; description: string }> = {
  overview: {
    title: 'Administrator console',
    description: 'A quick view of the API and the actions you need most.',
  },
  system: {
    title: 'System health',
    description: 'Live status of the ServerPulse API and its database, refreshed automatically.',
  },
  machines: {
    title: 'Machines',
    description: 'Resource and process health for your registered Windows and Linux hosts.',
  },
  accounts: {
    title: 'Administrators',
    description: 'Grant administrator privileges to trusted operator accounts.',
  },
  session: {
    title: 'My session',
    description: 'Your current administrator session.',
  },
}

export function AdminDashboard() {
  const { user } = useAuth()
  const health = useHealth(HEALTH_POLL_INTERVAL_MS)
  const [section, setSection] = useState<AdminSection>('overview')
  const [accountsVersion, setAccountsVersion] = useState(0)
  const meta = SECTION_META[section]
  const username = user?.username ?? ''

  return (
    <DashboardLayout
      isAdmin
      groups={NAV}
      activeId={section}
      onSelect={(id) => setSection(id as AdminSection)}
      health={health}
      title={meta.title}
      description={meta.description}
    >
      {section === 'overview' && (
        <section className="overview-page admin-overview">
          <div className="overview-hero overview-hero-admin">
            <div className="overview-hero-copy">
              <p className="overview-kicker">SERVERPULSE <span>/</span> OPERATIONS</p>
              <h2>Your infrastructure,<br />in clear view.</h2>
              <p>Monitor platform health and get to the tools you need without the noise.</p>
              <div className="overview-hero-actions">
                <button type="button" className="btn btn-primary" onClick={() => setSection('system')}>
                  System health <span aria-hidden="true">→</span>
                </button>
                <button type="button" className="btn btn-ghost" onClick={() => setSection('machines')}>
                  View machines
                </button>
              </div>
            </div>
            <div className="overview-service-card">
              <div className="overview-service-heading">
                <div>
                  <span className="overview-service-label">Platform status</span>
                  <strong>Core services</strong>
                </div>
                <span className={`overview-live-indicator overview-live-${health.status}`}>
                  <span aria-hidden="true" />{health.status === 'checking' ? 'Checking' : health.status === 'offline' ? 'Offline' : health.status === 'degraded' ? 'Degraded' : 'Operational'}
                </span>
              </div>
              <div className="overview-service-list">
                {healthStats(health).map((stat) => (
                  <div className="overview-service-row" key={stat.label}>
                    <span><span className={`overview-service-dot ${stat.tone ? `tone-${stat.tone}` : ''}`} aria-hidden="true" />{stat.label}</span>
                    <strong>{stat.value}</strong>
                  </div>
                ))}
              </div>
              <div className="overview-service-footer">
                <span>{health.checkedAt ? `Checked ${health.checkedAt.toLocaleTimeString()}` : 'Waiting for first health check'}</span>
                <button type="button" onClick={health.check} disabled={health.pending}>
                  {health.pending ? 'Checking…' : 'Refresh'}
                </button>
              </div>
              <div className="overview-signal-art" aria-hidden="true">
                <span /><span /><span /><span /><span /><span /><span /><span /><span /><span /><span /><span /><span /><span /><span /><span /><span />
              </div>
            </div>
          </div>

          <div className="overview-section-heading">
            <div>
              <p className="overview-kicker">QUICK ACCESS</p>
              <h2>Make your next move</h2>
            </div>
            <span>Administrator workspace</span>
          </div>
          <div className="overview-action-grid">
            <button type="button" className="overview-action-card" onClick={() => setSection('machines')}>
              <span className="overview-action-icon overview-action-icon-blue" aria-hidden="true">⌘</span>
              <span className="overview-action-text">
                <strong>Manage machines</strong>
                <span>Review host connectivity, resource use, and alerts.</span>
              </span>
              <span className="overview-action-arrow" aria-hidden="true">↗</span>
            </button>
            <button type="button" className="overview-action-card" onClick={() => setSection('accounts')}>
              <span className="overview-action-icon overview-action-icon-teal" aria-hidden="true">＋</span>
              <span className="overview-action-text">
                <strong>Administrator access</strong>
                <span>Manage trusted operators with elevated access.</span>
              </span>
              <span className="overview-action-arrow" aria-hidden="true">↗</span>
            </button>
          </div>
        </section>
      )}

      {section === 'system' && (
        <section className="grid">
          <HealthCard health={health} endpoint={API_BASE_URL} onCheck={health.check} />
          <article className="card">
            <div className="card-header">
              <h2>Monitoring</h2>
              <span className="badge badge-online">Polling</span>
            </div>
            <dl className="meta">
              <div>
                <dt>Endpoint</dt>
                <dd>{API_BASE_URL}/health</dd>
              </div>
              <div>
                <dt>Refresh interval</dt>
                <dd>{HEALTH_POLL_INTERVAL_MS / 1000} seconds</dd>
              </div>
            </dl>
          </article>
        </section>
      )}

      {section === 'machines' && <MachinesMonitoring />}

      {section === 'accounts' && (
        <div className="accounts-layout">
          <div className="content-narrow">
            <AdminPanel onCreated={() => setAccountsVersion((version) => version + 1)} />
          </div>
          <AccountsDirectory refreshKey={accountsVersion} />
        </div>
      )}

      {section === 'session' && (
        <section className="grid">
          <SessionCard username={username} privileges="Administrator" />
          <ProfileCard />
        </section>
      )}
    </DashboardLayout>
  )
}
