import { useCallback, useEffect, useState } from 'react'
import { ApiError } from '../api/client'
import { getHealth } from '../api/endpoints'

export type HealthStatus = 'checking' | 'online' | 'degraded' | 'offline'

export interface HealthState {
  status: HealthStatus
  database: string | null
  checkedAt: Date | null
  error: string | null
  pending: boolean
}

export interface HealthMonitor extends HealthState {
  check: () => void
}

const INITIAL_STATE: HealthState = { status: 'checking', database: null, checkedAt: null, error: null, pending: false }

export function useHealth(intervalMs: number): HealthMonitor {
  const [state, setState] = useState<HealthState>(INITIAL_STATE)
  const [runId, setRunId] = useState(0)

  useEffect(() => {
    const controller = new AbortController()
    let timer: number | undefined

    const poll = async () => {
      let next: Omit<HealthState, 'pending'>
      try {
        const { database } = await getHealth(controller.signal)
        next = {
          status: database === 'ok' ? 'online' : 'degraded',
          database,
          checkedAt: new Date(),
          error: null,
        }
      } catch (err) {
        if (controller.signal.aborted) return
        next = {
          status: 'offline',
          database: null,
          checkedAt: new Date(),
          error: err instanceof ApiError ? err.message : 'Unexpected error',
        }
      }
      if (controller.signal.aborted) return
      setState({ ...next, pending: false })
      timer = window.setTimeout(poll, intervalMs)
    }

    void poll()
    return () => {
      controller.abort()
      window.clearTimeout(timer)
    }
  }, [intervalMs, runId])

  const check = useCallback(() => {
    setState((prev) => ({ ...prev, pending: true }))
    setRunId((id) => id + 1)
  }, [])

  return { ...state, check }
}
