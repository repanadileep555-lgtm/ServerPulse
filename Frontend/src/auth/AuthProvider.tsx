import { useCallback, useEffect, useMemo, useState, type ReactNode } from 'react'
import { refreshAccessToken, SESSION_EXPIRED_EVENT } from '../api/client'
import { createUser, getCurrentUser, login } from '../api/endpoints'
import { tokenStore } from '../api/tokenStore'
import type { UserResponse } from '../api/types'
import { AuthContext, type AuthContextValue, type AuthStatus } from './auth-context'

export function AuthProvider({ children }: { children: ReactNode }) {
  const [status, setStatus] = useState<AuthStatus>(() =>
    tokenStore.getRefreshToken() ? 'checking' : 'signed-out',
  )
  const [user, setUser] = useState<UserResponse | null>(null)

  useEffect(() => {
    if (status !== 'checking') return
    let active = true
    refreshAccessToken()
      .then(() => getCurrentUser())
      .then((profile) => {
        if (!active) return
        setUser(profile)
        setStatus('signed-in')
      })
      .catch(() => {
        if (!active) return
        tokenStore.clear()
        setUser(null)
        setStatus('signed-out')
      })
    return () => {
      active = false
    }
  }, [status])

  useEffect(() => {
    const handleExpired = () => {
      setUser(null)
      setStatus('signed-out')
    }
    window.addEventListener(SESSION_EXPIRED_EVENT, handleExpired)
    return () => window.removeEventListener(SESSION_EXPIRED_EVENT, handleExpired)
  }, [])

  const signIn = useCallback(async (name: string, password: string) => {
    const tokens = await login({ username: name, password })
    tokenStore.setAccessToken(tokens.access_token)
    tokenStore.setRefreshToken(tokens.refresh_token)
    try {
      setUser(await getCurrentUser())
    } catch (error) {
      tokenStore.clear()
      throw error
    }
    setStatus('signed-in')
  }, [])

  const register = useCallback(
    async (name: string, password: string) => {
      await createUser({ username: name, password })
      await signIn(name, password)
    },
    [signIn],
  )

  const signOut = useCallback(() => {
    tokenStore.clear()
    setUser(null)
    setStatus('signed-out')
  }, [])

  const value = useMemo<AuthContextValue>(
    () => ({ status, user, signIn, register, signOut }),
    [status, user, signIn, register, signOut],
  )

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}
