import { useEffect, useState, type ReactNode } from 'react'
import { Navigate } from 'react-router-dom'
import { tryRefresh, useAuth } from './AuthContext'

// On a hard reload the in-memory access token is gone; try the refresh cookie
// once before bouncing to /login, so a reload doesn't force a re-login.
export default function RequireAuth({ children }: { children: ReactNode }) {
  const { isAuthenticated, setAccessToken } = useAuth()
  const [checked, setChecked] = useState(isAuthenticated)

  useEffect(() => {
    if (isAuthenticated) {
      setChecked(true)
      return
    }
    tryRefresh().then((token) => {
      setAccessToken(token)
      setChecked(true)
    })
  }, [isAuthenticated, setAccessToken])

  if (!checked) return null
  if (!isAuthenticated) return <Navigate to="/login" replace />
  return <>{children}</>
}
