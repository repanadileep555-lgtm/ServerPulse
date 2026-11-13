import { useCallback, useEffect, useRef, useState } from 'react'
import {
  listNotifications,
  markAllNotificationsRead,
  markNotificationRead,
  type HostNotification,
} from '../api/monitoring'
import { NavIcon } from './icons'

const NOTIFICATION_POLL_MS = 5000

function NotificationToast({ item, onDismiss }: { item: HostNotification; onDismiss: (id: number) => void }) {
  const isAlert = item.message.startsWith('Alert:') || item.message.startsWith('Resolved:')

  useEffect(() => {
    const timer = window.setTimeout(() => onDismiss(item.id), 7000)
    return () => window.clearTimeout(timer)
  }, [item.id, onDismiss])

  return (
    <article className={`notification-toast${isAlert ? ' notification-toast-alert' : ''}`} role="status">
      <span className="notification-toast-icon" aria-hidden="true">{isAlert ? '!' : 'i'}</span>
      <div className="notification-toast-content">
        <strong>{isAlert ? 'Machine alert' : 'New notification'}</strong>
        <span>{item.message}</span>
        <time dateTime={item.created_at}>{new Date(item.created_at).toLocaleTimeString()}</time>
      </div>
      <button type="button" className="notification-toast-dismiss" aria-label="Dismiss toast" onClick={() => onDismiss(item.id)}>
        <span aria-hidden="true">×</span>
      </button>
    </article>
  )
}

export function NotificationBell() {
  const [items, setItems] = useState<HostNotification[]>([])
  const [toasts, setToasts] = useState<HostNotification[]>([])
  const [open, setOpen] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [pending, setPending] = useState(false)
  const knownNotificationIds = useRef<Set<number> | null>(null)
  const rootRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    let active = true
    let loading = false
    const load = async () => {
      if (loading) return
      loading = true
      try {
        const next = await listNotifications()
        if (!active) return
        const knownIds = knownNotificationIds.current
        if (knownIds === null) {
          knownNotificationIds.current = new Set(next.map((item) => item.id))
        } else {
          const newlyUnread = next.filter((item) => item.read_at === null && !knownIds.has(item.id))
          for (const item of next) knownIds.add(item.id)
          if (newlyUnread.length > 0) {
            setToasts((current) => [...current, ...newlyUnread].slice(-4))
          }
        }
        setItems(next)
        setError(null)
      } catch {
        if (active) setError('Could not load notifications.')
      } finally {
        loading = false
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

  const dismissToast = useCallback((notificationId: number) => {
    setToasts((current) => current.filter((item) => item.id !== notificationId))
  }, [])

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

  const label = unreadCount > 0 ? `Alerts and notifications, ${unreadCount} unread` : 'Alerts and notifications'

  return (
    <>
      <div className="notification-toast-region" aria-label="New notifications" aria-live="polite" aria-relevant="additions">
        {toasts.map((item) => (
          <NotificationToast key={item.id} item={item} onDismiss={dismissToast} />
        ))}
      </div>
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
              <strong>Alerts &amp; notifications</strong>
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
    </>
  )
}
