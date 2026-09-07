import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import TierBadge from './TierBadge'

describe('TierBadge', () => {
  it.each(['covered', 'stale', 'unvouched', 'deferred', 'unknown'])(
    'renders the %s tier with its own background/text classes',
    (tier) => {
      render(<TierBadge tier={tier} label="Label" />)
      const badge = screen.getByText('Label')
      expect(badge.className).toContain(`bg-tier-${tier}-bg`)
      expect(badge.className).toContain(`text-tier-${tier}-text`)
    },
  )

  it('falls back to a neutral style for an unrecognized tier', () => {
    render(<TierBadge tier="not-a-real-tier" label="Mystery" />)
    const badge = screen.getByText('Mystery')
    expect(badge.className).toContain('bg-surface')
    expect(badge.className).toContain('text-text')
  })

  it('renders the given label text', () => {
    render(<TierBadge tier="unknown" label="Learn" />)
    expect(screen.getByText('Learn')).toBeInTheDocument()
  })
})
