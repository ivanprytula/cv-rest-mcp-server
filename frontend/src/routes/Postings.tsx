import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { listPostings } from '../api/gaps'

export default function Postings() {
  const { data, isLoading, isError, error } = useQuery({
    queryKey: ['postings'],
    queryFn: listPostings,
  })

  if (isLoading) return <p>Loading postings…</p>
  if (isError) return <p role="alert">Failed to load postings: {(error as Error).message}</p>
  if (!data || data.length === 0) return <p>No job postings stored yet.</p>

  return (
    <table className="postings-table">
      <thead>
        <tr>
          <th>Title</th>
          <th>Company</th>
          <th>Source</th>
          <th>First seen</th>
          <th>Status</th>
        </tr>
      </thead>
      <tbody>
        {data.map((posting) => (
          <tr key={posting.id}>
            <td>
              <Link to={`/postings/${posting.id}`}>{posting.title || `Posting ${posting.id}`}</Link>
            </td>
            <td>{posting.company || '—'}</td>
            <td>{posting.source}</td>
            <td>{new Date(posting.first_seen_at).toLocaleDateString()}</td>
            <td>{posting.closed_at ? 'Closed' : 'Open'}</td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}
