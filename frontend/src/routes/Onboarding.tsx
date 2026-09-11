import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import {
  readDocument,
  writeDocument,
  type JdVocabularyDocument,
  type SkillAtom,
  type SkillBankDocument,
  type VocabularyEntry,
} from '../api/documents'
import type { CVData } from '../api/cv'

const fieldClass = 'rounded border border-border bg-bg px-2 py-2 text-text [font-family:inherit]'

const LEVELS: SkillAtom['level'][] = ['expert', 'middle', 'basic']
const PRIORITIES: SkillAtom['priority'][] = ['high', 'medium', 'low']

function emptyAtom(): SkillAtom {
  return { atom: '', group_id: '', level: 'middle', priority: 'medium', category_hint: '', aliases: [] }
}

function emptyTerm(): VocabularyEntry {
  return { term: '', group_id: '', aliases: [] }
}

function splitAliases(text: string): string[] {
  return text
    .split(',')
    .map((a) => a.trim())
    .filter(Boolean)
}

export default function Onboarding() {
  const [cvDoc, setCvDoc] = useState<CVData | null>(null)
  const [loadError, setLoadError] = useState<string | null>(null)

  const [skills, setSkills] = useState<SkillAtom[]>([])
  const [skillsSaving, setSkillsSaving] = useState(false)
  const [skillsError, setSkillsError] = useState<string | null>(null)
  const [skillsSaved, setSkillsSaved] = useState(false)

  const [terms, setTerms] = useState<VocabularyEntry[]>([])
  const [termsSaving, setTermsSaving] = useState(false)
  const [termsError, setTermsError] = useState<string | null>(null)
  const [termsSaved, setTermsSaved] = useState(false)

  useEffect(() => {
    readDocument<CVData>('cv')
      .then(setCvDoc)
      .catch((err) => setLoadError((err as Error).message))
    readDocument<SkillBankDocument>('skill_bank')
      .then((doc) => setSkills(doc?.skills ?? []))
      .catch((err) => setSkillsError((err as Error).message))
    readDocument<JdVocabularyDocument>('jd_vocabulary')
      .then((doc) => setTerms(doc?.terms ?? []))
      .catch((err) => setTermsError((err as Error).message))
  }, [])

  const skillsValid =
    skills.length > 0 &&
    skills.every(
      (s) => s.atom.trim() && s.group_id.trim() && s.category_hint.includes(' > '),
    )

  async function handleSaveSkills() {
    setSkillsError(null)
    setSkillsSaved(false)
    setSkillsSaving(true)
    try {
      await writeDocument<SkillBankDocument>('skill_bank', { skills })
      setSkillsSaved(true)
    } catch (err) {
      setSkillsError((err as Error).message)
    } finally {
      setSkillsSaving(false)
    }
  }

  const termsValid = terms.length > 0 && terms.every((t) => t.term.trim())

  async function handleSaveTerms() {
    setTermsError(null)
    setTermsSaved(false)
    setTermsSaving(true)
    try {
      await writeDocument<JdVocabularyDocument>('jd_vocabulary', { terms })
      setTermsSaved(true)
    } catch (err) {
      setTermsError((err as Error).message)
    } finally {
      setTermsSaving(false)
    }
  }

  return (
    <div className="flex max-w-160 flex-col gap-8">
      <div>
        <h1 className="text-2xl text-text-h">Profile setup</h1>
        <p className="text-sm text-muted">
          Populate your CV, skill bank, and JD vocabulary — this data drives how job postings are
          matched and tailored for you.
        </p>
      </div>

      <section className="flex flex-col gap-2">
        <h2 className="text-xl text-text-h">CV</h2>
        {loadError && (
          <p role="alert" className="text-danger">
            {loadError}
          </p>
        )}
        <p className="text-sm text-muted">
          {cvDoc ? `CV on file: ${cvDoc.name || cvDoc.title || 'saved'}.` : 'No CV yet.'}
        </p>
        <Link to="/cv/import" className="w-fit text-accent">
          {cvDoc ? 'Replace / edit CV' : 'Import CV'}
        </Link>
      </section>

      <section className="flex flex-col gap-3">
        <h2 className="text-xl text-text-h">Skill bank</h2>
        <p className="text-sm text-muted">
          The skills you can vouch for. Category hint must be in the form &quot;Group &gt;
          Sub&quot;.
        </p>
        {/* Onboarding only edits the active "skills" list; "deferred" (parked/stale atoms) is a
            fast-follow — see baseline.py's ATOM docstring. */}
        {skills.map((skill, idx) => (
          <div key={idx} className="flex flex-wrap items-start gap-2 rounded border border-border p-2">
            <input
              className={fieldClass}
              placeholder="Skill (e.g. PostgreSQL)"
              value={skill.atom}
              onChange={(e) => {
                const next = [...skills]
                next[idx] = { ...skill, atom: e.target.value }
                setSkills(next)
                setSkillsSaved(false)
              }}
            />
            <input
              className={fieldClass}
              placeholder="Group id (e.g. databases)"
              value={skill.group_id}
              onChange={(e) => {
                const next = [...skills]
                next[idx] = { ...skill, group_id: e.target.value }
                setSkills(next)
                setSkillsSaved(false)
              }}
            />
            <select
              className={fieldClass}
              value={skill.level}
              onChange={(e) => {
                const next = [...skills]
                next[idx] = { ...skill, level: e.target.value as SkillAtom['level'] }
                setSkills(next)
                setSkillsSaved(false)
              }}
            >
              {LEVELS.map((level) => (
                <option key={level} value={level}>
                  {level}
                </option>
              ))}
            </select>
            <select
              className={fieldClass}
              value={skill.priority}
              onChange={(e) => {
                const next = [...skills]
                next[idx] = { ...skill, priority: e.target.value as SkillAtom['priority'] }
                setSkills(next)
                setSkillsSaved(false)
              }}
            >
              {PRIORITIES.map((priority) => (
                <option key={priority} value={priority}>
                  {priority}
                </option>
              ))}
            </select>
            <div className="flex flex-col gap-1">
              <input
                className={fieldClass}
                placeholder="Category hint (Group > Sub)"
                value={skill.category_hint}
                onChange={(e) => {
                  const next = [...skills]
                  next[idx] = { ...skill, category_hint: e.target.value }
                  setSkills(next)
                  setSkillsSaved(false)
                }}
              />
              {skill.category_hint && !skill.category_hint.includes(' > ') && (
                <span className="text-xs text-danger">Must contain &quot; &gt; &quot;</span>
              )}
            </div>
            <input
              className={fieldClass}
              placeholder="Aliases (comma-separated)"
              defaultValue={skill.aliases?.join(', ') ?? ''}
              onBlur={(e) => {
                const next = [...skills]
                next[idx] = { ...skill, aliases: splitAliases(e.target.value) }
                setSkills(next)
                setSkillsSaved(false)
              }}
            />
            <button
              type="button"
              onClick={() => {
                setSkills(skills.filter((_, i) => i !== idx))
                setSkillsSaved(false)
              }}
              className="rounded border border-border px-2 py-2"
            >
              Remove
            </button>
          </div>
        ))}
        <button
          type="button"
          onClick={() => setSkills([...skills, emptyAtom()])}
          className="w-fit rounded border border-border px-3 py-1.5"
        >
          + Add skill
        </button>
        {skillsError && (
          <p role="alert" className="text-danger">
            {skillsError}
          </p>
        )}
        <button
          type="button"
          onClick={handleSaveSkills}
          disabled={!skillsValid || skillsSaving}
          className="w-fit rounded bg-accent px-4 py-2 text-accent-contrast disabled:cursor-default disabled:opacity-60"
        >
          {skillsSaving ? 'Saving…' : 'Save skill bank'}
        </button>
        {skillsSaved && <p className="text-accent">Saved.</p>}
      </section>

      <section className="flex flex-col gap-3">
        <h2 className="text-xl text-text-h">JD vocabulary</h2>
        <p className="text-sm text-muted">
          Terms and their aliases that job postings use, so matching can recognize them.
        </p>
        {terms.map((entry, idx) => (
          <div key={idx} className="flex flex-wrap items-start gap-2 rounded border border-border p-2">
            <input
              className={fieldClass}
              placeholder="Term (e.g. AWS)"
              value={entry.term}
              onChange={(e) => {
                const next = [...terms]
                next[idx] = { ...entry, term: e.target.value }
                setTerms(next)
                setTermsSaved(false)
              }}
            />
            <input
              className={fieldClass}
              placeholder="Group id (optional)"
              value={entry.group_id ?? ''}
              onChange={(e) => {
                const next = [...terms]
                next[idx] = { ...entry, group_id: e.target.value }
                setTerms(next)
                setTermsSaved(false)
              }}
            />
            <input
              className={fieldClass}
              placeholder="Aliases (comma-separated)"
              defaultValue={entry.aliases?.join(', ') ?? ''}
              onBlur={(e) => {
                const next = [...terms]
                next[idx] = { ...entry, aliases: splitAliases(e.target.value) }
                setTerms(next)
                setTermsSaved(false)
              }}
            />
            <button
              type="button"
              onClick={() => {
                setTerms(terms.filter((_, i) => i !== idx))
                setTermsSaved(false)
              }}
              className="rounded border border-border px-2 py-2"
            >
              Remove
            </button>
          </div>
        ))}
        <button
          type="button"
          onClick={() => setTerms([...terms, emptyTerm()])}
          className="w-fit rounded border border-border px-3 py-1.5"
        >
          + Add term
        </button>
        {termsError && (
          <p role="alert" className="text-danger">
            {termsError}
          </p>
        )}
        <button
          type="button"
          onClick={handleSaveTerms}
          disabled={!termsValid || termsSaving}
          className="w-fit rounded bg-accent px-4 py-2 text-accent-contrast disabled:cursor-default disabled:opacity-60"
        >
          {termsSaving ? 'Saving…' : 'Save JD vocabulary'}
        </button>
        {termsSaved && <p className="text-accent">Saved.</p>}
      </section>
    </div>
  )
}
