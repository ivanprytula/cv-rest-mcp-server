"""Repair extraction artifacts in job-description text before matching.

PDF and job-portal copy-paste introduce damage the skill matcher cannot see
past: a word split across a line break (``"Kuber-\\nnetes"``) never matches
``kubernetes``, and a non-breaking space between ``"Google"`` and ``"Cloud"``
is not the space the tokenizer expects.

Normalization runs before any matching, so every downstream consumer — the
tailor pipeline, gap analysis, ATS-fetched postings — sees repaired text.
"""

from __future__ import annotations

import re
import unicodedata


# Split-word repair: only letters flanking the hyphen, so a genuine trailing
# hyphen ("CI/CD -\nGitHub Actions") is left alone.
_HYPHEN_LINEBREAK = re.compile(r"(\w)-\n(\w)")

# Zero-width characters: joiners, non-joiners, BOM. Portal HTML is full of them.
_ZERO_WIDTH = re.compile(r"[​‌‍﻿]")

# Bullet glyphs that start list items; the matcher only needs a separator.
_BULLETS = re.compile(r"^[\s]*[•·▪◦‣∙⁃]+[\s]*", re.MULTILINE)

# Three or more newlines collapse to a paragraph break.
_BLANK_RUNS = re.compile(r"\n{3,}")


def normalize_jd_text(raw: str) -> str:
    """Return *raw* with extraction artifacts repaired.

    Applies, in order: NFKC folding (ligatures, smart quotes, full-width
    forms), split-word rejoining, zero-width removal, non-breaking-space
    flattening, bullet-glyph stripping, per-line trimming, and blank-run
    collapsing.

    Order matters: de-hyphenation needs the line break still present, so it
    must run before any whitespace collapsing.

    Args:
        raw: Text as extracted from a PDF, .docx, or portal paste.

    Returns:
        Normalized text. Idempotent — normalizing twice equals normalizing
        once.
    """
    text = unicodedata.normalize("NFKC", raw)
    text = _HYPHEN_LINEBREAK.sub(r"\1\2", text)
    text = _ZERO_WIDTH.sub("", text)
    # NFKC leaves NBSP (U+00A0) alone; it must become a real space.
    text = text.replace(" ", " ")
    text = _BULLETS.sub("", text)
    text = "\n".join(line.strip() for line in text.splitlines())
    text = _BLANK_RUNS.sub("\n\n", text)
    return text.strip()
