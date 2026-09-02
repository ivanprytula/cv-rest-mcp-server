from services.portfolio.renderer import _build_render_context, render_html


def test_render_html_renderer_owned_keys_override_cv_values(synthetic_cv):
    cv = {
        **synthetic_cv,
        "css": "payload CSS",
        "consent_enabled": True,
        "consent_company": "payload company",
    }

    html = render_html(cv, "renderer CSS", consent=False, consent_company="")

    assert "renderer CSS" in html
    assert "payload CSS" not in html
    assert "payload company" not in html


def test_render_context_preserves_harmless_extra_metadata(synthetic_cv):
    cv = {**synthetic_cv, "metadata": "harmless extra metadata"}

    context = _build_render_context(
        cv, "renderer CSS", consent=False, consent_company=""
    )

    assert context["metadata"] == "harmless extra metadata"
