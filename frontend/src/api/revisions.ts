import { apiJson } from './client'

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
