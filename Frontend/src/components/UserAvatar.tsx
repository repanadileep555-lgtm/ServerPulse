interface UserAvatarProps {
  avatar?: string | null
  size?: 'sm' | 'lg'
  title?: string
}

const DEFAULT_AVATAR_SRC = '/default-avatar.svg'

export function UserAvatar({ avatar, size = 'sm', title }: UserAvatarProps) {
  const sizeClass = size === 'lg' ? 'avatar-lg' : 'avatar-sm'

  return (
    <img
      className={`avatar avatar-image ${sizeClass}`}
      src={avatar || DEFAULT_AVATAR_SRC}
      alt=""
      aria-hidden="true"
      title={title}
    />
  )
}
