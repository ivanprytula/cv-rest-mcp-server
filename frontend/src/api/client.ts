import { getAccessToken, setAccessTokenExternal, tryRefresh } from '../auth/AuthContext'

const BASE_URL = import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000'

export class ApiError extends Error {
  status: number

  constructor(status: number, message: string) {
    super(message)
    this.status = status
  }
}

async function parseError(res: Response): Promise<string> {
  try {
    const body = await res.json()
    return typeof body?.detail === 'string' ? body.detail : res.statusText
  } catch {
    return res.statusText
  }
}

// Authenticated fetch: attaches the in-memory access token, and on a single
// 401 tries the refresh-cookie flow once before giving up. Never retries a
// second time — a refresh that also 401s means the session is truly over.
export async function apiFetch(path: string, init: RequestInit = {}, isRetry = false): Promise<Response> {
  const token = getAccessToken()
  const headers = new Headers(init.headers)
  if (token) headers.set('Authorization', `Bearer ${token}`)

  const res = await fetch(`${BASE_URL}${path}`, { ...init, headers })

  if (res.status === 401 && !isRetry) {
    const newToken = await tryRefresh()
    if (newToken) return apiFetch(path, init, true)
    setAccessTokenExternal(null)
  }

  return res
}

export async function apiJson<T>(path: string, init: RequestInit = {}): Promise<T> {
  const res = await apiFetch(path, init)
  if (!res.ok) throw new ApiError(res.status, await parseError(res))
  return res.json() as Promise<T>
}
