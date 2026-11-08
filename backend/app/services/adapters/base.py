"""Adapter interface (Section 8.3). Adapters parse bytes into a ParsedReport and never touch the DB."""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol

from app.models.enums import FileKind
from app.schemas.ingest import ParsedReport


class AdapterError(ValueError):
    """The file cannot be parsed with this adapter/profile. Message is shown to the user."""


@dataclass
class ProfileConfig:
    """Plain copy of a mapping profile so adapters stay DB-free."""

    name: str
    file_kind: FileKind
    delimiter: str | None = ","
    decimal_separator: str = "."
    header_row: int = 1
    column_map: dict[str, str] = field(default_factory=dict)
    header_fields: dict[str, dict[str, Any]] = field(default_factory=dict)
    unit: str = "mm"

    @classmethod
    def from_model(cls, profile: Any) -> "ProfileConfig":
        return cls(
            name=profile.name,
            file_kind=FileKind(profile.file_kind),
            delimiter=profile.delimiter,
            decimal_separator=profile.decimal_separator or ".",
            header_row=profile.header_row if profile.header_row is not None else 1,
            column_map=dict(profile.column_map or {}),
            header_fields=dict(profile.header_fields or {}),
            unit=profile.unit or "mm",
        )


@dataclass
class FileContext:
    """Facts about the incoming file that are not inside its bytes."""

    filename: str
    file_mtime: datetime | None = None
    upload_form: dict[str, Any] = field(default_factory=dict)
    # Sibling files, e.g. CALYPSO `<name>_hdr.txt` next to `<name>_chr.txt`.
    companions: dict[str, bytes] = field(default_factory=dict)


class Adapter(Protocol):
    def parse(self, data: bytes, profile: ProfileConfig, ctx: FileContext) -> ParsedReport: ...


def decode_text(data: bytes) -> str:
    """UTF-8 (with or without BOM), falling back to Windows-1252 for older CMM PCs."""
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError:
        return data.decode("cp1252")
