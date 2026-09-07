import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { listPostings } from '../api/gaps'
import { DataTable, TableScroll, th } from '../components/Table'

export default function Postings() {
  const { data, isLoading, isError, error } = useQuery({
    queryKey: ['postings'],
    queryFn: listPostings,
  })

  if (isLoading) return <p>Loading postings…</p>
  if (isError) return <p role="alert">Failed to load postings: {(error as Error).message}</p>

  return (
    <>
      <nav className="mb-3" aria-label="Posting actions">
        <Link to="/postings/new" className="text-accent">
          + New posting
        </Link>
      </nav>
      {!data || data.length === 0 ? (
        <p>No job postings stored yet.</p>
      ) : (
        <TableScroll>
          <DataTable>
            <caption className="mb-2 text-muted">Stored job postings</caption>
            <thead>
              <tr>
                <th className={th}>Title</th>
                <th className={th}>Company</th>
                <th className={th}>Source</th>
                <th className={th}>First seen</th>
                <th className={th}>Status</th>
              </tr>
            </thead>
            <tbody>
              {data.map((posting) => (
                <tr key={posting.id}>
                  <td className={th}>
                    <Link to={`/postings/${posting.id}`} className="text-accent">
                      {posting.title || `Posting ${posting.id}`}
                    </Link>
                  </td>
                  <td className={th}>{posting.company || '—'}</td>
                  <td className={th}>{posting.source}</td>
                  <td className={th}>{new Date(posting.first_seen_at).toLocaleDateString()}</td>
                  <td className={th}>{posting.closed_at ? 'Closed' : 'Open'}</td>
                </tr>
              ))}
            </tbody>
          </DataTable>
        </TableScroll>
      )}
    </>
  )
}
