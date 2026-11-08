"""Master data tables (Section 7.2, Masters)."""

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, Timestamps, UUIDPk
from app.models.enums import (
    CharClass,
    CharKind,
    CmmVendor,
    FileKind,
    Role,
    ToleranceType,
)


def enum_col(enum_cls: type) -> Enum:
    return Enum(enum_cls, native_enum=False, length=32, validate_strings=True)


# Measurement values: up to 6 decimals is ample for mm metrology.
Measure = Numeric(14, 6)


class Department(UUIDPk, Timestamps, Base):
    __tablename__ = "departments"

    name: Mapped[str] = mapped_column(String(100), unique=True)
    head_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", use_alter=True, name="fk_departments_head_user_id_users")
    )


class Process(UUIDPk, Timestamps, Base):
    __tablename__ = "processes"

    code: Mapped[str] = mapped_column(String(32), unique=True)
    name: Mapped[str] = mapped_column(String(100))
    department_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("departments.id"))


class Machine(UUIDPk, Timestamps, Base):
    __tablename__ = "machines"

    code: Mapped[str] = mapped_column(String(32), unique=True)
    name: Mapped[str] = mapped_column(String(100))
    process_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("processes.id"))
    line: Mapped[str | None] = mapped_column(String(50))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")


class MappingProfile(UUIDPk, Timestamps, Base):
    __tablename__ = "mapping_profiles"

    name: Mapped[str] = mapped_column(String(100), unique=True)
    vendor: Mapped[CmmVendor] = mapped_column(enum_col(CmmVendor), default=CmmVendor.OTHER)
    file_kind: Mapped[FileKind] = mapped_column(enum_col(FileKind))
    delimiter: Mapped[str | None] = mapped_column(String(4))
    decimal_separator: Mapped[str] = mapped_column(String(1), default=".", server_default=".")
    header_row: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    column_map: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    header_fields: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    unit: Mapped[str] = mapped_column(String(8), default="mm", server_default="mm")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")


class Cmm(UUIDPk, Timestamps, Base):
    __tablename__ = "cmms"

    code: Mapped[str] = mapped_column(String(32), unique=True)
    vendor: Mapped[CmmVendor] = mapped_column(enum_col(CmmVendor))
    default_mapping_profile_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("mapping_profiles.id")
    )
    inbox_path: Mapped[str | None] = mapped_column(String(255))


class Part(UUIDPk, Timestamps, Base):
    __tablename__ = "parts"

    part_no: Mapped[str] = mapped_column(String(50), unique=True)
    name: Mapped[str] = mapped_column(String(100))
    drawing_no: Mapped[str | None] = mapped_column(String(50))
    drawing_rev: Mapped[str | None] = mapped_column(String(10))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")

    characteristics: Mapped[list["Characteristic"]] = relationship(
        back_populates="part", order_by="Characteristic.char_no"
    )


class Characteristic(UUIDPk, Timestamps, Base):
    __tablename__ = "characteristics"
    __table_args__ = (UniqueConstraint("part_id", "char_no", name="uq_characteristics_part_char"),)

    part_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("parts.id"))
    char_no: Mapped[str] = mapped_column(String(32))
    name: Mapped[str] = mapped_column(String(150))
    kind: Mapped[CharKind] = mapped_column(enum_col(CharKind), default=CharKind.DIMENSION)
    tolerance_type: Mapped[ToleranceType] = mapped_column(enum_col(ToleranceType))
    nominal: Mapped[Decimal | None] = mapped_column(Measure)
    usl: Mapped[Decimal | None] = mapped_column(Measure)
    lsl: Mapped[Decimal | None] = mapped_column(Measure)
    # Section 9.1: LOWER_ONLY characteristics need a configured reference width for the guard band.
    reference_width: Mapped[Decimal | None] = mapped_column(Measure)
    unit: Mapped[str] = mapped_column(String(8), default="mm", server_default="mm")
    decimals: Mapped[int] = mapped_column(Integer, default=3, server_default="3")
    classification: Mapped[CharClass] = mapped_column(
        enum_col(CharClass), default=CharClass.STANDARD
    )
    process_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("processes.id"))
    guard_band_pct: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
    expanded_uncertainty: Mapped[Decimal | None] = mapped_column(Measure)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")

    part: Mapped[Part] = relationship(back_populates="characteristics")


class User(UUIDPk, Timestamps, Base):
    __tablename__ = "users"

    email: Mapped[str] = mapped_column(String(255), unique=True)
    full_name: Mapped[str] = mapped_column(String(100))
    role: Mapped[Role] = mapped_column(enum_col(Role))
    department_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("departments.id"))
    password_hash: Mapped[str] = mapped_column(String(255))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")


class OwnershipRule(UUIDPk, Timestamps, Base):
    """Most specific match wins: machine > process > part > department head fallback."""

    __tablename__ = "ownership_rules"

    part_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("parts.id"))
    process_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("processes.id"))
    machine_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("machines.id"))
    owner_user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    supervisor_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    priority: Mapped[int] = mapped_column(Integer, default=0, server_default="0")


class Setting(Base):
    __tablename__ = "settings"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[Any] = mapped_column(JSONB)
    updated_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
