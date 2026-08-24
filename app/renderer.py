from jinja2 import Environment, FileSystemLoader

from app.constants import TEMPLATE_DIR


def get_env() -> Environment:
    loader = FileSystemLoader(str(TEMPLATE_DIR))
    return Environment(loader=loader, autoescape=True)


_ENV = get_env()


def render_html(
    cv: dict, css: str, *, consent: bool = False, consent_company: str = ""
) -> str:
    template = _ENV.get_template("cv_base.html")
    return template.render(
        css=css,
        consent_enabled=consent,
        consent_company=consent_company,
        **cv,
    )


def render_template(name: str, **context) -> str:
    template = _ENV.get_template(name)
    return template.render(**context)
