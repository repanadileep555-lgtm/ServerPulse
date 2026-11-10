import { useState, type FormEvent } from 'react'
import { ApiError } from '../api/client'
import { useAuth } from '../auth/useAuth'

type Mode = 'signin' | 'register'

const USERNAME_PATTERN = /^[A-Za-z0-9_.-]{3,64}$/

export function AuthPanel() {
  const { signIn, register } = useAuth()
  const [mode, setMode] = useState<Mode>('signin')
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)
  const isRegister = mode === 'register'

  function validate(): string | null {
    if (!username || !password) return 'Enter both a username and a password.'
    if (isRegister && !USERNAME_PATTERN.test(username)) {
      return 'Username must be 3–64 characters: letters, digits, "_", "." or "-".'
    }
    if (isRegister && password.length < 8) return 'Password must be at least 8 characters.'
    return null
  }

  function switchMode(next: Mode) {
    setMode(next)
    setError(null)
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const validation = validate()
    if (validation) {
      setError(validation)
      return
    }
    setSubmitting(true)
    setError(null)
    try {
      if (isRegister) {
        await register(username, password)
      } else {
        await signIn(username, password)
      }
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Something went wrong. Please try again.')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="auth-page">
      <div className="auth-card">
        <div className="brand brand-large">
          <img className="brand-mark" src="/logo.svg" alt="" aria-hidden="true" />
          ServerPulse
        </div>
        <p className="muted">Centralized server log collection and monitoring.</p>

        <div className="tabs" role="tablist">
          <button
            type="button"
            role="tab"
            aria-selected={!isRegister}
            className={`tab ${!isRegister ? 'tab-active' : ''}`}
            onClick={() => switchMode('signin')}
          >
            Sign in
          </button>
          <button
            type="button"
            role="tab"
            aria-selected={isRegister}
            className={`tab ${isRegister ? 'tab-active' : ''}`}
            onClick={() => switchMode('register')}
          >
            Create account
          </button>
        </div>

        <form className="form" onSubmit={handleSubmit} noValidate>
          <label className="field">
            <span>Username</span>
            <input
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              autoComplete="username"
              autoFocus
            />
          </label>
          <label className="field">
            <span>Password</span>
            <input
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              autoComplete={isRegister ? 'new-password' : 'current-password'}
            />
          </label>

          {error && (
            <p className="error" role="alert">
              {error}
            </p>
          )}

          <button type="submit" className="btn btn-primary btn-block" disabled={submitting}>
            {submitting && <span className="spinner" aria-hidden="true" />}
            {submitting ? 'Please wait…' : isRegister ? 'Create account' : 'Sign in'}
          </button>
        </form>
      </div>
    </div>
  )
}
