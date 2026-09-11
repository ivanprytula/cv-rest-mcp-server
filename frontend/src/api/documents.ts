import { apiFetch, ApiError } from './client'
import type { CVData } from './cv'

export type DocumentKind = 'cv' | 'skill_bank' | 'jd_vocabulary'

export interface SkillAtom {
  atom: string
  group_id: string
  level: 'expert' | 'middle' | 'basic'
  priority: 'high' | 'medium' | 'low'
  category_hint: string
  aliases?: string[]
}

export interface SkillBankDocument {
  skills: SkillAtom[]
}

export interface VocabularyEntry {
  term: string
  group_id?: string
  aliases?: string[]
}

export interface JdVocabularyDocument {
  terms: VocabularyEntry[]
}

// Generic across all three document kinds — the backend route is already
// kind-generic. Returns null on 404 ("no document stored yet"), not an error.
export async function readDocument<T>(kind: DocumentKind): Promise<T | null> {
  const res = await apiFetch(`/api/v1/documents/${kind}`)
  if (res.status === 404) return null
  if (!res.ok) throw new ApiError(res.status, await res.text())
  return res.json() as Promise<T>
}

export async function writeDocument<T>(
  kind: DocumentKind,
  payload: T,
): Promise<{ version: number }> {
  const res = await apiFetch(`/api/v1/documents/${kind}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
  if (!res.ok) throw new ApiError(res.status, await res.text())
  return res.json() as Promise<{ version: number }>
}

// Sends the raw file bytes with its own content-type — the same
// format-agnostic intake as job postings (parse_job_posting_input on the
// backend). The server never saves the result; it only returns a draft.
export async function extractCvDraft(file: File): Promise<CVData> {
  const res = await apiFetch('/api/v1/documents/cv/extract', {
    method: 'POST',
    headers: { 'Content-Type': file.type || 'application/octet-stream' },
    body: file,
  })
  if (!res.ok) throw new ApiError(res.status, await res.text())
  return res.json() as Promise<CVData>
}

// Replaces the caller's own CV document. Used to save a reviewed/edited
// extraction draft — never called automatically by extractCvDraft.
export async function writeCvDocument(payload: CVData): Promise<{ version: number }> {
  const res = await apiFetch('/api/v1/documents/cv', {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
  if (!res.ok) throw new ApiError(res.status, await res.text())
  return res.json() as Promise<{ version: number }>
}
