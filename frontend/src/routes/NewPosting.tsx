import { useState, type FormEvent } from 'react'
import { useNavigate } from 'react-router-dom'
import { storePosting, analyzePosting } from '../api/gaps'

export default function NewPosting() {
  const navigate = useNavigate()
  const [text, setText] = useState('')
  const [title, setTitle] = useState('')
  const [company, setCompany] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)

  async function handleSubmit(event: FormEvent) {
    event.preventDefault()
    setError(null)
    setSubmitting(true)
    try {
      const posting = await storePosting(text, { title, company })
      await analyzePosting(posting.id)
      navigate(`/postings/${posting.id}`, { replace: true })
    } catch (err) {
      setError((err as Error).message)
    } finally {
      setSubmitting(false)
    }
  }

  const fieldClass = 'rounded border border-border bg-bg px-2 py-2 text-text [font-family:inherit]'

  return (
    <form onSubmit={handleSubmit} className="flex max-w-160 flex-col gap-2">
      <h2 className="text-xl text-text-h">New job posting</h2>
      <label htmlFor="posting-title">Title</label>
      <input
        id="posting-title"
        className={fieldClass}
        value={title}
        onChange={(e) => setTitle(e.target.value)}
      />
      <label htmlFor="posting-company">Company</label>
      <input
        id="posting-company"
        className={fieldClass}
        value={company}
        onChange={(e) => setCompany(e.target.value)}
      />
      <label htmlFor="posting-text">Job description</label>
      <textarea
        id="posting-text"
        className={fieldClass}
        value={text}
        onChange={(e) => setText(e.target.value)}
        rows={16}
        required
        placeholder="Paste the full job description text here"
      />
      {error && (
        <p role="alert" className="text-danger">
          {error}
        </p>
      )}
      <button
        type="submit"
        disabled={submitting || !text.trim()}
        className="mt-2 w-fit rounded bg-accent px-4 py-2 text-accent-contrast disabled:cursor-default disabled:opacity-60"
      >
        {submitting ? 'Analyzing…' : 'Store & analyze'}
      </button>
    </form>
  )
}
