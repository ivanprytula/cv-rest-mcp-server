// Fixed status-color pairs (matching-gap.py's TIERS), independent of the
// selected accent palette. Tailwind can't build `bg-tier-${tier}-bg` from a
// template string at compile time (it needs literal class names to scan),
// so each tier's full class combination is listed explicitly.
const TIER_CLASSES: Record<string, string> = {
  covered: 'bg-tier-covered-bg text-tier-covered-text',
  stale: 'bg-tier-stale-bg text-tier-stale-text',
  unvouched: 'bg-tier-unvouched-bg text-tier-unvouched-text',
  deferred: 'bg-tier-deferred-bg text-tier-deferred-text',
  unknown: 'bg-tier-unknown-bg text-tier-unknown-text',
}

export default function TierBadge({ tier, label }: { tier: string; label: string }) {
  const classes = TIER_CLASSES[tier] ?? 'bg-surface text-text'
  return (
    <span className={`inline-block rounded-full px-2 py-0.5 text-sm whitespace-nowrap ${classes}`}>
      {label}
    </span>
  )
}
