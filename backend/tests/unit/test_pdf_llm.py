"""Groq PDF extraction with a fake client: JSON parsing, number check, failure handling.
No network calls."""

import io
import json
from types import SimpleNamespace

import pytest

from app.ai import pdf_llm
from app.core import config


def text_pdf(lines: list[str]) -> bytes:
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas

    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    y = 800
    for line in lines:
        c.drawString(40, y, line)
        y -= 16
    c.save()
    return buf.getvalue()


class FakeClient:
    def __init__(self, payload: str) -> None:
        self.payload = payload
        self.calls: list[dict] = []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.create))

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=self.payload))]
        )


PDF = text_pdf(
    [
        "Inspection report (demo)   Part DC-101   Serial 0457   Machine VMC-02",
        "C-03  Bearing bore  nominal 72.000  tolerance +0.030 / 0.000  actual 72.034",
        "C-01  Pinion bore   nominal 48.000  tolerance +0.025 / 0.000  actual 48.010",
    ]
)


@pytest.fixture(autouse=True)
def ai_on(monkeypatch):
    monkeypatch.setenv("AI_ENABLED", "true")
    config.get_settings.cache_clear()
    yield
    monkeypatch.delenv("AI_ENABLED", raising=False)
    config.get_settings.cache_clear()


def test_rows_parsed_and_checked_against_pdf_text():
    payload = {
        "part_no": "DC-101",
        "serial_no": "0457",
        "machine_code": "VMC-02",
        "measured_at": None,
        "rows": [
            {
                "char_no": "C-03",
                "char_name": "Bearing bore",
                "actual": "72.034",
                "nominal": "72.000",
                "upper_tol": "0.030",
                "lower_tol": "0.000",
                "usl": None,
                "lsl": None,
            },
            {
                "char_no": "C-01",
                "char_name": "Pinion bore",
                "actual": "48.011",
                "nominal": "48.000",
                "upper_tol": "0.025",
                "lower_tol": "0.000",
                "usl": None,
                "lsl": None,
            },
        ],
    }
    client = FakeClient(json.dumps(payload))
    out = pdf_llm.extract_rows(PDF, client=client)
    assert out["provider"] == "groq"
    assert out["part_no"] == "DC-101"
    by = {r["char_no"]: r for r in out["rows"]}
    assert by["C-03"]["found_in_pdf"] is True
    assert by["C-01"]["found_in_pdf"] is False  # 48.011 is not in the PDF: model mistake flagged
    call = client.calls[0]
    assert call["temperature"] == 0
    assert call["response_format"] == {"type": "json_object"}
    assert "72.034" in call["messages"][1]["content"]


def test_bad_json_is_reported_not_guessed():
    with pytest.raises(pdf_llm.AiUnavailable, match="expected format"):
        pdf_llm.extract_rows(PDF, client=FakeClient("not json"))


def test_scanned_pdf_without_text_is_refused():
    from reportlab.pdfgen import canvas

    buf = io.BytesIO()
    canvas.Canvas(buf).save()
    with pytest.raises(pdf_llm.AiUnavailable, match="no text layer"):
        pdf_llm.extract_rows(buf.getvalue(), client=FakeClient("{}"))


def test_disabled_ai_never_builds_a_client(monkeypatch):
    monkeypatch.setenv("AI_ENABLED", "false")
    config.get_settings.cache_clear()
    with pytest.raises(pdf_llm.AiUnavailable, match="disabled"):
        pdf_llm._client()
