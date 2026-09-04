"""Tests for JD text normalization."""

import hypothesis.strategies as st
from hypothesis import given

from services.portfolio.matching.normalize import normalize_jd_text


class TestSplitWordRepair:
    def test_rejoins_word_split_across_lines(self):
        assert "kubernetes" in normalize_jd_text("We use Kuber-\nnetes daily").lower()

    def test_keeps_trailing_hyphen_when_not_intraword(self):
        # A dash ending a line is punctuation, not a split word.
        assert "-\nGitHub" in normalize_jd_text("CI/CD -\nGitHub Actions")

    def test_preserves_genuine_hyphenated_terms(self):
        assert "end-to-end" in normalize_jd_text("end-to-end testing")


class TestInvisibleCharacters:
    def test_non_breaking_space_becomes_plain_space(self):
        assert normalize_jd_text("Google Cloud") == "Google Cloud"

    def test_zero_width_characters_removed(self):
        assert normalize_jd_text("Post​greSQL") == "PostgreSQL"

    def test_nfkc_folds_ligatures(self):
        assert normalize_jd_text("ﬁrst") == "first"

    def test_nfkc_folds_full_width_forms(self):
        assert normalize_jd_text("Ｐｙｔｈｏｎ") == "Python"

    def test_smart_quotes_survive(self):
        # NFKC leaves curly quotes alone, and that is fine: the matcher
        # tokenizes on word boundaries, so quoting never blocks a match.
        assert normalize_jd_text("“DevOps”") == "“DevOps”"


class TestLayout:
    def test_bullet_glyphs_stripped(self):
        assert normalize_jd_text("• Python\n• Django") == "Python\nDjango"

    def test_blank_runs_collapse_to_one_break(self):
        assert (
            normalize_jd_text("Requirements\n\n\n\nPython") == "Requirements\n\nPython"
        )

    def test_lines_are_trimmed(self):
        assert normalize_jd_text("   Python   \n   Django  ") == "Python\nDjango"


class TestProperties:
    @given(raw=st.text(max_size=300))
    def test_is_idempotent(self, raw):
        once = normalize_jd_text(raw)
        assert normalize_jd_text(once) == once

    @given(raw=st.text(max_size=300))
    def test_never_raises_and_returns_str(self, raw):
        assert isinstance(normalize_jd_text(raw), str)
