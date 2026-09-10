"""Job-posting intake: format detection and text normalization."""

from io import BytesIO

import docx
import pytest
from weasyprint import HTML

from services.portfolio.job_posting_input import (
    MAX_POSTING_PAYLOAD_BYTES,
    parse_job_posting_input,
)


JD_TEXT = "Required: Python, FastAPI, PostgreSQL"


def build_pdf_bytes(text: str = JD_TEXT) -> bytes:
    html = f"<html><body><p>{text}</p></body></html>"
    return HTML(string=html).write_pdf()


def build_docx_bytes(text: str = JD_TEXT) -> bytes:
    document = docx.Document()
    document.add_paragraph(text)
    buffer = BytesIO()
    document.save(buffer)
    return buffer.getvalue()


# --- raw text / txt / markdown -------------------------------------------------


def test_raw_text_default():
    jd = parse_job_posting_input(b"The Role\n\nTake ownership", "text/plain")
    assert jd.posting_text == "The Role\n\nTake ownership"
    assert jd.title == ""


def test_txt_explicit_content_type():
    jd = parse_job_posting_input(JD_TEXT.encode(), "text/plain")
    assert jd.posting_text == JD_TEXT


def test_markdown_content_type():
    md = "# The Role\n\nNeed **Python** and `FastAPI` skills\n- Kafka\n"
    jd = parse_job_posting_input(md.encode(), "text/markdown")
    assert jd.posting_text == md.strip()


def test_markdown_x_content_type():
    jd = parse_job_posting_input(b"# Job\nPython", "text/x-markdown")
    assert "Python" in jd.posting_text


def test_raw_text_with_query_title():
    jd = parse_job_posting_input(b"Python dev", "text/plain", title="Senior Python Dev")
    assert jd.posting_text == "Python dev"
    assert jd.title == "Senior Python Dev"


def test_unhandled_content_type_falls_back_to_text():
    jd = parse_job_posting_input(b"open xml body", "application/octet-stream")
    assert jd.posting_text == "open xml body"


def test_empty_body_raw_text():
    jd = parse_job_posting_input(b"", "text/plain")
    assert jd.posting_text == ""


# --- json ---------------------------------------------------------------------


def test_json_valid():
    jd = parse_job_posting_input(
        b'{"posting_text": "Required: Python", "title": ""}',
        "application/json",
    )
    assert jd.posting_text == "Required: Python"
    assert jd.title == ""


def test_json_with_embedded_title_prefers_payload():
    jd = parse_job_posting_input(
        b'{"posting_text": "Python", "title": "From JSON"}',
        "application/json",
        title="From Query",
    )
    assert jd.title == "From JSON"


def test_json_with_query_title_when_payload_title_empty():
    jd = parse_job_posting_input(
        b'{"posting_text": "Python", "title": ""}',
        "application/json",
        title="From Query",
    )
    assert jd.title == "From Query"


def test_json_invalid_raises_value_error():
    with pytest.raises(ValueError, match="posting_text"):
        parse_job_posting_input(b'{"foo": "bar"}', "application/json")


def test_json_media_type_with_parameters():
    jd = parse_job_posting_input(
        b'{"posting_text": "Python"}',
        "application/json; charset=utf-8",
    )
    assert jd.posting_text == "Python"


# --- pdf ----------------------------------------------------------------------


def test_pdf_content_type_extracts_text():
    jd = parse_job_posting_input(build_pdf_bytes(), "application/pdf")
    assert "Python" in jd.posting_text
    assert "FastAPI" in jd.posting_text


def test_pdf_sniffed_from_octet_stream():
    jd = parse_job_posting_input(build_pdf_bytes(), "application/octet-stream")
    assert "FastAPI" in jd.posting_text


def test_pdf_sniffed_from_empty_content_type():
    jd = parse_job_posting_input(build_pdf_bytes(), "")
    assert "FastAPI" in jd.posting_text


def test_corrupt_pdf_raises_value_error():
    with pytest.raises(ValueError, match="PDF"):
        parse_job_posting_input(b"%PDF this is not a real pdf", "application/pdf")


# --- docx ---------------------------------------------------------------------


def test_docx_content_type_extracts_text():
    jd = parse_job_posting_input(build_docx_bytes(), _docx_media_type())
    assert "FastAPI" in jd.posting_text


def test_docx_sniffed_from_octet_stream():
    jd = parse_job_posting_input(build_docx_bytes(), "application/octet-stream")
    assert "PostgreSQL" in jd.posting_text


def test_corrupt_docx_raises_value_error():
    with pytest.raises(ValueError, match="docx"):
        parse_job_posting_input(b"PK\x03\x04 not a real docx", _docx_media_type())


# --- size cap -----------------------------------------------------------------


def test_oversized_payload_rejected():
    big = b"x" * (MAX_POSTING_PAYLOAD_BYTES + 1)
    with pytest.raises(ValueError, match="5 MB"):
        parse_job_posting_input(big, "text/plain")


def test_oversized_json_rejected():
    huge_jd = {"posting_text": "y" * (MAX_POSTING_PAYLOAD_BYTES + 1)}
    body = f'{{"posting_text": "{huge_jd["posting_text"]}"}}'.encode()
    with pytest.raises(ValueError, match="5 MB"):
        parse_job_posting_input(body, "application/json")


def _docx_media_type() -> str:
    return "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
