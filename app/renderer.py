from __future__ import annotations

from typing import Any

from jinja2 import Environment, FileSystemLoader

from app.constants import TEMPLATE_DIR


_RENDERER_OWNED_KEYS = frozenset({"css", "consent_enabled", "consent_company"})


def _flatten_skills(skills: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Flatten SkillCategory with sub_categories into flat display list.

    Each SkillCategory becomes ``{"category": name, "items": [...]}`` with
    all sub-category items merged in order.  Categories that produce no
    items after flattening are dropped.
    """
    flat: list[dict[str, Any]] = []
    for cat in skills:
        parts: list[str] = []
        for sub in cat.get("sub_categories", []):
            if sub.get("items"):
                parts.extend(sub["items"])
        if parts:
            flat.append({"category": cat.get("name", ""), "items": parts})
    return flat


def get_env() -> Environment:
    loader = FileSystemLoader(str(TEMPLATE_DIR))
    return Environment(loader=loader, autoescape=True)


_ENV = get_env()


def _build_render_context(
    cv: dict, css: str, *, consent: bool, consent_company: str
) -> dict:
    context = {
        key: value for key, value in cv.items() if key not in _RENDERER_OWNED_KEYS
    }
    context["flat_skills"] = _flatten_skills(context.get("skills", []))
    context["flat_additional_skills"] = _flatten_skills(
        context.get("additional_skills", [])
    )
    context.update(
        css=css,
        consent_enabled=consent,
        consent_company=consent_company,
    )
    return context


def render_html(
    cv: dict, css: str, *, consent: bool = False, consent_company: str = ""
) -> str:
    template = _ENV.get_template("cv_base.html")
    return template.render(
        **_build_render_context(
            cv, css, consent=consent, consent_company=consent_company
        )
    )


def render_template(name: str, **context) -> str:
    template = _ENV.get_template(name)
    return template.render(**context)
