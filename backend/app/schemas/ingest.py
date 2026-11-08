"""Canonical ingestion records (Section 8.2). Every adapter produces a ParsedReport."""

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, Field


class RawRecord(BaseModel):
    """One characteristic row, normalized (dot decimals, mm, UTC)."""

    part_no: str
    serial_no: str | None = None
    machine_code: str | None = None
    measured_at: datetime | None = None
    char_no: str
    char_name: str | None = None
    actual: Decimal
    nominal: Decimal | None = None
    upper_tol: Decimal | None = None  # either tolerances...
    lower_tol: Decimal | None = None
    usl: Decimal | None = None  # ...or absolute limits
    lsl: Decimal | None = None
    unit: str = "mm"


class ParsedReport(BaseModel):
    """Header fields + characteristic rows from one file."""

    part_no: str | None = None
    serial_no: str | None = None
    machine_code: str | None = None
    measured_at: datetime | None = None
    operator_name: str | None = None
    batch_no: str | None = None
    records: list[RawRecord] = Field(default_factory=list)
    warnings: list[dict[str, Any]] = Field(default_factory=list)


class ManualRow(BaseModel):
    char_no: str
    actual: Decimal


class ManualReportIn(BaseModel):
    """Manual entry for one part (same validation as files)."""

    part_no: str
    serial_no: str | None = None
    machine_code: str
    measured_at: datetime | None = None
    operator_name: str | None = None
    batch_no: str | None = None
    rows: list[ManualRow] = Field(min_length=1)


class IngestWarning(BaseModel):
    code: str
    message: str
    char_no: str | None = None


class ReportSummary(BaseModel):
    id: uuid.UUID
    report_no: str
    status: str
    part_result: str | None
    nok_count: int
    marginal_count: int
    nc_id: uuid.UUID | None = None
    nc_no: str | None = None
    warnings: list[dict[str, Any]] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
