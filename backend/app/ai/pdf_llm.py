"""AI-assisted PDF extraction (Section 19, COULD). Runs only when AI_ENABLED=true.

Used only after deterministic pdfplumber extraction has failed. Claude reads the PDF and returns
rows in the canonical RawRecord shape (structured output). The result never reaches the
classifier directly: the report is stored as NEEDS_CONFIRMATION and only rows a person confirms
are classified. The AI never decides OK / Not OK and never alerts.
"""

import base64
import json
import logging
from typing import Any

from app.core.config import get_settings

logger = logging.getLogger(__name__)

DEFAULT_MODEL = "claude-opus-5"

ROW_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "part_no": {"type": ["string", "null"]},
        "serial_no": {"type": ["string", "null"]},
        "machine_code": {"type": ["string", "null"]},
        "measured_at": {"type": ["string", "null"], "description": "ISO 8601 if printed"},
        "rows": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "char_no": {"type": "string"},
                    "char_name": {"type": ["string", "null"]},
                    "actual": {
                        "type": "string",
                        "description": "measured value exactly as printed",
                    },
                    "nominal": {"type": ["string", "null"]},
                    "upper_tol": {"type": ["string", "null"]},
                    "lower_tol": {"type": ["string", "null"]},
                    "usl": {"type": ["string", "null"]},
                    "lsl": {"type": ["string", "null"]},
                },
                "required": [
                    "char_no",
                    "char_name",
                    "actual",
                    "nominal",
                    "upper_tol",
                    "lower_tol",
                    "usl",
                    "lsl",
                ],
                "additionalProperties": False,
            },
        },
    },
    "required": ["part_no", "serial_no", "machine_code", "measured_at", "rows"],
    "additionalProperties": False,
}

PROMPT = (
    "This PDF is a coordinate measuring machine (CMM) inspection report. Extract the report "
    "header (part number, serial number, machine, measurement time) and one row per measured "
    "characteristic. Copy numbers exactly as printed; do not round, convert or judge them. Use "
    "null for anything the report does not show. Do not invent rows. A person will check every "
    "row against the PDF before it is used."
)


class AiUnavailable(Exception):
    pass


def extract_rows(pdf_bytes: bytes) -> dict[str, Any]:
    """Ask Claude for the report's rows. Raises AiUnavailable when AI is off or the call fails."""
    settings = get_settings()
    if not settings.ai_enabled:
        raise AiUnavailable("AI is disabled (AI_ENABLED=false)")
    try:
        import anthropic
    except ImportError as exc:  # pragma: no cover
        raise AiUnavailable("anthropic SDK not installed") from exc

    # Credentials: AI_API_KEY from .env if set, else the SDK's own resolution
    # (ANTHROPIC_API_KEY, ANTHROPIC_AUTH_TOKEN or an `ant auth login` profile).
    client = (
        anthropic.Anthropic(api_key=settings.ai_api_key)
        if settings.ai_api_key
        else anthropic.Anthropic()
    )
    try:
        response = client.beta.messages.create(
            model=settings.ai_model or DEFAULT_MODEL,
            max_tokens=16000,
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
            output_config={"format": {"type": "json_schema", "schema": ROW_SCHEMA}},
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "document",
                            "source": {
                                "type": "base64",
                                "media_type": "application/pdf",
                                "data": base64.standard_b64encode(pdf_bytes).decode("ascii"),
                            },
                        },
                        {"type": "text", "text": PROMPT},
                    ],
                }
            ],
        )
    except anthropic.RateLimitError as exc:
        raise AiUnavailable("AI provider rate limit; try again shortly") from exc
    except anthropic.APIStatusError as exc:
        raise AiUnavailable(f"AI provider error {exc.status_code}") from exc
    except anthropic.APIConnectionError as exc:
        raise AiUnavailable("AI provider not reachable (offline plant network?)") from exc

    if response.stop_reason == "refusal":
        raise AiUnavailable("the model declined this document")
    if response.stop_reason == "max_tokens":
        raise AiUnavailable("the report is too long for one extraction")
    text = next((b.text for b in response.content if b.type == "text"), None)
    if text is None:
        raise AiUnavailable("no extraction returned")
    data: dict[str, Any] = json.loads(text)
    logger.info(
        "AI extracted %d rows from PDF (model %s)", len(data.get("rows", [])), response.model
    )
    return data
