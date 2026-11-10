import { createContext } from 'react'
import type { UserResponse } from '../api/types'

export type AuthStatus = 'checking' | 'signed-out' | 'signed-in'

export interface AuthContextValue {
  status: AuthStatus
  user: UserResponse | null
  signIn: (username: string, password: string) => Promise<void>
  register: (username: string, password: string) => Promise<void>
  signOut: () => void
}

export const AuthContext = createContext<AuthContextValue | null>(null)
