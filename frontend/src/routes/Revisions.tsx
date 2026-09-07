import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { listRevisions } from '../api/revisions'
import { DataTable, TableScroll, th } from '../components/Table'

export default function Revisions() {
  const { data, isLoading, isError, error } = useQuery({
    queryKey: ['revisions'],
    queryFn: listRevisions,
  })

  if (isLoading) return <p>Loading revisions…</p>
  if (isError) return <p role="alert">Failed to load revisions: {(error as Error).message}</p>
  if (!data || data.length === 0) return <p>No tailored CV revisions yet.</p>

  return (
    <TableScroll>
      <DataTable>
        <caption className="mb-2 text-muted">Tailored CV revisions</caption>
        <thead>
          <tr>
            <th className={th}>Name</th>
            <th className={th}>Created</th>
            <th className={th}>Size</th>
          </tr>
        </thead>
        <tbody>
          {data.map((revision) => (
            <tr key={revision.id}>
              <td className={th}>
                <Link to={`/revisions/${encodeURIComponent(revision.id)}`} className="text-accent">
                  {revision.name}
                </Link>
              </td>
              <td className={th}>{new Date(revision.created_at).toLocaleString()}</td>
              <td className={th}>{(revision.size_bytes / 1024).toFixed(1)} KB</td>
            </tr>
          ))}
        </tbody>
      </DataTable>
    </TableScroll>
  )
}
