"""Tests for the four-tier JD gap model."""

import re

import pytest

from services.portfolio.matching.gap import (
    TIERS,
    GapReport,
    detect_gaps,
    load_vocabulary,
)
from services.portfolio.settings import settings


def _atom(name, group="backend", level="middle", **extra):
    return {
        "atom": name,
        "group_id": group,
        "level": level,
        "priority": "high",
        "category_hint": "Backend development > languages",
        **extra,
    }


BANK = [_atom("Python"), _atom("Kubernetes"), _atom("Terraform")]
DEFERRED = [_atom("GraphQL", level="basic", _note="Promote if a role needs it")]
VOCAB = [
    {"atom": "Kafka", "group_id": "messaging", "aliases": ["apache kafka"]},
    {"atom": "Python", "group_id": "backend", "aliases": []},
]
# The live CV claims Python only — Kubernetes and Terraform are bank-only.
LIVE_CV = {
    "skills": [
        {
            "category": "Backend development",
            "sub_categories": [{"name": "languages", "items": ["Python"]}],
        }
    ]
}


def _report(jd_text):
    return detect_gaps(jd_text, BANK, DEFERRED, VOCAB, LIVE_CV)


class TestTierAssignment:
    def test_live_cv_skill_is_covered(self):
        gaps = _report("We need Python.").by_tier("covered")
        assert [g.term for g in gaps] == ["Python"]

    def test_bank_skill_absent_from_cv_is_unvouched(self):
        gaps = _report("We need Kubernetes.").by_tier("unvouched")
        assert [g.term for g in gaps] == ["Kubernetes"]

    def test_deferred_atom_is_deferred_and_carries_note(self):
        (gap,) = _report("We need GraphQL.").by_tier("deferred")
        assert gap.term == "GraphQL"
        assert gap.note == "Promote if a role needs it"

    def test_vocabulary_only_term_is_unknown(self):
        gaps = _report("We need Kafka.").by_tier("unknown")
        assert [g.term for g in gaps] == ["Kafka"]

    def test_bank_membership_outranks_vocabulary(self):
        # "Python" is in both VOCAB and BANK; the bank (and live CV) wins.
        (gap,) = _report("We need Python.").gaps
        assert gap.tier == "covered"

    def test_alias_resolves_to_canonical_term(self):
        gaps = _report("Experience with Apache Kafka required.").gaps
        assert [g.term for g in gaps] == ["Kafka"]


class TestPartitionInvariant:
    JD = "We need Python, Kubernetes, Terraform, GraphQL and Kafka."

    def test_every_gap_lands_in_exactly_one_tier(self):
        report = _report(self.JD)
        counted = sum(len(report.by_tier(tier)) for tier in TIERS)
        assert counted == len(report.gaps)

    def test_terms_are_unique(self):
        terms = [g.term for g in _report(self.JD).gaps]
        assert len(terms) == len(set(terms))

    def test_tiers_are_disjoint(self):
        report = _report(self.JD)
        seen = [{g.term for g in report.by_tier(t)} for t in TIERS]
        for i, first in enumerate(seen):
            for second in seen[i + 1 :]:
                assert not (first & second)

    def test_gaps_sorted_by_tier_then_name(self):
        gaps = _report(self.JD).gaps
        keys = [(TIERS.index(g.tier), g.term.lower()) for g in gaps]
        assert keys == sorted(keys)


class TestDeterminism:
    def test_same_input_yields_identical_output(self):
        jd = "Python, Kubernetes and Kafka experience required."
        assert _report(jd) == _report(jd)

    def test_unmatched_jd_yields_no_gaps(self):
        assert _report("We value teamwork and clear communication.").gaps == ()


class TestQualifiers:
    """Levels come from the parser's prepositional qualifier heads.

    Bare adjectives ("expert Kubernetes") are deliberately not qualifiers —
    only phrases like "5+ years of X" or "familiarity with X" are.
    """

    def test_years_imply_expert(self):
        (gap,) = _report("5+ years of experience with Kubernetes.").gaps
        assert gap.required_level == "expert"

    def test_familiarity_implies_basic(self):
        (gap,) = _report("Familiarity with Kubernetes.").gaps
        assert gap.required_level == "basic"

    def test_strongest_mention_wins_regardless_of_order(self):
        weak_first = _report(
            "Familiarity with Kubernetes. 5+ years of experience with Kubernetes."
        )
        strong_first = _report(
            "5+ years of experience with Kubernetes. Familiarity with Kubernetes."
        )
        assert weak_first.gaps[0].required_level == "expert"
        assert strong_first.gaps[0].required_level == "expert"

    def test_evidence_is_recorded(self):
        (gap,) = _report("Familiarity with Kubernetes.").gaps
        assert "kubernetes" in gap.evidence.lower()


class TestCoverage:
    def test_empty_report_is_fully_covered(self):
        assert GapReport(gaps=()).coverage == 1.0

    def test_coverage_is_share_of_covered_tier(self):
        # Python covered; Kubernetes + Kafka are not.
        assert _report("Python, Kubernetes, Kafka.").coverage == pytest.approx(1 / 3)


class TestVocabularyFile:
    """The shipped vocabulary must stay loadable and matchable."""

    def test_loads_and_is_atom_shaped(self):
        vocab = load_vocabulary(settings.jd_vocabulary_path)
        assert vocab
        assert all("atom" in entry and "group_id" in entry for entry in vocab)

    def test_no_term_contains_phrase_breaking_punctuation(self):
        # parser._skills_in_chunk skips multi-word keys containing these, so
        # such a term would silently never match inside a qualifier window.
        vocab = load_vocabulary(settings.jd_vocabulary_path)
        offenders = [
            entry["atom"]
            for entry in vocab
            if " " in entry["atom"] and re.search(r"[,.:–—]", entry["atom"])
        ]
        assert offenders == []
