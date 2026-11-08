"""Transaction tables (Section 7.2, Transactions)."""

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, Timestamps, UUIDPk
from app.models.enums import (
    AlertKind,
    CharClass,
    LimitsSource,
    NcStatus,
    OutboxKind,
    OutboxStatus,
    ReportSource,
    ReportStatus,
    Result,
    RootCauseCategory,
    SpcSignalStatus,
)
from app.models.masters import Measure, enum_col

TZ = DateTime(timezone=True)


class InspectionReport(UUIDPk, Timestamps, Base):
    __tablename__ = "inspection_reports"
    __table_args__ = (
        Index("ix_reports_measured_at", "measured_at"),
        Index("ix_reports_status_measured", "status", "measured_at"),
        Index("ix_reports_machine_measured", "machine_id", "measured_at"),
        Index("ix_reports_part_serial", "part_id", "serial_no"),
        # Re-uploads never double-count; a FAILED file may be retried after fixing its mapping.
        Index(
            "uq_reports_sha256_not_failed",
            "sha256",
            unique=True,
            postgresql_where=text("status <> 'FAILED'"),
        ),
    )

    report_no: Mapped[str] = mapped_column(String(32), unique=True)
    cmm_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("cmms.id"))
    part_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("parts.id"))
    machine_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("machines.id"))
    process_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("processes.id"))
    serial_no: Mapped[str | None] = mapped_column(String(50))
    batch_no: Mapped[str | None] = mapped_column(String(50))
    operator_name: Mapped[str | None] = mapped_column(String(100))
    measured_at: Mapped[datetime | None] = mapped_column(TZ)
    received_at: Mapped[datetime] = mapped_column(TZ)
    ingested_at: Mapped[datetime | None] = mapped_column(TZ)
    source: Mapped[ReportSource] = mapped_column(enum_col(ReportSource))
    original_filename: Mapped[str | None] = mapped_column(String(255))
    storage_path: Mapped[str | None] = mapped_column(String(500))
    sha256: Mapped[str] = mapped_column(String(64), index=True)
    mapping_profile_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("mapping_profiles.id"))
    part_result: Mapped[Result | None] = mapped_column(enum_col(Result))
    nok_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    marginal_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    status: Mapped[ReportStatus] = mapped_column(enum_col(ReportStatus))
    warnings: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)
    uploaded_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    reinspection_of_report_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("inspection_reports.id")
    )

    measurements: Mapped[list["Measurement"]] = relationship(back_populates="report")


class Measurement(UUIDPk, Timestamps, Base):
    __tablename__ = "measurements"
    __table_args__ = (
        Index("ix_measurements_stream", "characteristic_id", "machine_id", "measured_at"),
        Index("ix_measurements_report", "report_id"),
        Index("ix_measurements_nok", "result", postgresql_where=text("result = 'NOK'")),
    )

    report_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("inspection_reports.id"))
    characteristic_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("characteristics.id"))
    char_no: Mapped[str] = mapped_column(String(32))
    char_name: Mapped[str | None] = mapped_column(String(150))
    machine_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("machines.id"))
    measured_at: Mapped[datetime | None] = mapped_column(TZ)
    actual: Mapped[Decimal] = mapped_column(Measure)
    nominal: Mapped[Decimal | None] = mapped_column(Measure)
    usl: Mapped[Decimal | None] = mapped_column(Measure)
    lsl: Mapped[Decimal | None] = mapped_column(Measure)
    deviation: Mapped[Decimal | None] = mapped_column(Measure)
    tolerance_used_pct: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
    result: Mapped[Result] = mapped_column(enum_col(Result))
    is_suspect: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    limits_source: Mapped[LimitsSource] = mapped_column(enum_col(LimitsSource))

    report: Mapped[InspectionReport] = relationship(back_populates="measurements")


class NonConformance(UUIDPk, Timestamps, Base):
    __tablename__ = "nonconformances"
    __table_args__ = (
        Index("ix_nc_status", "status"),
        Index("ix_nc_detected_at", "detected_at"),
        Index("ix_nc_part_machine_status", "part_id", "machine_id", "status"),
    )

    nc_no: Mapped[str] = mapped_column(String(32), unique=True)
    part_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("parts.id"))
    machine_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("machines.id"))
    process_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("processes.id"))
    first_report_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("inspection_reports.id"))
    severity: Mapped[CharClass] = mapped_column(enum_col(CharClass))
    status: Mapped[NcStatus] = mapped_column(enum_col(NcStatus), default=NcStatus.OPEN)
    owner_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    supervisor_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    detected_at: Mapped[datetime] = mapped_column(TZ)
    acknowledged_at: Mapped[datetime | None] = mapped_column(TZ)
    acknowledged_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    escalation_level: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    target_date: Mapped[date | None] = mapped_column(Date)
    containment: Mapped[str | None] = mapped_column(Text)
    root_cause_category: Mapped[RootCauseCategory | None] = mapped_column(
        enum_col(RootCauseCategory)
    )
    root_cause: Mapped[str | None] = mapped_column(Text)
    corrective_action: Mapped[str | None] = mapped_column(Text)
    preventive_action: Mapped[str | None] = mapped_column(Text)
    submitted_at: Mapped[datetime | None] = mapped_column(TZ)
    verified_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    verified_at: Mapped[datetime | None] = mapped_column(TZ)
    verification_note: Mapped[str | None] = mapped_column(Text)
    closed_at: Mapped[datetime | None] = mapped_column(TZ)
    cancel_reason: Mapped[str | None] = mapped_column(Text)
    recurrence_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    warnings: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)


class NcMeasurement(UUIDPk, Timestamps, Base):
    __tablename__ = "nc_measurements"

    nc_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("nonconformances.id"), index=True)
    measurement_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("measurements.id"), index=True)


class Alert(UUIDPk, Timestamps, Base):
    __tablename__ = "alerts"
    __table_args__ = (
        Index("ix_alerts_recipient_created", "recipient_user_id", "created_at"),
        Index("ix_alerts_kind_created", "kind", "created_at"),
    )

    kind: Mapped[AlertKind] = mapped_column(enum_col(AlertKind))
    nc_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("nonconformances.id"), index=True)
    spc_signal_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("spc_signals.id"))
    level: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    recipient_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    title: Mapped[str] = mapped_column(String(255))
    body: Mapped[str] = mapped_column(Text)
    source_received_at: Mapped[datetime | None] = mapped_column(TZ)
    read_at: Mapped[datetime | None] = mapped_column(TZ)
    acknowledged_at: Mapped[datetime | None] = mapped_column(TZ)
    generation_ms: Mapped[int | None] = mapped_column(Integer)


class Outbox(UUIDPk, Timestamps, Base):
    __tablename__ = "outbox"
    __table_args__ = (Index("ix_outbox_pending", "status", "next_attempt_at"),)

    kind: Mapped[OutboxKind] = mapped_column(enum_col(OutboxKind), default=OutboxKind.EMAIL)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB)
    alert_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("alerts.id"), index=True)
    status: Mapped[OutboxStatus] = mapped_column(
        enum_col(OutboxStatus), default=OutboxStatus.PENDING
    )
    attempts: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    next_attempt_at: Mapped[datetime] = mapped_column(TZ, server_default=func.now())
    sent_at: Mapped[datetime | None] = mapped_column(TZ)
    last_error: Mapped[str | None] = mapped_column(Text)


class Evidence(UUIDPk, Timestamps, Base):
    __tablename__ = "evidence"

    nc_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("nonconformances.id"), index=True)
    filename: Mapped[str] = mapped_column(String(255))
    storage_path: Mapped[str] = mapped_column(String(500))
    mime: Mapped[str] = mapped_column(String(100))
    size: Mapped[int] = mapped_column(Integer)
    sha256: Mapped[str] = mapped_column(String(64))
    note: Mapped[str | None] = mapped_column(Text)
    uploaded_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))


class SpcLimits(UUIDPk, Timestamps, Base):
    __tablename__ = "spc_limits"

    characteristic_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("characteristics.id"))
    machine_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("machines.id"))
    center: Mapped[Decimal] = mapped_column(Measure)
    ucl: Mapped[Decimal] = mapped_column(Measure)
    lcl: Mapped[Decimal] = mapped_column(Measure)
    mr_bar: Mapped[Decimal] = mapped_column(Measure)
    sigma_within: Mapped[Decimal] = mapped_column(Measure)
    n_baseline: Mapped[int] = mapped_column(Integer)
    baseline_from: Mapped[datetime | None] = mapped_column(TZ)
    baseline_to: Mapped[datetime | None] = mapped_column(TZ)
    frozen_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")


class SpcSignal(UUIDPk, Timestamps, Base):
    __tablename__ = "spc_signals"
    __table_args__ = (Index("ix_spc_signals_stream", "characteristic_id", "machine_id", "status"),)

    characteristic_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("characteristics.id"))
    machine_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("machines.id"))
    rule: Mapped[str] = mapped_column(String(4))
    measurement_ids: Mapped[list[str]] = mapped_column(JSONB, default=list)
    status: Mapped[SpcSignalStatus] = mapped_column(
        enum_col(SpcSignalStatus), default=SpcSignalStatus.ACTIVE
    )
    triggered_at: Mapped[datetime] = mapped_column(TZ)
    in_control_streak: Mapped[int] = mapped_column(Integer, default=0, server_default="0")


class AuditLog(Base):
    """Append-only (Section 16): a trigger rejects UPDATE and DELETE."""

    __tablename__ = "audit_log"
    __table_args__ = (Index("ix_audit_entity", "entity", "entity_id"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    at: Mapped[datetime] = mapped_column(TZ, server_default=func.now(), index=True)
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    actor_role: Mapped[str | None] = mapped_column(String(32))
    action: Mapped[str] = mapped_column(String(64))
    entity: Mapped[str] = mapped_column(String(64))
    entity_id: Mapped[str | None] = mapped_column(String(64))
    before: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    after: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    request_id: Mapped[str | None] = mapped_column(String(64))
    ip: Mapped[str | None] = mapped_column(String(64))
