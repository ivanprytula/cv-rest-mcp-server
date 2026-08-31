const BASE_URL = import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000'

interface TokenPair {
  access_token: string
  token_type: string
  expires_in: number
}

async function throwDetail(res: Response, fallback: string): Promise<never> {
  const detail = await res
    .json()
    .then((body) => (typeof body?.detail === 'string' ? body.detail : fallback))
    .catch(() => fallback)
  throw new Error(detail)
}

export async function login(username: string, password: string): Promise<TokenPair> {
  const res = await fetch(`${BASE_URL}/api/v1/auth/token`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    credentials: 'include', // receives the __Host-refresh_token cookie
    body: JSON.stringify({ username, password }),
  })
  if (!res.ok) return throwDetail(res, 'Invalid credentials')
  return res.json()
}

// Credentialed cross-origin call: only this endpoint gets
// Access-Control-Allow-Credentials from the API (ADR-022).
export async function refresh(): Promise<TokenPair> {
  const res = await fetch(`${BASE_URL}/api/v1/auth/refresh`, {
    method: 'POST',
    credentials: 'include',
  })
  if (!res.ok) return throwDetail(res, 'Session expired')
  return res.json()
}

export async function logout(): Promise<void> {
  await fetch(`${BASE_URL}/api/v1/auth/logout`, {
    method: 'POST',
    credentials: 'include',
  })
}
