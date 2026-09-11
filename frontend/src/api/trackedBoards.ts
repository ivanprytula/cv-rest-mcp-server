import { apiFetch, apiJson, ApiError } from './client'

export interface TrackedBoard {
  id: number
  kind: string
  company_name: string
  company_slug: string | null
  url: string | null
  notes: string | null
  group: string | null
  active: boolean
  created_at: string
  updated_at: string
}

export interface TrackedBoardCreate {
  kind: string
  company_name: string
  company_slug?: string
  url?: string
  notes?: string
  group?: string
}

export interface TrackedBoardUpdate {
  company_name?: string
  company_slug?: string
  url?: string
  notes?: string
  group?: string
  active?: boolean
}

export async function listTrackedBoards(): Promise<TrackedBoard[]> {
  return apiJson<TrackedBoard[]>('/api/v1/tracked-boards')
}

export async function createTrackedBoard(
  payload: TrackedBoardCreate,
): Promise<TrackedBoard> {
  const res = await apiFetch('/api/v1/tracked-boards', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
  if (!res.ok) throw new ApiError(res.status, await res.text())
  return res.json()
}

export async function updateTrackedBoard(
  id: number,
  payload: TrackedBoardUpdate,
): Promise<TrackedBoard> {
  const res = await apiFetch(`/api/v1/tracked-boards/${id}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
  if (!res.ok) throw new ApiError(res.status, await res.text())
  return res.json()
}

export async function deleteTrackedBoard(id: number): Promise<void> {
  const res = await apiFetch(`/api/v1/tracked-boards/${id}`, { method: 'DELETE' })
  if (!res.ok) throw new ApiError(res.status, await res.text())
}
