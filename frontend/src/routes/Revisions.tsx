import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { listRevisions } from '../api/revisions'

export default function Revisions() {
  const { data, isLoading, isError, error } = useQuery({
    queryKey: ['revisions'],
    queryFn: listRevisions,
  })

  if (isLoading) return <p>Loading revisions…</p>
  if (isError) return <p role="alert">Failed to load revisions: {(error as Error).message}</p>
  if (!data || data.length === 0) return <p>No tailored CV revisions yet.</p>

  return (
    <table className="revisions-table">
      <thead>
        <tr>
          <th>Name</th>
          <th>Created</th>
          <th>Size</th>
        </tr>
      </thead>
      <tbody>
        {data.map((revision) => (
          <tr key={revision.name}>
            <td>
              <Link to={`/revisions/${encodeURIComponent(revision.name)}`}>{revision.name}</Link>
            </td>
            <td>{new Date(revision.created_at).toLocaleString()}</td>
            <td>{(revision.size_bytes / 1024).toFixed(1)} KB</td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}
