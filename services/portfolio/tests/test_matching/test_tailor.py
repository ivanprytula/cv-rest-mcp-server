"""Tests for app.matching.tailor (bank-driven tailoring)."""

import copy
import logging

from services.portfolio.matching.tailor import company_slug, extract_company, tailor_cv


# A test-owned bank. Only atoms whose canonical form appears on LIVE_CV get
# past the trust policy (Kafka, Docker is vouched, X-Ray is not, ...
# deliberately DRF has no vouched twin).
BASELINE_ATOMS = [
    {
        "atom": "Python",
        "group_id": "backend",
        "level": "expert",
        "priority": "high",
        "category_hint": "Backend development > languages",
    },
    {
        "atom": "FastAPI",
        "group_id": "backend",
        "level": "expert",
        "priority": "high",
        "category_hint": "Backend development > frameworks",
    },
    {
        "atom": "PostgreSQL",
        "group_id": "databases",
        "level": "middle",
        "priority": "medium",
        "category_hint": "Databases and data processing > datastores",
    },
    {
        "atom": "Redis",
        "group_id": "databases",
        "level": "basic",
        "priority": "low",
        "category_hint": "Databases and data processing > datastores",
    },
    {
        "atom": "Docker",
        "group_id": "infra",
        "level": "expert",
        "priority": "high",
        "category_hint": "Additional skills > tools",
    },
    {
        "atom": "Kafka",
        "group_id": "streaming",
        "level": "expert",
        "priority": "high",
        "category_hint": "Databases and data processing > datastores",
    },
    {
        "atom": "Claude Code",
        "group_id": "ai-coding",
        "level": "expert",
        "priority": "high",
        "category_hint": "AI integrations > tools",
        "aliases": ["claude code cli"],
    },
    {
        "atom": "Cron",
        "group_id": "backend",
        "level": "basic",
        "priority": "low",
        "category_hint": "Backend development > tools",
    },
]

LIVE_CV = {
    "name": "Jane Doe",
    "title": "Backend Engineer",
    "summary": "Vouched summary.",
    "skills": [
        {
            "name": "Backend development",
            "sub_categories": [
                {"name": "languages", "items": ["Python 3.14+"]},
                {"name": "frameworks", "items": ["FastAPI", "Django"]},
                {"name": "tools", "items": ["Cron"]},
            ],
        },
        {
            "name": "Databases and data processing",
            "sub_categories": [
                {"name": "datastores", "items": ["PostgreSQL", "Redis"]},
            ],
        },
        {
            "name": "AI integrations",
            "sub_categories": [
                {"name": "tools", "items": ["Claude Code"]},
            ],
        },
    ],
    "additional_skills": [
        {
            "name": "Additional skills",
            "sub_categories": [{"name": "tools", "items": ["Docker"]}],
        },
    ],
    "experience": [
        {
            "role": "Developer",
            "company": "Acme",
            "period": "2023 - 2024",
            "highlights": ["Built things"],
            "tech": ["Python", "FastAPI"],
        },
    ],
    "languages": ["English"],
}


def _items(tailored: dict) -> list[str]:
    """Flatten every skill item across skills + additional_skills."""
    out = []
    for section in ("skills", "additional_skills"):
        for cat in tailored.get(section, []):
            for sub in cat.get("sub_categories", []):
                out.extend(sub.get("items", []))
    return out


class TestCompanySlug:
    def test_simple(self):
        assert company_slug("EPC Network") == "epc_network"

    def test_single_word(self):
        assert company_slug("Litslink") == "litslink"

    def test_special_chars(self):
        assert company_slug("Acme & Co.") == "acme_co"

    def test_unicode(self):
        assert company_slug("Münchener") == "munchener"


class TestExtractCompany:
    def test_work_at_pattern(self):
        jd = "Work at EPC Network building backend services."
        assert extract_company(jd) == "EPC Network"

    def test_company_label(self):
        jd = "Company: Litslink\nWe are hiring..."
        assert extract_company(jd) == "Litslink"

    def test_no_company(self):
        jd = "Looking for a Python developer."
        assert extract_company(jd) == ""

    def test_empty(self):
        assert extract_company("") == ""


class TestTailorCv:
    def test_rebuilds_skills_from_matched_atoms(self):
        jd = "Required: Python, FastAPI, PostgreSQL"
        tailored = tailor_cv(jd, BASELINE_ATOMS, LIVE_CV)
        items = _items(tailored)
        assert "Python" in items
        assert "FastAPI" in items
        assert "PostgreSQL" in items
        # Atom names come from the bank (not the live CV's "Python 3.14+").
        assert "Python 3.14+" not in items

    def test_skips_bank_atoms_not_in_jd(self):
        tailored = tailor_cv("Required: Python", BASELINE_ATOMS, LIVE_CV)
        assert "FastAPI" not in _items(tailored)
        assert "PostgreSQL" not in _items(tailored)

    def test_groups_by_category_hint(self):
        jd = "Required: Python, FastAPI, PostgreSQL, Redis"
        tailored = tailor_cv(jd, BASELINE_ATOMS, LIVE_CV)
        cats = {c["name"]: c for c in tailored["skills"]}
        assert "Backend development" in cats
        subs = {
            s["name"]: s["items"] for s in cats["Backend development"]["sub_categories"]
        }
        assert "languages" in subs and "frameworks" in subs
        assert "Python" in subs["languages"]
        assert "FastAPI" in subs["frameworks"]

    def test_additional_skills_group_lands_in_additional_section(self):
        tailored = tailor_cv("Required: Docker", BASELINE_ATOMS, LIVE_CV)
        assert tailored["skills"] == []
        add = tailored["additional_skills"]
        assert [i for c in add for s in c["sub_categories"] for i in s["items"]] == [
            "Docker"
        ]

    def test_level_filter_drops_basic_atom_for_expert_requirement(self):
        # Redis is basic in the bank; "Solid experience" demands expert.
        tailored = tailor_cv("Solid experience with Redis.", BASELINE_ATOMS, LIVE_CV)
        assert "Redis" not in _items(tailored)

    def test_level_filter_drops_middle_atom_for_expert_requirement(self):
        # PostgreSQL is middle; "Production experience" demands expert.
        tailored = tailor_cv(
            "Production experience with PostgreSQL.", BASELINE_ATOMS, LIVE_CV
        )
        assert "PostgreSQL" not in _items(tailored)

    def test_accepts_higher_or_equal_level(self):
        # FastAPI is expert; "Experience with" (middle) is satisfied.
        tailored = tailor_cv("Experience with FastAPI.", BASELINE_ATOMS, LIVE_CV)
        assert "FastAPI" in _items(tailored)

    def test_unqualified_mention_imposes_no_constraint(self):
        # No qualifier → "no constraint": even the basic Redis atom qualifies.
        tailored = tailor_cv("Redis.", BASELINE_ATOMS, LIVE_CV)
        assert "Redis" in _items(tailored)

    def test_trust_policy_drops_atom_not_on_live_cv(self, caplog):
        # Kafka is expert in the bank but nowhere on LIVE_CV — must vanish,
        # with a warning naming the dropped atom.
        with caplog.at_level(
            logging.WARNING, logger="services.portfolio.matching.tailor"
        ):
            tailored = tailor_cv(
                "Solid experience with Kafka.", BASELINE_ATOMS, LIVE_CV
            )
        assert "Kafka" not in _items(tailored)
        assert "Kafka" in caplog.text

    def test_alias_header_resolves_to_atom(self):
        # Bank alias "claude code cli" → atom "Claude Code"; the JD uses the
        # alias form, which must resolve through the mention pipeline to the
        # atom (expert level, vouched on LIVE_CV) — so it lands in the output.
        tailored = tailor_cv(
            "Solid experience with Claude Code CLI.", BASELINE_ATOMS, LIVE_CV
        )
        assert "Claude Code" in _items(tailored)

    def test_priority_ordering_within_group(self):
        # Both vouched: Python (high) and Cron (low), grouped in Backend development.
        tailored = tailor_cv("Required: Python, Cron", BASELINE_ATOMS, LIVE_CV)
        backend = next(
            c for c in tailored["skills"] if c["name"] == "Backend development"
        )
        flattened = [item for sub in backend["sub_categories"] for item in sub["items"]]
        # Python (high) must appear before Cron (low).
        assert flattened.index("Python") < flattened.index("Cron")

    def test_language_sub_category_precedes_frameworks(self):
        # The JD lists FastAPI first, but the live CV's canonical order keeps
        # "languages" before "frameworks" — Python is the headline skill.
        tailored = tailor_cv("Required: FastAPI, Python", BASELINE_ATOMS, LIVE_CV)
        backend = next(
            c for c in tailored["skills"] if c["name"] == "Backend development"
        )
        subs = [s["name"] for s in backend["sub_categories"]]
        assert subs == ["languages", "frameworks"]
        flattened = [item for sub in backend["sub_categories"] for item in sub["items"]]
        assert flattened.index("Python") < flattened.index("FastAPI")

    def test_groups_follow_live_cv_order_not_priority(self):
        # Claude Code (AI integrations, high priority) vs PostgreSQL (Databases,
        # medium): the live CV lists Databases before AI integrations, so the
        # tailored output must too — even though priority would flip them.
        jd = "Required: PostgreSQL. Solid experience with Claude Code CLI."
        tailored = tailor_cv(jd, BASELINE_ATOMS, LIVE_CV)
        assert [c["name"] for c in tailored["skills"]] == [
            "Databases and data processing",
            "AI integrations",
        ]

    def test_passes_through_nonskill_sections(self):
        tailored = tailor_cv("Required: Python", BASELINE_ATOMS, LIVE_CV)
        assert tailored["name"] == "Jane Doe"
        assert tailored["summary"] == "Vouched summary."
        assert tailored["experience"] == LIVE_CV["experience"]
        assert tailored["languages"] == ["English"]

    def test_title_override(self):
        tailored = tailor_cv(
            "Python", BASELINE_ATOMS, LIVE_CV, title="Senior Python Dev"
        )
        assert tailored["title"] == "Senior Python Dev"

    def test_empty_jd_rebuilds_empty_skills(self):
        tailored = tailor_cv("", BASELINE_ATOMS, LIVE_CV)
        assert tailored["skills"] == []
        assert tailored["additional_skills"] == []

    def test_fuzzy_typo_still_matches_atom(self):
        # "Pyton" is a typo; fuzzy fallback resolves it to Python (no qualifier,
        # so the expert atom is accepted) and the trust policy lets it through.
        tailored = tailor_cv("Required: Pyton", BASELINE_ATOMS, LIVE_CV)
        assert "Python" in _items(tailored)

    def test_does_not_mutate_live_cv(self):
        original = copy.deepcopy(LIVE_CV)
        tailor_cv("Required: Python, FastAPI", BASELINE_ATOMS, LIVE_CV)
        assert LIVE_CV == original

    def test_does_not_mutate_baseline_atoms(self):
        original = copy.deepcopy(BASELINE_ATOMS)
        tailor_cv("Required: Python", BASELINE_ATOMS, LIVE_CV)
        assert BASELINE_ATOMS == original
