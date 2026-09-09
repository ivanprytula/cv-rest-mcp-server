import { apiFetch, ApiError } from './client'
import type { CVData } from './cv'

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
