"""AI-assisted PDF extraction via Groq (Section 19, COULD). Runs only when AI_ENABLED=true.

Used only after deterministic pdfplumber table extraction has failed (messy layouts, text in
odd columns). Steps:
1. Read the PDF's text layer locally (pdfplumber). Scanned images without text are refused:
   OCR is out of scope, and we never send images we cannot check.
2. Send the text to a Groq-hosted model and ask for JSON rows in the RawRecord shape.
3. Check every returned number against the PDF text; a value that does not appear verbatim is
   flagged `found_in_pdf: false`, so a model mistake is visible to the person confirming.
The report is stored as NEEDS_CONFIRMATION; only rows a person confirms are classified. The AI
never decides OK / Not OK and never alerts.
"""

import io
import json
import logging
import re
from typing import Any

from pydantic import BaseModel, ValidationError

from app.core.config import get_settings

logger = logging.getLogger(__name__)

# Configurable with AI_MODEL; pick any JSON-capable model listed in your Groq console.
DEFAULT_MODEL = "llama-3.3-70b-versatile"
MAX_TEXT_CHARS = 60_000

SYSTEM_PROMPT = """You extract data from coordinate measuring machine (CMM) inspection reports.
Return ONE JSON object with exactly these keys:
{"part_no": string|null, "serial_no": string|null, "machine_code": string|null,
 "measured_at": string|null,
 "rows": [{"char_no": string, "char_name": string|null, "actual": string,
           "nominal": string|null, "upper_tol": string|null, "lower_tol": string|null,
           "usl": string|null, "lsl": string|null}]}
Rules: one row per measured characteristic. Copy every number exactly as printed (same digits,
same decimal separator); never round, convert, compute or judge. Use null for anything the report
does not show. Never invent rows. A person checks every row against the PDF before it is used."""


class AiUnavailable(Exception):
    pass


class ExtractedRow(BaseModel):
    char_no: str
    char_name: str | None = None
    actual: str
    nominal: str | None = None
    upper_tol: str | None = None
    lower_tol: str | None = None
    usl: str | None = None
    lsl: str | None = None


class Extraction(BaseModel):
    part_no: str | None = None
    serial_no: str | None = None
    machine_code: str | None = None
    measured_at: str | None = None
    rows: list[ExtractedRow]


def pdf_text(pdf_bytes: bytes) -> str:
    import pdfplumber

    try:
        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            return "\n".join(page.extract_text() or "" for page in pdf.pages)
    except Exception as exc:
        raise AiUnavailable(f"not a readable PDF: {exc}") from exc


def _norm(token: str) -> str:
    return token.strip().replace("−", "-").lstrip("+")


def _number_tokens(text: str) -> set[str]:
    return {_norm(t) for t in re.findall(r"[-+−]?\d+(?:[.,]\d+)?", text)}


def check_against_text(extraction: Extraction, text: str) -> list[dict[str, Any]]:
    """Rows as dicts with `found_in_pdf`: every numeric field must appear verbatim in the text."""
    tokens = _number_tokens(text)
    out = []
    for row in extraction.rows:
        values = [
            v
            for v in (row.actual, row.nominal, row.usl, row.lsl, row.upper_tol, row.lower_tol)
            if v
        ]
        found = all(_norm(v) in tokens for v in values)
        out.append(row.model_dump() | {"found_in_pdf": found})
    return out


def _client() -> Any:
    settings = get_settings()
    if not settings.ai_enabled:
        raise AiUnavailable("AI is disabled (AI_ENABLED=false)")
    if settings.ai_provider and settings.ai_provider.lower() != "groq":
        raise AiUnavailable(f"AI_PROVIDER={settings.ai_provider!r} is not supported; use groq")
    try:
        import groq
    except ImportError as exc:  # pragma: no cover
        raise AiUnavailable("groq SDK not installed") from exc
    # AI_API_KEY from .env if set, else the SDK reads GROQ_API_KEY.
    return groq.Groq(api_key=settings.ai_api_key) if settings.ai_api_key else groq.Groq()


def extract_rows(pdf_bytes: bytes, client: Any = None) -> dict[str, Any]:
    """Ask the Groq model for the report's rows. Raises AiUnavailable on any failure."""
    import groq

    text = pdf_text(pdf_bytes)
    if len(text.strip()) < 20:
        raise AiUnavailable("the PDF has no text layer (scanned image); OCR is not supported")
    if len(text) > MAX_TEXT_CHARS:
        raise AiUnavailable(
            "the PDF is too long for one extraction; export CSV from the CMM instead"
        )
    client = client or _client()
    model = get_settings().ai_model or DEFAULT_MODEL
    try:
        response = client.chat.completions.create(
            model=model,
            temperature=0,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": f"Inspection report text:\n\n{text}"},
            ],
        )
    except groq.RateLimitError as exc:
        raise AiUnavailable("Groq rate limit reached; try again shortly") from exc
    except groq.AuthenticationError as exc:
        raise AiUnavailable("Groq rejected the API key (check AI_API_KEY)") from exc
    except groq.APIStatusError as exc:
        raise AiUnavailable(f"Groq API error {exc.status_code}") from exc
    except groq.APIConnectionError as exc:
        raise AiUnavailable("Groq API not reachable (offline plant network?)") from exc

    content = response.choices[0].message.content or ""
    try:
        extraction = Extraction.model_validate(json.loads(content))
    except (json.JSONDecodeError, ValidationError) as exc:
        raise AiUnavailable("the model did not return rows in the expected format") from exc
    rows = check_against_text(extraction, text)
    logger.info(
        "Groq (%s) extracted %d rows; %d not found verbatim in the PDF",
        model,
        len(rows),
        sum(not r["found_in_pdf"] for r in rows),
    )
    return extraction.model_dump(exclude={"rows"}) | {
        "rows": rows,
        "model": model,
        "provider": "groq",
    }
