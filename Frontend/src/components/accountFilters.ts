import type { UserResponse } from '../api/types'

export type RoleFilter = 'all' | 'admin' | 'member'
export type StatusFilter = 'all' | 'enabled' | 'disabled'
export type SortKey = 'name-asc' | 'name-desc' | 'newest' | 'oldest'

export interface AccountFilters {
  query: string
  role: RoleFilter
  status: StatusFilter
  sort: SortKey
}

export const DEFAULT_ACCOUNT_FILTERS: AccountFilters = {
  query: '',
  role: 'all',
  status: 'all',
  sort: 'name-asc',
}

export const ROLE_OPTIONS: { value: RoleFilter; label: string }[] = [
  { value: 'all', label: 'All roles' },
  { value: 'admin', label: 'Administrators' },
  { value: 'member', label: 'Members' },
]

export const STATUS_OPTIONS: { value: StatusFilter; label: string }[] = [
  { value: 'all', label: 'Any status' },
  { value: 'enabled', label: 'Enabled' },
  { value: 'disabled', label: 'Disabled' },
]

export const SORT_OPTIONS: { value: SortKey; label: string }[] = [
  { value: 'name-asc', label: 'Name (A–Z)' },
  { value: 'name-desc', label: 'Name (Z–A)' },
  { value: 'newest', label: 'Newest first' },
  { value: 'oldest', label: 'Oldest first' },
]

export function applyAccountFilters(users: UserResponse[], filters: AccountFilters): UserResponse[] {
  const needle = filters.query.trim().toLowerCase()
  const matching = users.filter(
    (user) =>
      (!needle || user.username.toLowerCase().includes(needle)) &&
      (filters.role === 'all' || user.is_admin === (filters.role === 'admin')) &&
      (filters.status === 'all' || user.enabled === (filters.status === 'enabled')),
  )

  // created_at values share one timestamp format from the API, so string order matches time order.
  return matching.sort((a, b) => {
    switch (filters.sort) {
      case 'name-desc':
        return b.username.localeCompare(a.username)
      case 'newest':
        return b.created_at.localeCompare(a.created_at)
      case 'oldest':
        return a.created_at.localeCompare(b.created_at)
      default:
        return a.username.localeCompare(b.username)
    }
  })
}
