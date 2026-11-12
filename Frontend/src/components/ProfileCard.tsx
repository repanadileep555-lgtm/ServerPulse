import { useRef, useState, type ChangeEvent, type FormEvent } from 'react'
import { ApiError } from '../api/client'
import { changePassword, updateProfile } from '../api/endpoints'
import { useAuth } from '../auth/useAuth'
import { UserAvatar } from './UserAvatar'

const AVATAR_SIZE_PX = 128
const AVATAR_QUALITY = 0.85
const MIN_PASSWORD_LENGTH = 8

async function fileToAvatarDataUrl(file: File): Promise<string> {
  const url = URL.createObjectURL(file)
  try {
    const image = new Image()
    image.src = url
    await image.decode()
    const canvas = document.createElement('canvas')
    canvas.width = AVATAR_SIZE_PX
    canvas.height = AVATAR_SIZE_PX
    const context = canvas.getContext('2d')
    if (!context) throw new Error('Image processing is not available in this browser.')
    const side = Math.min(image.naturalWidth, image.naturalHeight)
    const sx = (image.naturalWidth - side) / 2
    const sy = (image.naturalHeight - side) / 2
    context.drawImage(image, sx, sy, side, side, 0, 0, AVATAR_SIZE_PX, AVATAR_SIZE_PX)
    return canvas.toDataURL('image/jpeg', AVATAR_QUALITY)
  } finally {
    URL.revokeObjectURL(url)
  }
}

function errorMessage(error: unknown, fallback: string): string {
  return error instanceof ApiError ? error.message : fallback
}

export function ProfileCard() {
  const { user, updateUser } = useAuth()
  const fileInput = useRef<HTMLInputElement>(null)
  const [displayName, setDisplayName] = useState(user?.display_name ?? '')
  const [profileBusy, setProfileBusy] = useState(false)
  const [profileMessage, setProfileMessage] = useState<{ tone: 'success' | 'error'; text: string } | null>(null)

  const [currentPassword, setCurrentPassword] = useState('')
  const [newPassword, setNewPassword] = useState('')
  const [confirmPassword, setConfirmPassword] = useState('')
  const [passwordBusy, setPasswordBusy] = useState(false)
  const [passwordMessage, setPasswordMessage] = useState<{ tone: 'success' | 'error'; text: string } | null>(null)

  if (!user) return null

  async function saveProfile(patch: Parameters<typeof updateProfile>[0], successText: string) {
    setProfileBusy(true)
    setProfileMessage(null)
    try {
      updateUser(await updateProfile(patch))
      setProfileMessage({ tone: 'success', text: successText })
    } catch (error) {
      setProfileMessage({ tone: 'error', text: errorMessage(error, 'Could not update your profile.') })
    } finally {
      setProfileBusy(false)
    }
  }

  function handleNameSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const trimmed = displayName.trim()
    void saveProfile({ display_name: trimmed || null }, 'Display name saved.')
  }

  async function handleAvatarChange(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0]
    event.target.value = ''
    if (!file) return
    setProfileMessage(null)
    try {
      const avatar = await fileToAvatarDataUrl(file)
      await saveProfile({ avatar }, 'Profile picture updated.')
    } catch {
      setProfileMessage({ tone: 'error', text: 'That file could not be read as an image.' })
    }
  }

  async function handlePasswordSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setPasswordMessage(null)
    if (newPassword.length < MIN_PASSWORD_LENGTH) {
      setPasswordMessage({ tone: 'error', text: `New password must be at least ${MIN_PASSWORD_LENGTH} characters.` })
      return
    }
    if (newPassword !== confirmPassword) {
      setPasswordMessage({ tone: 'error', text: 'The new passwords do not match.' })
      return
    }
    setPasswordBusy(true)
    try {
      await changePassword({ current_password: currentPassword, new_password: newPassword })
      setCurrentPassword('')
      setNewPassword('')
      setConfirmPassword('')
      setPasswordMessage({ tone: 'success', text: 'Password changed.' })
    } catch (error) {
      setPasswordMessage({ tone: 'error', text: errorMessage(error, 'Could not change your password.') })
    } finally {
      setPasswordBusy(false)
    }
  }

  return (
    <article className="card profile-card">
      <div className="card-header">
        <h2>Edit profile</h2>
      </div>

      <div className="profile-avatar-row">
        <UserAvatar avatar={user.avatar} size="lg" />
        <div className="profile-avatar-actions">
          <input
            ref={fileInput}
            type="file"
            accept="image/png,image/jpeg,image/webp"
            className="visually-hidden"
            aria-label="Choose profile picture"
            onChange={handleAvatarChange}
            disabled={profileBusy}
          />
          <button type="button" className="btn btn-ghost btn-small" onClick={() => fileInput.current?.click()} disabled={profileBusy}>
            Upload picture
          </button>
          {user.avatar && (
            <button
              type="button"
              className="btn btn-ghost btn-small"
              onClick={() => void saveProfile({ avatar: null }, 'Profile picture removed.')}
              disabled={profileBusy}
            >
              Remove
            </button>
          )}
          <small className="field-hint">PNG, JPEG, or WebP. Cropped to a square.</small>
        </div>
      </div>

      <form className="form" onSubmit={handleNameSubmit}>
        <label className="field">
          <span>Display name</span>
          <input
            value={displayName}
            maxLength={64}
            placeholder={user.username}
            onChange={(event) => setDisplayName(event.target.value)}
          />
        </label>
        <div className="profile-actions">
          <button type="submit" className="btn btn-primary" disabled={profileBusy}>
            Save name
          </button>
        </div>
      </form>
      {profileMessage && (
        <p className={profileMessage.tone === 'error' ? 'error' : 'muted small'} role="status">
          {profileMessage.text}
        </p>
      )}

      <form className="form profile-password" onSubmit={handlePasswordSubmit}>
        <h3>Change password</h3>
        <label className="field">
          <span>Current password</span>
          <input type="password" autoComplete="current-password" value={currentPassword} onChange={(e) => setCurrentPassword(e.target.value)} required />
        </label>
        <label className="field">
          <span>New password</span>
          <input type="password" autoComplete="new-password" value={newPassword} onChange={(e) => setNewPassword(e.target.value)} required />
          <small className="field-hint">At least {MIN_PASSWORD_LENGTH} characters.</small>
        </label>
        <label className="field">
          <span>Confirm new password</span>
          <input type="password" autoComplete="new-password" value={confirmPassword} onChange={(e) => setConfirmPassword(e.target.value)} required />
        </label>
        <div className="profile-actions">
          <button type="submit" className="btn btn-primary" disabled={passwordBusy}>
            {passwordBusy ? 'Updating…' : 'Update password'}
          </button>
        </div>
      </form>
      {passwordMessage && (
        <p className={passwordMessage.tone === 'error' ? 'error' : 'muted small'} role="status">
          {passwordMessage.text}
        </p>
      )}
    </article>
  )
}
