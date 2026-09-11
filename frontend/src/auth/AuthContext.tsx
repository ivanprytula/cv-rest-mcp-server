import {
  createContext,
  useCallback,
  useContext,
  useMemo,
  useState,
  type ReactNode,
} from 'react'
import {
  getMe,
  login as apiLogin,
  logout as apiLogout,
  refresh as apiRefresh,
} from '../api/auth'

// Access token lives in memory only (ADR-022): never localStorage/sessionStorage,
// so an XSS payload cannot read it. The refresh token never reaches JS at all —
// it travels in the __Host- httpOnly cookie the browser manages automatically.
interface AuthState {
  accessToken: string | null
  isAuthenticated: boolean
  role: string | null
  username: string | null
  login: (username: string, password: string) => Promise<void>
  logout: () => Promise<void>
  setAccessToken: (token: string | null) => void
}

const AuthContext = createContext<AuthState | null>(null)

let currentAccessToken: string | null = null

export function getAccessToken(): string | null {
  return currentAccessToken
}

export function setAccessTokenExternal(token: string | null): void {
  currentAccessToken = token
}

// Refresh rotates the token server-side on every call (ADR-022 replay
// detection): a second concurrent call would present the now-stale cookie
// and get treated as a replay, revoking the whole family and logging the
// user out. React 18 StrictMode double-invokes effects in dev (and two tabs,
// or a fast double-click, can race in prod too), so concurrent callers must
// share one in-flight request rather than each firing their own.
let inFlightRefresh: Promise<string | null> | null = null

export async function tryRefresh(): Promise<string | null> {
  if (inFlightRefresh) return inFlightRefresh

  inFlightRefresh = (async () => {
    try {
      const { access_token } = await apiRefresh()
      setAccessTokenExternal(access_token)
      return access_token
    } catch {
      setAccessTokenExternal(null)
      return null
    } finally {
      inFlightRefresh = null
    }
  })()

  return inFlightRefresh
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [accessToken, setAccessTokenState] = useState<string | null>(null)
  const [role, setRole] = useState<string | null>(null)
  const [username, setUsername] = useState<string | null>(null)

  // Single choke point for both explicit login and RequireAuth's silent
  // cookie-refresh on reload — role/username are fetched here so both paths
  // know them, not just the one that calls login() directly.
  const setAccessToken = useCallback((token: string | null) => {
    setAccessTokenExternal(token)
    setAccessTokenState(token)
    if (token) {
      getMe()
        .then((me) => {
          setRole(me.role)
          setUsername(me.subject)
        })
        .catch(() => {
          setRole(null)
          setUsername(null)
        })
    } else {
      setRole(null)
      setUsername(null)
    }
  }, [])

  const login = useCallback(
    async (username: string, password: string) => {
      const { access_token } = await apiLogin(username, password)
      setAccessToken(access_token)
    },
    [setAccessToken],
  )

  const logout = useCallback(async () => {
    await apiLogout().catch(() => undefined)
    setAccessToken(null)
  }, [setAccessToken])

  const value = useMemo(
    () => ({
      accessToken,
      isAuthenticated: accessToken !== null,
      role,
      username,
      login,
      logout,
      setAccessToken,
    }),
    [accessToken, role, username, login, logout, setAccessToken],
  )

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

export function useAuth(): AuthState {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error('useAuth must be used within AuthProvider')
  return ctx
}
