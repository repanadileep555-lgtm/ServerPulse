import type { HealthState } from '../hooks/useHealth'
import { HEALTH_LABEL } from './healthStats'
import { NavIcon } from './icons'

interface ApiStatusProps {
  health: HealthState
  onCheck: () => void
}

export function ApiStatus({ health, onCheck }: ApiStatusProps) {
  return (
    <div className="api-status">
      <div className="api-status-row">
        <span className={`status-dot status-${health.status}`} aria-hidden="true" />
        <span className="collapse-hide">API {HEALTH_LABEL[health.status]}</span>
      </div>
      <button
        type="button"
        className="btn btn-ghost btn-small btn-block collapse-hide"
        onClick={onCheck}
        disabled={health.pending}
      >
        <NavIcon name="refresh" />
        {health.pending ? 'Checking…' : 'Check now'}
      </button>
    </div>
  )
}
