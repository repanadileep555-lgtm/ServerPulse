import type { HealthState, HealthStatus } from '../hooks/useHealth'

const STATUS_LABELS: Record<HealthStatus, string> = {
  checking: 'Checking…',
  online: 'Online',
  degraded: 'Database error',
  offline: 'Unreachable',
}

interface HealthCardProps {
  health: HealthState
  endpoint: string
  onCheck?: () => void
}

export function HealthCard({ health, endpoint, onCheck }: HealthCardProps) {
  return (
    <article className="card">
      <div className="card-header">
        <h2>API health</h2>
        <span className={`badge badge-${health.status}`}>{STATUS_LABELS[health.status]}</span>
      </div>
      <dl className="meta">
        <div>
          <dt>Endpoint</dt>
          <dd>{`${endpoint}/health`}</dd>
        </div>
        <div>
          <dt>Database</dt>
          <dd>{health.database ?? '—'}</dd>
        </div>
        <div>
          <dt>Last checked</dt>
          <dd>{health.checkedAt ? health.checkedAt.toLocaleTimeString() : '—'}</dd>
        </div>
      </dl>
      {health.error && <p className="error">{health.error}</p>}
      {onCheck && (
        <button type="button" className="btn btn-ghost btn-small" onClick={onCheck} disabled={health.pending}>
          {health.pending ? 'Checking…' : 'Check now'}
        </button>
      )}
    </article>
  )
}
