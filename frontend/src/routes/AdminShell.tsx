import { NavLink, Outlet, useNavigate } from 'react-router-dom'
import { useAuth } from '../auth/AuthContext'

export default function AdminShell() {
  const { logout } = useAuth()
  const navigate = useNavigate()

  async function handleLogout() {
    await logout()
    navigate('/login', { replace: true })
  }

  return (
    <div className="admin-shell">
      <header className="admin-header">
        <nav>
          <NavLink to="/" end>
            Revisions
          </NavLink>
        </nav>
        <button type="button" onClick={handleLogout}>
          Log out
        </button>
      </header>
      <main>
        <Outlet />
      </main>
    </div>
  )
}
