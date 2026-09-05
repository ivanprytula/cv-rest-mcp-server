"""Skill freshness: `last_used` / `confidence` and the `stale` tier.

`level` is depth-at-peak, not readiness today. A skill used for one month a
year ago is `basic` and sits in `skills[]`, so tailoring puts it in front of
a recruiter — while refreshing it costs nearly as much as learning something
new. These tests pin that distinction.
"""

from datetime import date

from services.portfolio.matching.baseline import (
    STALE_AFTER_MONTHS,
    is_stale,
)
from services.portfolio.matching.gap import detect_gaps


TODAY = date(2026, 9, 5)


def _atom(name, **extra):
    return {
        "atom": name,
        "group_id": "backend",
        "level": "basic",
        "priority": "low",
        "category_hint": "Backend development > languages",
        **extra,
    }


class TestIsStale:
    def test_atom_without_metadata_is_current(self):
        # Guessing would flag the entire existing bank.
        assert is_stale(_atom("Python"), today=TODAY) is False

    def test_recent_last_used_is_current(self):
        assert is_stale(_atom("Python", last_used="2026-06"), today=TODAY) is False

    def test_old_last_used_is_stale(self):
        assert is_stale(_atom("OpenSearch", last_used="2024-01"), today=TODAY) is True

    def test_year_only_last_used_is_accepted(self):
        assert is_stale(_atom("OpenSearch", last_used="2023"), today=TODAY) is True

    def test_boundary_is_not_stale(self):
        months = STALE_AFTER_MONTHS
        year, month = TODAY.year, TODAY.month - months
        while month <= 0:
            year, month = year - 1, month + 12
        assert (
            is_stale(_atom("X", last_used=f"{year}-{month:02d}"), today=TODAY) is False
        )


class TestConfidenceOverrides:
    """Decay is not uniform: SQL keeps, Kubernetes does not."""

    def test_confidence_current_beats_old_date(self):
        atom = _atom("SQL", last_used="2019", confidence="current")
        assert is_stale(atom, today=TODAY) is False

    def test_needs_refresh_beats_recent_date(self):
        atom = _atom("Kubernetes", last_used="2026-08", confidence="needs_refresh")
        assert is_stale(atom, today=TODAY) is True


class TestStaleTier:
    LIVE_CV = {
        "skills": [
            {
                "category": "Backend development",
                "sub_categories": [
                    {"name": "languages", "items": ["Python", "OpenSearch"]}
                ],
            }
        ]
    }

    def _report(self, bank):
        return detect_gaps("We need Python and OpenSearch.", bank, [], [], self.LIVE_CV)

    def test_stale_cv_skill_lands_in_stale_not_covered(self):
        bank = [_atom("Python"), _atom("OpenSearch", confidence="needs_refresh")]
        report = self._report(bank)
        assert [g.term for g in report.by_tier("covered")] == ["Python"]
        assert [g.term for g in report.by_tier("stale")] == ["OpenSearch"]

    def test_stale_skills_are_reported_as_interview_risks(self):
        bank = [_atom("Python"), _atom("OpenSearch", confidence="needs_refresh")]
        assert [g.term for g in self._report(bank).interview_risks] == ["OpenSearch"]

    def test_coverage_excludes_stale_skills(self):
        bank = [_atom("Python"), _atom("OpenSearch", confidence="needs_refresh")]
        # Two requirements, one genuinely defensible.
        assert self._report(bank).coverage == 0.5

    def test_fresh_bank_still_fully_covers(self):
        bank = [_atom("Python"), _atom("OpenSearch")]
        assert self._report(bank).coverage == 1.0

    def test_partition_still_holds_with_five_tiers(self):
        from services.portfolio.matching.gap import TIERS

        bank = [_atom("Python"), _atom("OpenSearch", confidence="needs_refresh")]
        report = self._report(bank)
        counted = sum(len(report.by_tier(t)) for t in TIERS)
        assert counted == len(report.gaps)
