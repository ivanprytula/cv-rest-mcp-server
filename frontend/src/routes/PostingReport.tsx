import { useQuery } from '@tanstack/react-query'
import { useParams } from 'react-router-dom'
import { fetchGapReport, type SkillGap } from '../api/gaps'

const TIERS: { key: string; heading: string; blurb: string }[] = [
  { key: 'covered', heading: 'Covered', blurb: 'Already on your CV.' },
  { key: 'unvouched', heading: 'Unvouched', blurb: 'In your skill bank, but not on the CV.' },
  { key: 'deferred', heading: 'Deferred', blurb: 'Parked deliberately.' },
  { key: 'unknown', heading: 'Unknown', blurb: 'Not in your bank at all.' },
]

function TierSection({ heading, blurb, gaps }: { heading: string; blurb: string; gaps: SkillGap[] }) {
  if (gaps.length === 0) return null
  return (
    <section>
      <h3>
        {heading} ({gaps.length})
      </h3>
      <p className="tier-blurb">{blurb}</p>
      <ul>
        {gaps.map((gap) => (
          <li key={gap.term}>
            {gap.term}
            {gap.required_level ? ` — ${gap.required_level} asked` : ''}
            {gap.note ? ` — ${gap.note}` : ''}
          </li>
        ))}
      </ul>
    </section>
  )
}

export default function PostingReport() {
  const { id } = useParams<{ id: string }>()
  const postingId = Number(id)
  const { data, isLoading, isError, error } = useQuery({
    queryKey: ['gap-report', postingId],
    queryFn: () => fetchGapReport(postingId),
    enabled: Number.isFinite(postingId),
  })

  if (isLoading) return <p>Loading report…</p>
  if (isError) return <p role="alert">Failed to load report: {(error as Error).message}</p>
  if (!data) return <p>No analysis for this posting yet.</p>

  return (
    <div className="gap-report">
      <p>
        Coverage: <strong>{Math.round(data.coverage * 100)}%</strong> of {data.gaps.length}{' '}
        requirements already on your CV.
      </p>
      {TIERS.map((tier) => (
        <TierSection
          key={tier.key}
          heading={tier.heading}
          blurb={tier.blurb}
          gaps={data.gaps.filter((gap) => gap.tier === tier.key)}
        />
      ))}
    </div>
  )
}
