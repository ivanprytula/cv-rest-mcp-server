import {
  createContext,
  useCallback,
  useContext,
  useMemo,
  useState,
  type ReactNode,
} from 'react'
import { login as apiLogin, logout as apiLogout, refresh as apiRefresh } from '../api/auth'

// Access token lives in memory only (ADR-022): never localStorage/sessionStorage,
// so an XSS payload cannot read it. The refresh token never reaches JS at all —
// it travels in the __Host- httpOnly cookie the browser manages automatically.
interface AuthState {
  accessToken: string | null
  isAuthenticated: boolean
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

export async function tryRefresh(): Promise<string | null> {
  try {
    const { access_token } = await apiRefresh()
    setAccessTokenExternal(access_token)
    return access_token
  } catch {
    setAccessTokenExternal(null)
    return null
  }
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [accessToken, setAccessTokenState] = useState<string | null>(null)

  const setAccessToken = useCallback((token: string | null) => {
    setAccessTokenExternal(token)
    setAccessTokenState(token)
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
    () => ({ accessToken, isAuthenticated: accessToken !== null, login, logout, setAccessToken }),
    [accessToken, login, logout, setAccessToken],
  )

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

export function useAuth(): AuthState {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error('useAuth must be used within AuthProvider')
  return ctx
}
