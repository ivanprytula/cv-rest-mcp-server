import { useState, type ChangeEvent, type FormEvent } from 'react'
import { extractCvDraft, writeCvDocument } from '../api/documents'
import type { CVData } from '../api/cv'

const fieldClass = 'rounded border border-border bg-bg px-2 py-2 text-text [font-family:inherit]'

export default function CvIntake() {
  const [file, setFile] = useState<File | null>(null)
  const [draftText, setDraftText] = useState('')
  const [extracting, setExtracting] = useState(false)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [saved, setSaved] = useState(false)

  function handleFileChange(event: ChangeEvent<HTMLInputElement>) {
    setFile(event.target.files?.[0] ?? null)
    setSaved(false)
  }

  async function handleExtract(event: FormEvent) {
    event.preventDefault()
    if (!file) return
    setError(null)
    setSaved(false)
    setExtracting(true)
    try {
      const draft = await extractCvDraft(file)
      setDraftText(JSON.stringify(draft, null, 2))
    } catch (err) {
      setError((err as Error).message)
    } finally {
      setExtracting(false)
    }
  }

  async function handleSave() {
    setError(null)
    setSaved(false)
    let payload: CVData
    try {
      payload = JSON.parse(draftText)
    } catch {
      setError('Draft is not valid JSON — fix it before saving.')
      return
    }
    setSaving(true)
    try {
      await writeCvDocument(payload)
      setSaved(true)
    } catch (err) {
      setError((err as Error).message)
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="flex max-w-160 flex-col gap-4">
      <div>
        <h2 className="text-xl text-text-h">Import CV from a file</h2>
        <p className="text-sm text-muted">
          Upload a resume (PDF, DOCX, text, or Markdown) to draft your CV document. Review and
          edit the extracted JSON below, then save — nothing is written until you do.
        </p>
      </div>

      <form onSubmit={handleExtract} className="flex flex-col gap-2">
        <label htmlFor="cv-file">Resume file</label>
        <input
          id="cv-file"
          type="file"
          accept=".pdf,.docx,.txt,.md,application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document,text/plain,text/markdown"
          onChange={handleFileChange}
          className={fieldClass}
        />
        <button
          type="submit"
          disabled={!file || extracting}
          className="mt-2 w-fit rounded bg-accent px-4 py-2 text-accent-contrast disabled:cursor-default disabled:opacity-60"
        >
          {extracting ? 'Extracting…' : 'Extract draft'}
        </button>
      </form>

      {error && (
        <p role="alert" className="text-danger">
          {error}
        </p>
      )}

      {draftText && (
        <div className="flex flex-col gap-2">
          <label htmlFor="cv-draft">Draft (edit before saving)</label>
          <textarea
            id="cv-draft"
            className={`${fieldClass} font-mono text-sm`}
            value={draftText}
            onChange={(e) => {
              setDraftText(e.target.value)
              setSaved(false)
            }}
            rows={24}
            spellCheck={false}
          />
          <button
            type="button"
            onClick={handleSave}
            disabled={saving}
            className="w-fit rounded bg-accent px-4 py-2 text-accent-contrast disabled:cursor-default disabled:opacity-60"
          >
            {saving ? 'Saving…' : 'Save as my CV'}
          </button>
          {saved && <p className="text-accent">Saved.</p>}
        </div>
      )}
    </div>
  )
}
