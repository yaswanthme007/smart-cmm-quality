"""Format detection and adapter lookup (Section 8.1 step 3)."""

import re
from pathlib import Path

from app.models.enums import FileKind
from app.services.adapters.base import Adapter, AdapterError
from app.services.adapters.generic_table import GenericTableAdapter

_AQDEF_LINE = re.compile(rb"^\s*K\d{4}(/\d+)?\s", re.MULTILINE)


def sniff_kind(filename: str, data: bytes) -> FileKind:
    """K-field lines -> AQDEF; `_chr.txt` -> CALYPSO-style; else by extension."""
    name = filename.lower()
    ext = Path(name).suffix
    if ext == ".dfq" or len(_AQDEF_LINE.findall(data[:4096])) >= 3:
        return FileKind.AQDEF
    if name.endswith("_chr.txt"):
        return FileKind.CALYPSO_CHR
    if ext == ".xlsx":
        return FileKind.XLSX
    if ext == ".pdf":
        return FileKind.PDF
    if ext in {".tsv", ".txt"}:
        return FileKind.TSV
    return FileKind.CSV


def adapter_for(kind: FileKind) -> Adapter:
    if kind in {FileKind.CSV, FileKind.TSV, FileKind.XLSX}:
        return GenericTableAdapter()
    if kind == FileKind.CALYPSO_CHR:
        from app.services.adapters.calypso_chr import CalypsoChrAdapter

        return CalypsoChrAdapter()
    if kind == FileKind.AQDEF:
        from app.services.adapters.aqdef import AqdefAdapter

        return AqdefAdapter()
    if kind == FileKind.PDF:
        from app.services.adapters.pdf_table import PdfTableAdapter

        return PdfTableAdapter()
    raise AdapterError(f"no adapter for {kind}")
