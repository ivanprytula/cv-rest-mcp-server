import { useQuery } from '@tanstack/react-query'
import { fetchRoadmap } from '../api/gaps'
import { DataTable, TableScroll, th } from '../components/Table'
import TierBadge from '../components/TierBadge'

const TIER_LABEL: Record<string, string> = {
  stale: 'Refresh',
  unvouched: 'Update CV',
  deferred: 'Parked',
  unknown: 'Learn',
}

export default function Roadmap() {
  const { data, isLoading, isError, error } = useQuery({
    queryKey: ['roadmap'],
    queryFn: fetchRoadmap,
  })

  if (isLoading) return <p>Loading roadmap…</p>
  if (isError) return <p role="alert">Failed to load roadmap: {(error as Error).message}</p>
  if (!data || data.length === 0)
    return <p>No gaps yet. Store and analyse some job postings first.</p>

  return (
    <TableScroll>
      <DataTable>
        <caption className="mb-2 text-muted">
          Learning roadmap: gap terms ranked by how many postings demand them
        </caption>
        <thead>
          <tr>
            <th className={th}>Term</th>
            <th className={th}>Wanted by</th>
            <th className={th}>Tier</th>
            <th className={th}>Level asked</th>
            <th className={th}>Note</th>
          </tr>
        </thead>
        <tbody>
          {data.map((item) => (
            <tr key={`${item.term}-${item.tier}`}>
              <td className={th}>{item.term}</td>
              <td className={th}>
                {item.jd_count} {item.jd_count === 1 ? 'posting' : 'postings'}
              </td>
              <td className={th}>
                <TierBadge tier={item.tier} label={TIER_LABEL[item.tier] ?? item.tier} />
              </td>
              <td className={th}>{item.strongest_level_asked ?? '—'}</td>
              <td className={th}>{item.note ?? ''}</td>
            </tr>
          ))}
        </tbody>
      </DataTable>
    </TableScroll>
  )
}
