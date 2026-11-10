import { useEffect, useMemo, useState } from 'react'
import { ApiError } from '../api/client'
import { listUsers } from '../api/endpoints'
import type { UserResponse } from '../api/types'
import { applyAccountFilters, type AccountFilters } from './accountFilters'

interface AccountsDirectoryProps {
  filters: AccountFilters
  refreshKey: number
}

interface DirectoryState {
  users: UserResponse[]
  loading: boolean
  error: string | null
}

export function AccountsDirectory({ filters, refreshKey }: AccountsDirectoryProps) {
  const [state, setState] = useState<DirectoryState>({ users: [], loading: true, error: null })

  useEffect(() => {
    const controller = new AbortController()
    listUsers(controller.signal)
      .then((users) => setState({ users, loading: false, error: null }))
      .catch((err: unknown) => {
        if (controller.signal.aborted) return
        setState((previous) => ({
          ...previous,
          loading: false,
          error: err instanceof ApiError ? err.message : 'Could not load accounts.',
        }))
      })
    return () => controller.abort()
  }, [refreshKey])

  const visible = useMemo(() => applyAccountFilters(state.users, filters), [state.users, filters])

  return (
    <article className="card">
      <div className="card-header">
        <div>
          <h2>Accounts</h2>
          <p className="muted small card-subtitle">
            {state.loading ? 'Loading…' : `Showing ${visible.length} of ${state.users.length}`}
          </p>
        </div>
      </div>

      {state.error && (
        <p className="error" role="alert">
          {state.error}
        </p>
      )}

      {!state.loading && !state.error && visible.length === 0 && (
        <p className="muted">No accounts match the current search and filters.</p>
      )}

      {visible.length > 0 && (
        <ul className="account-list" aria-label="Accounts">
          {visible.map((user) => (
            <li key={user.id} className="account-row">
              <span className="avatar avatar-sm" aria-hidden="true">
                {user.username.slice(0, 2).toUpperCase()}
              </span>
              <span className="account-name">{user.username}</span>
              <span className={`account-role ${user.is_admin ? 'account-role-admin' : ''}`}>
                {user.is_admin ? 'Administrator' : 'Member'}
              </span>
              <span className={`badge ${user.enabled ? 'badge-online' : 'badge-offline'}`}>
                {user.enabled ? 'Enabled' : 'Disabled'}
              </span>
              <span className="muted small">{new Date(user.created_at).toLocaleDateString()}</span>
            </li>
          ))}
        </ul>
      )}
    </article>
  )
}
