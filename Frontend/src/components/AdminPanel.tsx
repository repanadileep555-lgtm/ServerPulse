import { useState, type FormEvent } from 'react'
import { ApiError } from '../api/client'
import { createAdmin } from '../api/endpoints'

export function AdminPanel({ onCreated }: { onCreated?: () => void }) {
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [message, setMessage] = useState<{ kind: 'success' | 'error'; text: string } | null>(null)

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setSubmitting(true)
    setMessage(null)
    try {
      const created = await createAdmin({ username, password })
      setMessage({ kind: 'success', text: `Administrator "${created.username}" created.` })
      setUsername('')
      setPassword('')
      onCreated?.()
    } catch (err) {
      setMessage({
        kind: 'error',
        text: err instanceof ApiError ? err.message : 'Could not create the administrator.',
      })
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <article className="card">
      <div className="card-header">
        <div>
          <h2>Create administrator</h2>
          <p className="muted small card-subtitle">Grants full admin privileges to a new account.</p>
        </div>
      </div>
      <form className="form" onSubmit={handleSubmit}>
        <label className="field">
          <span>Username</span>
          <input value={username} onChange={(e) => setUsername(e.target.value)} required />
        </label>
        <label className="field">
          <span>Password</span>
          <input
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            autoComplete="new-password"
            minLength={8}
            required
          />
          <small className="field-hint">At least 8 characters.</small>
        </label>
        <button type="submit" className="btn btn-primary btn-block" disabled={submitting}>
          {submitting ? 'Creating…' : 'Create administrator'}
        </button>
      </form>
      {message && (
        <p className={message.kind === 'success' ? 'success' : 'error'} role="status">
          {message.text}
        </p>
      )}
    </article>
  )
}
