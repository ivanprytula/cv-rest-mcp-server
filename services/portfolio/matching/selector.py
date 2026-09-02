"""Reorder CV skill categories so matched skills appear first (F-shaped reading)."""

from __future__ import annotations

from typing import Any

from services.portfolio.matching.taxonomy import normalize_skill


def _reorder_items(items: list[str], matched_norm: set[str]) -> list[str]:
    """Split items into matched-first order, preserving relative order within each group."""
    matched: list[str] = []
    unmatched: list[str] = []
    for item in items:
        if normalize_skill(item) in matched_norm:
            matched.append(item)
        else:
            unmatched.append(item)
    return matched + unmatched


def reorder_skills(
    skills: list[dict[str, Any]], matched_norm: set[str]
) -> list[dict[str, Any]]:
    """Return a new skills list with matched items sorted first in each category.

    Unmatched items are appended after matched ones, preserving the original
    relative order within each group.  Categories with no items after
    reordering are dropped.
    """
    result: list[dict[str, Any]] = []
    for cat in skills:
        reordered = _reorder_items(cat.get("items", []), matched_norm)
        if reordered:
            result.append({**cat, "items": reordered})
    return result


def reorder_skill_categories(
    categories: list[dict[str, Any]], matched_norm: set[str]
) -> list[dict[str, Any]]:
    """Reorder items within sub_categories of SkillCategory dicts.

    Each ``SkillCategory`` has ``sub_categories`` containing
    ``{"name": ..., "items": [...]}`` dicts.  Items are reordered so
    matched skills appear first within each sub-category.
    """
    result: list[dict[str, Any]] = []
    for cat in categories:
        new_subs: list[dict[str, Any]] = [
            {**sub, "items": _reorder_items(sub.get("items", []), matched_norm)}
            for sub in cat.get("sub_categories", [])
        ]
        if new_subs:
            result.append({**cat, "sub_categories": new_subs})
    return result
