"""Normalization helpers (Section 8.1 step 5): decimal comma, trimming, inch -> mm, UTC."""

import re
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from zoneinfo import ZoneInfo

INCH_TO_MM = Decimal("25.4")
# Timestamps without an offset are taken as plant local time (IST).
PLANT_TZ = ZoneInfo("Asia/Kolkata")

_DATETIME_FORMATS = [
    "%Y-%m-%dT%H:%M:%S%z",
    "%Y-%m-%d %H:%M:%S%z",
    "%Y-%m-%dT%H:%M:%S",
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%d %H:%M",
    "%d.%m.%Y/%H:%M:%S",  # AQDEF K0004
    "%d.%m.%Y %H:%M:%S",
    "%d/%m/%Y %H:%M:%S",
    "%d/%m/%Y %H:%M",
    "%Y-%m-%d",
]


def to_decimal(value: object, decimal_separator: str = ".") -> Decimal | None:
    """Parse a cell into Decimal. Empty -> None. Raises ValueError on garbage."""
    if value is None:
        return None
    if isinstance(value, Decimal):
        return value
    if isinstance(value, (int, float)):
        return Decimal(repr(value)) if isinstance(value, float) else Decimal(value)
    text = str(value).strip().replace("−", "-").replace(" ", "")
    if text in {"", "-", "--"}:
        return None
    if decimal_separator == ",":
        text = text.replace(".", "").replace(",", ".")
    try:
        return Decimal(text)
    except InvalidOperation as exc:
        raise ValueError(f"not a number: {value!r}") from exc


def to_mm(value: Decimal | None, unit: str) -> Decimal | None:
    if value is None:
        return None
    return value * INCH_TO_MM if unit.lower() in {"in", "inch", "inches"} else value


def to_utc(value: object) -> datetime | None:
    """Parse a timestamp (str or datetime) to aware UTC. Naive values are plant local time."""
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        dt = value
    else:
        text = str(value).strip()
        dt = None
        try:
            dt = datetime.fromisoformat(text)
        except ValueError:
            for fmt in _DATETIME_FORMATS:
                try:
                    dt = datetime.strptime(text, fmt)  # noqa: DTZ007 - tz applied below
                    break
                except ValueError:
                    continue
        if dt is None:
            raise ValueError(f"unrecognized date/time: {value!r}")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=PLANT_TZ)
    return dt.astimezone(UTC)


def clean(value: object) -> str | None:
    if value is None:
        return None
    text = re.sub(r"\s+", " ", str(value)).strip()
    return text or None
