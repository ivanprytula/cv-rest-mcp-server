import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { downloadTailoredPdf, getCv } from '../api/cv'
import CvView from '../components/CvView'

export default function RevisionPreview() {
  const { id } = useParams<{ id: string }>()
  const { data, isLoading, isError, error } = useQuery({
    queryKey: ['cv', id],
    queryFn: () => getCv(id),
    enabled: Boolean(id),
  })
  const [pdfError, setPdfError] = useState<string | null>(null)
  const [downloadingPdf, setDownloadingPdf] = useState(false)

  async function handleDownloadPdf() {
    if (!id) return
    setPdfError(null)
    setDownloadingPdf(true)
    try {
      await downloadTailoredPdf(id)
    } catch (err) {
      setPdfError((err as Error).message)
    } finally {
      setDownloadingPdf(false)
    }
  }

  return (
    <div>
      <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
        <Link to="/" className="text-accent">
          &larr; Revisions
        </Link>
        {data && (
          <button
            type="button"
            onClick={handleDownloadPdf}
            disabled={downloadingPdf}
            className="rounded border border-border px-3 py-1.5 disabled:cursor-default disabled:opacity-60"
          >
            {downloadingPdf ? 'Generating…' : 'Download PDF'}
          </button>
        )}
      </div>
      {isLoading && <p>Loading revision…</p>}
      {isError && <p role="alert">Failed to load revision: {(error as Error).message}</p>}
      {pdfError && <p role="alert">{pdfError}</p>}
      {data && <CvView cv={data} />}
    </div>
  )
}
