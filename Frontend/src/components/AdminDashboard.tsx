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
import { StatStrip } from './StatStrip'
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
        <>
          <StatStrip items={[...healthStats(health), { label: 'Access', value: 'Administrator', tone: 'accent' }]} />
          <section className="quick-actions" aria-label="Quick actions">
            <button type="button" className="action-tile" onClick={() => setSection('system')}>
              <strong>Check system health</strong>
              <span>Endpoint status, database state, and polling details.</span>
            </button>
            <button type="button" className="action-tile" onClick={() => setSection('accounts')}>
              <strong>Create an administrator</strong>
              <span>Add a new operator account with full admin privileges.</span>
            </button>
          </section>
        </>
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
