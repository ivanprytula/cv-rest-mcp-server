import { apiFetch, apiJson, ApiError } from './client'

export interface Experience {
  role: string
  company: string
  period: string
  highlights: string[]
  tech: string[]
}

export interface Education {
  degree: string
  institution: string
  year: string
}

export interface Project {
  name: string
  description: string
  url: string
  tech: string[]
}

export interface Certification {
  name: string
  issuer: string
  date: string
  url: string
}

export interface Publication {
  title: string
  venue: string
  year: string
  url: string
}

export interface Award {
  name: string
  issuer: string
  date: string
}

export interface Volunteering {
  role: string
  organization: string
  period: string
  description: string
}

export interface Website {
  name: string
  url: string
}

export interface SkillSubCategory {
  name: string
  items: string[]
}

export interface SkillCategory {
  name: string
  sub_categories: SkillSubCategory[]
}

export interface CVData {
  name: string
  title: string
  email: string
  phone: string
  telegram: string
  location: string
  github: string
  linkedin: string
  websites: Website[]
  summary: string
  skills: SkillCategory[]
  additional_skills: SkillCategory[]
  experience: Experience[]
  education: Education[]
  languages: string[]
  projects: Project[]
  certifications: Certification[]
  publications: Publication[]
  awards: Award[]
  volunteering: Volunteering[]
}

// Mirrors renderer.py's _flatten_skills: each category collapses its
// sub_categories' items into one flat, ordered list for display.
export function flattenSkills(categories: SkillCategory[]): { category: string; items: string[] }[] {
  const flat: { category: string; items: string[] }[] = []
  for (const cat of categories) {
    const items = cat.sub_categories.flatMap((sub) => sub.items)
    if (items.length > 0) flat.push({ category: cat.name, items })
  }
  return flat
}

// `tailored` is a bare cv_tailored-<ts>.json filename (from /api/v1/cv/tailor's
// saved_to) or the literal 'latest'; omit to fetch the public, unauthenticated
// live CV. A tailored fetch goes through the operator-only /api/v1/cv (never
// the public /cv, which has no `tailored` support at all).
export async function getCv(tailored?: string): Promise<CVData> {
  if (!tailored) return apiJson<CVData>('/cv')
  return apiJson<CVData>(`/api/v1/cv?tailored=${encodeURIComponent(tailored)}`)
}

const FILENAME_RE = /filename="([^"]+)"/

// Fetches the themed PDF for a tailored revision via the operator-only
// /api/v1/cv/pdf (Bearer-authenticated, same as getCv) and triggers a browser
// download using the server's own filename (Content-Disposition). The public
// /cv/pdf never accepts a `tailored` selector — this dedicated endpoint is
// the only way to download a tailored PDF, and only the SPA can reach it.
export async function downloadTailoredPdf(tailored: string): Promise<void> {
  const res = await apiFetch(`/api/v1/cv/pdf?tailored=${encodeURIComponent(tailored)}`)
  if (!res.ok) throw new ApiError(res.status, `Failed to generate PDF (${res.status})`)

  const filename = FILENAME_RE.exec(res.headers.get('content-disposition') ?? '')?.[1] ?? 'cv.pdf'
  const url = URL.createObjectURL(await res.blob())
  const link = document.createElement('a')
  link.href = url
  link.download = filename
  link.click()
  URL.revokeObjectURL(url)
}
