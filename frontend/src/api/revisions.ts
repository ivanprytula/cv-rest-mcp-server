import { apiFetch, apiJson, ApiError } from './client'

export interface RevisionSummary {
  id: string
  name: string
  created_at: string
  size_bytes: number
}

interface RevisionsResponse {
  revisions: RevisionSummary[]
}

export async function listRevisions(): Promise<RevisionSummary[]> {
  const { revisions } = await apiJson<RevisionsResponse>('/api/v1/revisions')
  return revisions
}

export async function deleteRevision(id: string): Promise<void> {
  const res = await apiFetch(`/api/v1/revisions/${id}`, { method: 'DELETE' })
  if (!res.ok) throw new ApiError(res.status, await res.text())
}
