import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict


class MeasurementOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    characteristic_id: uuid.UUID | None
    char_no: str
    char_name: str | None
    actual: Decimal
    nominal: Decimal | None
    usl: Decimal | None
    lsl: Decimal | None
    deviation: Decimal | None
    tolerance_used_pct: Decimal | None
    result: str
    is_suspect: bool
    limits_source: str
    classification: str | None = None
    tolerance_type: str | None = None


class ReportOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    report_no: str
    part_id: uuid.UUID | None
    part_no: str | None = None
    part_name: str | None = None
    machine_id: uuid.UUID | None
    machine_code: str | None = None
    process_id: uuid.UUID | None
    process_code: str | None = None
    cmm_code: str | None = None
    serial_no: str | None
    batch_no: str | None
    operator_name: str | None
    measured_at: datetime | None
    received_at: datetime
    ingested_at: datetime | None
    source: str
    original_filename: str | None
    part_result: str | None
    nok_count: int
    marginal_count: int
    status: str
    warnings: list[dict[str, Any]]
    reinspection_of_report_id: uuid.UUID | None
    mapping_profile_id: uuid.UUID | None


class ReportDetail(ReportOut):
    measurements: list[MeasurementOut] = []
    nc_ids: list[uuid.UUID] = []
    nc_nos: list[str] = []
    reinspected_by: list[uuid.UUID] = []


class ReportPage(BaseModel):
    total: int
    items: list[ReportOut]


class DuplicateOut(BaseModel):
    detail: str
    report_id: uuid.UUID
    report_no: str
