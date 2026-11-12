import { useEffect, useRef, useState } from 'react'
import {
  listNotifications,
  markAllNotificationsRead,
  markNotificationRead,
  type HostNotification,
} from '../api/monitoring'
import { NavIcon } from './icons'

const NOTIFICATION_POLL_MS = 15000

export function NotificationBell() {
  const [items, setItems] = useState<HostNotification[]>([])
  const [open, setOpen] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [pending, setPending] = useState(false)
  const rootRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    let active = true
    const load = async () => {
      try {
        const next = await listNotifications()
        if (!active) return
        setItems(next)
        setError(null)
      } catch {
        if (active) setError('Could not load notifications.')
      }
    }
    void load()
    const timer = setInterval(load, NOTIFICATION_POLL_MS)
    return () => {
      active = false
      clearInterval(timer)
    }
  }, [])

  useEffect(() => {
    if (!open) return
    const onPointerDown = (event: MouseEvent) => {
      if (rootRef.current && !rootRef.current.contains(event.target as Node)) setOpen(false)
    }
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setOpen(false)
    }
    document.addEventListener('mousedown', onPointerDown)
    document.addEventListener('keydown', onKeyDown)
    return () => {
      document.removeEventListener('mousedown', onPointerDown)
      document.removeEventListener('keydown', onKeyDown)
    }
  }, [open])

  const unread = items.filter((item) => item.read_at === null)
  const unreadCount = unread.length
  const badge = unreadCount > 9 ? '9+' : String(unreadCount)

  async function markRead(notificationId: number) {
    setError(null)
    try {
      await markNotificationRead(notificationId)
      setItems((current) =>
        current.map((item) =>
          item.id === notificationId ? { ...item, read_at: new Date().toISOString() } : item,
        ),
      )
    } catch {
      setError('Could not mark the notification as read.')
    }
  }

  async function markAllRead() {
    setError(null)
    setPending(true)
    try {
      await markAllNotificationsRead()
      const readAt = new Date().toISOString()
      setItems((current) => current.map((item) => (item.read_at === null ? { ...item, read_at: readAt } : item)))
    } catch {
      setError('Could not mark all notifications as read.')
    } finally {
      setPending(false)
    }
  }

  const label = unreadCount > 0 ? `Notifications, ${unreadCount} unread` : 'Notifications'

  return (
    <div className="notification-bell" ref={rootRef}>
      <button
        type="button"
        className="notification-trigger"
        aria-label={label}
        aria-haspopup="true"
        aria-expanded={open}
        title={label}
        onClick={() => setOpen((value) => !value)}
      >
        <NavIcon name="bell" />
        {unreadCount > 0 && <span className="notification-badge" aria-hidden="true">{badge}</span>}
      </button>

      {open && (
        <div className="notification-popover" role="dialog" aria-label="Notifications">
          <div className="notification-popover-header">
            <strong>Notifications</strong>
            <button
              type="button"
              className="btn btn-ghost notification-action"
              onClick={() => void markAllRead()}
              disabled={pending || unreadCount === 0}
            >
              Mark all read
            </button>
          </div>
          {error && <p className="notification-error" role="alert">{error}</p>}
          {unreadCount === 0 ? (
            <p className="notification-empty">You're all caught up.</p>
          ) : (
            <ul className="notification-list">
              {unread.map((item) => (
                <li key={item.id} className="notification-item">
                  <div>
                    <span className="notification-message">{item.message}</span>
                    <time className="notification-time" dateTime={item.created_at}>
                      {new Date(item.created_at).toLocaleString()}
                    </time>
                  </div>
                  <button type="button" className="btn btn-ghost notification-action" onClick={() => void markRead(item.id)}>
                    Dismiss
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </div>
  )
}
