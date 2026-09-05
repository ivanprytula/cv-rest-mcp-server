import { useQuery } from '@tanstack/react-query'
import { fetchRoadmap } from '../api/gaps'

const TIER_LABEL: Record<string, string> = {
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
    <table className="roadmap-table">
      <thead>
        <tr>
          <th>Term</th>
          <th>Wanted by</th>
          <th>Tier</th>
          <th>Level asked</th>
          <th>Note</th>
        </tr>
      </thead>
      <tbody>
        {data.map((item) => (
          <tr key={`${item.term}-${item.tier}`}>
            <td>{item.term}</td>
            <td>
              {item.jd_count} {item.jd_count === 1 ? 'posting' : 'postings'}
            </td>
            <td>
              <span className={`tier tier-${item.tier}`}>
                {TIER_LABEL[item.tier] ?? item.tier}
              </span>
            </td>
            <td>{item.strongest_level_asked ?? '—'}</td>
            <td>{item.note ?? ''}</td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}
