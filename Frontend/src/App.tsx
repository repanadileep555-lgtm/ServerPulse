import { AuthProvider } from './auth/AuthProvider'
import { useAuth } from './auth/useAuth'
import { AuthPanel } from './components/AuthPanel'
import { Dashboard } from './components/Dashboard'
import './App.css'

function Routes() {
  const { status } = useAuth()
  if (status === 'checking') {
    return (
      <div className="splash">
        <span className="spinner" aria-hidden="true" />
        Restoring your session…
      </div>
    )
  }
  return status === 'signed-in' ? <Dashboard /> : <AuthPanel />
}

export default function App() {
  return (
    <AuthProvider>
      <Routes />
    </AuthProvider>
  )
}
