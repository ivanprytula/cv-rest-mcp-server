import { apiFetch, apiJson, ApiError } from './client'

export interface RoadmapItem {
  term: string
  tier: string
  group_id: string
  posting_count: number
  strongest_level_asked: string | null
  note: string | null
}

export interface SkillGap {
  term: string
  tier: string
  group_id: string
  required_level: string | null
  bank_level: string | null
  note: string | null
  evidence: string
}

export interface GapReport {
  posting_id: number
  coverage: number
  gaps: SkillGap[]
  unrecognized: string[]
}

export interface PhraseCluster {
  label: string
  phrases: string[]
}

export interface PhraseClusters {
  posting_id: number
  clusters: PhraseCluster[]
}

export interface PostingCreated {
  id: number
  content_hash: string
  duplicate: boolean
}

export interface PostingSummary {
  id: number
  source: string
  company: string
  title: string
  url: string
  first_seen_at: string
  last_seen_at: string
  closed_at: string | null
}

interface RoadmapResponse {
  items: RoadmapItem[]
  analyzer_version: string
}

interface PostingsResponse {
  postings: PostingSummary[]
}

export async function fetchRoadmap(): Promise<RoadmapItem[]> {
  const { items } = await apiJson<RoadmapResponse>('/api/v1/gaps/roadmap')
  return items
}

export async function listPostings(): Promise<PostingSummary[]> {
  const { postings } = await apiJson<PostingsResponse>('/api/v1/postings')
  return postings
}

export async function fetchGapReport(postingId: number): Promise<GapReport> {
  return apiJson<GapReport>(`/api/v1/postings/${postingId}`)
}

// Stores a pasted JD as plain text (same parser as /api/v1/cv/tailor — PDF,
// DOCX, Markdown, JSON also accepted, but the SPA only offers a paste box).
// Re-posting identical text returns the existing posting (`duplicate: true`)
// rather than erroring.
export async function storePosting(
  text: string,
  options: { title?: string; company?: string } = {},
): Promise<PostingCreated> {
  const params = new URLSearchParams()
  if (options.title) params.set('title', options.title)
  if (options.company) params.set('company', options.company)
  const query = params.toString()
  const res = await apiFetch(`/api/v1/postings${query ? `?${query}` : ''}`, {
    method: 'POST',
    headers: { 'Content-Type': 'text/plain' },
    body: text,
  })
  if (!res.ok) throw new ApiError(res.status, await res.text())
  return res.json() as Promise<PostingCreated>
}

export async function analyzePosting(postingId: number): Promise<GapReport> {
  return apiJson<GapReport>(`/api/v1/postings/${postingId}/analyze`, {
    method: 'POST',
  })
}

export async function fetchClusters(postingId: number): Promise<PhraseCluster[]> {
  const { clusters } = await apiJson<PhraseClusters>(
    `/api/v1/postings/${postingId}/clusters`,
  )
  return clusters
}

export async function clusterPosting(postingId: number): Promise<PhraseCluster[]> {
  const { clusters } = await apiJson<PhraseClusters>(
    `/api/v1/postings/${postingId}/cluster`,
    { method: 'POST' },
  )
  return clusters
}
