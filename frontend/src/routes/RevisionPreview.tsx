import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { downloadTailoredPdf, getCv } from '../api/cv'
import CvView from '../components/CvView'

export default function RevisionPreview() {
  const { name } = useParams<{ name: string }>()
  const { data, isLoading, isError, error } = useQuery({
    queryKey: ['cv', name],
    queryFn: () => getCv(name),
    enabled: Boolean(name),
  })
  const [pdfError, setPdfError] = useState<string | null>(null)
  const [downloadingPdf, setDownloadingPdf] = useState(false)

  async function handleDownloadPdf() {
    if (!name) return
    setPdfError(null)
    setDownloadingPdf(true)
    try {
      await downloadTailoredPdf(name)
    } catch (err) {
      setPdfError((err as Error).message)
    } finally {
      setDownloadingPdf(false)
    }
  }

  return (
    <div className="revision-preview">
      <div className="revision-preview-toolbar">
        <Link to="/">&larr; Revisions</Link>
        {data && (
          <button type="button" onClick={handleDownloadPdf} disabled={downloadingPdf}>
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
