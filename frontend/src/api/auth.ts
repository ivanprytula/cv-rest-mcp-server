import { apiFetch, apiJson, ApiError } from './client'

const BASE_URL = import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000'

interface TokenPair {
  access_token: string
  token_type: string
  expires_in: number
}

interface RegisteredUser {
  id: number
  username: string
  email: string
}

export interface Me {
  subject: string
  role: string
  scopes: string[]
}

export interface AdminUser {
  id: number
  username: string
  email: string
  is_active: boolean
  role: string
}

async function throwDetail(res: Response, fallback: string): Promise<never> {
  const detail = await res
    .json()
    .then((body) => (typeof body?.detail === 'string' ? body.detail : fallback))
    .catch(() => fallback)
  throw new Error(detail)
}

export async function register(
  username: string,
  email: string,
  password: string,
): Promise<RegisteredUser> {
  const res = await fetch(`${BASE_URL}/api/v1/auth/register`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ username, email, password }),
  })
  if (!res.ok) return throwDetail(res, 'Could not create account')
  return res.json()
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

export async function getMe(): Promise<Me> {
  return apiJson<Me>('/api/v1/auth/me')
}

export async function listUsers(): Promise<AdminUser[]> {
  return apiJson<AdminUser[]>('/api/v1/auth/users')
}

export async function setUserRole(username: string, role: string): Promise<void> {
  const res = await apiFetch(`/api/v1/auth/users/${username}/role`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ role }),
  })
  if (!res.ok) throw new ApiError(res.status, await res.text())
}

export async function enableUser(username: string): Promise<void> {
  const res = await apiFetch(`/api/v1/auth/users/${username}/enable`, { method: 'POST' })
  if (!res.ok) throw new ApiError(res.status, await res.text())
}

export async function disableUser(username: string): Promise<void> {
  const res = await apiFetch(`/api/v1/auth/users/${username}/disable`, { method: 'POST' })
  if (!res.ok) throw new ApiError(res.status, await res.text())
}
