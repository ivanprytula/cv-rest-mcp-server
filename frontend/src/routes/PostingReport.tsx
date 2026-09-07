import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { useParams } from 'react-router-dom'
import {
  fetchGapReport,
  fetchClusters,
  clusterPosting,
  type SkillGap,
} from '../api/gaps'

// Cheapest-to-close first, matching matching/gap.py's TIERS order.
const TIERS: { key: string; heading: string; blurb: string }[] = [
  { key: 'covered', heading: 'Covered', blurb: 'On your CV and defensible today.' },
  { key: 'stale', heading: 'Stale', blurb: 'On your CV, but needs a refresher before an interview.' },
  { key: 'unvouched', heading: 'Unvouched', blurb: 'In your skill bank, but not on the CV.' },
  { key: 'deferred', heading: 'Deferred', blurb: 'Parked deliberately.' },
  { key: 'unknown', heading: 'Unknown', blurb: 'Not in your bank at all — the real "go learn it" tier.' },
]

const sectionBlurb = 'mb-1 text-sm text-muted'

function TierSection({ heading, blurb, gaps }: { heading: string; blurb: string; gaps: SkillGap[] }) {
  if (gaps.length === 0) return null
  const headingId = `tier-${heading.toLowerCase()}`
  return (
    <section aria-labelledby={headingId} className="mb-6">
      <h3 id={headingId} className="text-lg text-text-h">
        {heading} ({gaps.length})
      </h3>
      <p className={sectionBlurb}>{blurb}</p>
      <ul className="list-disc pl-5">
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

function UnrecognizedSection({ tokens }: { tokens: string[] }) {
  if (tokens.length === 0) return null
  return (
    <section aria-labelledby="unrecognized-heading" className="mb-6">
      <h3 id="unrecognized-heading" className="text-lg text-text-h">
        Unrecognized tokens
      </h3>
      <p className={sectionBlurb}>
        Technical-looking words this JD uses that aren't in the vocabulary yet — candidates to add to your
        skill vocabulary.
      </p>
      <p className="font-mono">{tokens.join(', ')}</p>
    </section>
  )
}

function ClustersSection({ postingId }: { postingId: number }) {
  const queryClient = useQueryClient()
  const { data: clusters, isLoading } = useQuery({
    queryKey: ['clusters', postingId],
    queryFn: () => fetchClusters(postingId),
    retry: false,
  })
  const runCluster = useMutation({
    mutationFn: () => clusterPosting(postingId),
    onSuccess: (result) => {
      queryClient.setQueryData(['clusters', postingId], result)
    },
  })

  return (
    <section aria-labelledby="clusters-heading" className="mb-6">
      <h3 id="clusters-heading" className="text-lg text-text-h">
        Responsibility clusters
      </h3>
      <p className={sectionBlurb}>
        Paraphrased JD bullets grouped by meaning — two sentences with no shared skill term can still
        describe the same responsibility.
      </p>
      <button
        type="button"
        onClick={() => runCluster.mutate()}
        disabled={runCluster.isPending}
        className="rounded border border-border px-3 py-1.5 disabled:cursor-default disabled:opacity-60"
      >
        {runCluster.isPending ? 'Clustering…' : clusters ? 'Re-cluster' : 'Cluster responsibilities'}
      </button>
      {runCluster.isError && <p role="alert">{(runCluster.error as Error).message}</p>}
      {isLoading && <p>Loading clusters…</p>}
      {clusters && clusters.length > 0 && (
        <ul className="mt-3 list-disc pl-5">
          {clusters.map((cluster) => (
            <li key={cluster.label}>
              <strong>{cluster.label}</strong>
              {cluster.phrases.length > 1 && (
                <ul className="my-1 list-disc pl-5 text-muted">
                  {cluster.phrases
                    .filter((phrase) => phrase !== cluster.label)
                    .map((phrase) => (
                      <li key={phrase}>{phrase}</li>
                    ))}
                </ul>
              )}
            </li>
          ))}
        </ul>
      )}
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
    <article>
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
      <UnrecognizedSection tokens={data.unrecognized} />
      {Number.isFinite(postingId) && <ClustersSection postingId={postingId} />}
    </article>
  )
}
