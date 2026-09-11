import { NavLink, Outlet, useNavigate } from 'react-router-dom'
import { useAuth } from '../auth/AuthContext'
import ThemeControls from '../theme/ThemeControls'

const navLinkClass = ({ isActive }: { isActive: boolean }) =>
  `whitespace-nowrap font-semibold no-underline ${isActive ? 'text-accent' : 'text-text'}`

export default function AdminShell() {
  const { logout, role } = useAuth()
  const navigate = useNavigate()

  async function handleLogout() {
    await logout()
    navigate('/login', { replace: true })
  }

  return (
    <div>
      <header className="flex flex-wrap items-center justify-between gap-3 border-b border-border px-4 py-3 sm:px-6">
        <nav className="flex flex-wrap gap-4">
          <NavLink to="/" end className={navLinkClass}>
            Revisions
          </NavLink>
          <NavLink to="/onboarding" className={navLinkClass}>
            Profile setup
          </NavLink>
          <NavLink to="/cv/import" className={navLinkClass}>
            Import CV
          </NavLink>
          <NavLink to="/roadmap" className={navLinkClass}>
            Roadmap
          </NavLink>
          <NavLink to="/postings" className={navLinkClass}>
            Postings
          </NavLink>
          <NavLink to="/postings/new" className={navLinkClass}>
            + New posting
          </NavLink>
          {role === 'admin' && (
            <NavLink to="/admin" className={navLinkClass}>
              Admin
            </NavLink>
          )}
        </nav>
        <div className="flex flex-wrap items-center gap-3">
          <ThemeControls />
          <button
            type="button"
            onClick={handleLogout}
            className="rounded border border-border px-3 py-1.5"
          >
            Log out
          </button>
        </div>
      </header>
      <main className="mx-auto max-w-content p-4 sm:p-6">
        <Outlet />
      </main>
    </div>
  )
}
