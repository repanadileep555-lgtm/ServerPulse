import { useAuth } from '../auth/useAuth'
import { AdminDashboard } from './AdminDashboard'
import { UserDashboard } from './UserDashboard'

export function Dashboard() {
  const { user } = useAuth()
  if (!user) return null
  return user.is_admin ? <AdminDashboard /> : <UserDashboard />
}
