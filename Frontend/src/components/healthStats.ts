import type { HealthStatus, HealthState } from '../hooks/useHealth'
import type { StatItem } from './StatStrip'

export const HEALTH_LABEL: Record<HealthStatus, string> = {
  checking: 'Checking',
  online: 'Online',
  degraded: 'Degraded',
  offline: 'Unreachable',
}

const HEALTH_TONE: Record<HealthStatus, StatItem['tone']> = {
  checking: undefined,
  online: 'success',
  degraded: 'warning',
  offline: 'danger',
}

export function healthStats(health: HealthState): StatItem[] {
  const databaseOk = health.database === 'ok'
  return [
    { label: 'API', value: HEALTH_LABEL[health.status], tone: HEALTH_TONE[health.status] },
    {
      label: 'Database',
      value: databaseOk ? 'Healthy' : health.database ? 'Error' : '—',
      tone: databaseOk ? 'success' : health.database ? 'danger' : undefined,
    },
  ]
}
