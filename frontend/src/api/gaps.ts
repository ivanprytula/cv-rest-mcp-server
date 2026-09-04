import { apiJson } from './client'

export interface RoadmapItem {
  term: string
  tier: string
  group_id: string
  jd_count: number
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
  const { postings } = await apiJson<PostingsResponse>('/api/v1/gaps/postings')
  return postings
}

export async function fetchGapReport(postingId: number): Promise<GapReport> {
  return apiJson<GapReport>(`/api/v1/gaps/postings/${postingId}`)
}
