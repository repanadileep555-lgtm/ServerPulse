import axios, { type InternalAxiosRequestConfig } from 'axios'
import { tokenStore } from './tokenStore'
import type { RefreshResponse } from './types'

export const API_BASE_URL: string = import.meta.env.VITE_API_BASE_URL ?? 'http://127.0.0.1:8000'
export const SESSION_EXPIRED_EVENT = 'serverpulse:session-expired'

const REQUEST_TIMEOUT_MS = 10_000
const AUTH_ENDPOINTS = ['/users/login', '/users/refresh']

export class ApiError extends Error {
  readonly status: number | undefined

  constructor(message: string, status?: number) {
    super(message)
    this.name = 'ApiError'
    this.status = status
  }
}

type RetriableConfig = InternalAxiosRequestConfig & { _retry?: boolean }

export const api = axios.create({ baseURL: API_BASE_URL, timeout: REQUEST_TIMEOUT_MS })

let refreshInFlight: Promise<string> | null = null

// Concurrent 401s share one refresh request so the backend sees a single /users/refresh call.
export function refreshAccessToken(): Promise<string> {
  if (!refreshInFlight) {
    refreshInFlight = (async () => {
      const refreshToken = tokenStore.getRefreshToken()
      if (!refreshToken) throw new Error('No refresh token available')
      const { data } = await axios.post<RefreshResponse>(
        `${API_BASE_URL}/users/refresh`,
        { refresh_token: refreshToken },
        { timeout: REQUEST_TIMEOUT_MS },
      )
      tokenStore.setAccessToken(data.access_token)
      return data.access_token
    })().finally(() => {
      refreshInFlight = null
    })
  }
  return refreshInFlight
}

function describeDetail(detail: unknown): string | undefined {
  if (typeof detail === 'string') return detail
  if (Array.isArray(detail)) {
    const messages = detail
      .map((item: unknown) =>
        typeof item === 'object' && item !== null && 'msg' in item && typeof item.msg === 'string'
          ? item.msg
          : null,
      )
      .filter((msg): msg is string => msg !== null)
    return messages.length > 0 ? messages.join('; ') : undefined
  }
  return undefined
}

export function toApiError(error: unknown): ApiError {
  if (!axios.isAxiosError(error)) {
    return new ApiError(error instanceof Error ? error.message : 'Unexpected error')
  }
  const status = error.response?.status
  const detail = (error.response?.data as { detail?: unknown } | undefined)?.detail
  const fallback = error.response
    ? `Request failed with status ${status}`
    : error.code === 'ECONNABORTED'
      ? 'The ServerPulse API did not respond in time'
      : 'Cannot reach the ServerPulse API'
  return new ApiError(describeDetail(detail) ?? fallback, status)
}

api.interceptors.request.use((config) => {
  const token = tokenStore.getAccessToken()
  if (token) config.headers.set('Authorization', `Bearer ${token}`)
  return config
})

api.interceptors.response.use(
  (response) => response,
  async (error: unknown) => {
    if (!axios.isAxiosError(error) || error.response?.status !== 401 || !error.config) {
      throw toApiError(error)
    }
    const config = error.config as RetriableConfig
    const isAuthEndpoint = AUTH_ENDPOINTS.includes(config.url ?? '')
    if (config._retry || isAuthEndpoint || !tokenStore.getRefreshToken()) {
      throw toApiError(error)
    }

    config._retry = true
    try {
      await refreshAccessToken()
    } catch {
      tokenStore.clear()
      window.dispatchEvent(new Event(SESSION_EXPIRED_EVENT))
      throw toApiError(error)
    }
    return api.request(config)
  },
)
