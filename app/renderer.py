from jinja2 import Environment, FileSystemLoader

from app.constants import TEMPLATE_DIR


_RENDERER_OWNED_KEYS = frozenset({"css", "consent_enabled", "consent_company"})


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
