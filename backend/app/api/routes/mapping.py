"""Mapping profiles: CRUD + live preview (Section 8.5). Admin edits; everyone can read."""

import json
import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import ADMIN_ONLY, get_actor, get_current_user, require_roles
from app.core.db import get_db
from app.models import Characteristic, MappingProfile, User
from app.models.enums import CmmVendor, FileKind
from app.services import audit, settings
from app.services.adapters.base import AdapterError, FileContext, ProfileConfig
from app.services.adapters.generic_table import CANONICAL_FIELDS, read_table, rows_to_report
from app.services.adapters.registry import adapter_for, sniff_kind
from app.services.classification import Limits, classify, limits_from_tolerances
from app.services.ingestion.pipeline import find_part

router = APIRouter(prefix="/mapping-profiles", tags=["mapping"])


class MappingProfileIn(BaseModel):
    name: str
    vendor: CmmVendor = CmmVendor.OTHER
    file_kind: FileKind
    delimiter: str | None = ","
    decimal_separator: str = "."
    header_row: int = 1
    column_map: dict[str, str] = Field(default_factory=dict)
    header_fields: dict[str, dict[str, Any]] = Field(default_factory=dict)
    unit: str = "mm"
    is_active: bool = True


class MappingProfileOut(MappingProfileIn):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID


class PreviewRow(BaseModel):
    char_no: str
    char_name: str | None
    actual: Decimal
    nominal: Decimal | None
    usl: Decimal | None
    lsl: Decimal | None
    result: str | None
    limits_source: str


class PreviewOut(BaseModel):
    detected_kind: FileKind
    columns: list[str]
    sample: list[list[Any]]
    header: dict[str, Any]
    rows: list[PreviewRow]
    error: str | None = None
    canonical_fields: list[str] = CANONICAL_FIELDS


@router.get("", response_model=list[MappingProfileOut])
def list_profiles(
    db: Session = Depends(get_db), _: User = Depends(get_current_user)
) -> list[MappingProfile]:
    return list(db.scalars(select(MappingProfile).order_by(MappingProfile.name)))


@router.get("/{profile_id}", response_model=MappingProfileOut)
def get_profile(
    profile_id: uuid.UUID, db: Session = Depends(get_db), _: User = Depends(get_current_user)
) -> MappingProfile:
    profile = db.get(MappingProfile, profile_id)
    if profile is None:
        raise HTTPException(404, "mapping profile not found")
    return profile


@router.post("", response_model=MappingProfileOut, status_code=201)
def create_profile(
    body: MappingProfileIn,
    db: Session = Depends(get_db),
    _: User = Depends(require_roles(*ADMIN_ONLY)),
    actor: audit.Actor = Depends(get_actor),
) -> MappingProfile:
    if db.scalars(select(MappingProfile).where(MappingProfile.name == body.name)).first():
        raise HTTPException(409, "a profile with this name exists")
    profile = MappingProfile(**body.model_dump())
    db.add(profile)
    db.flush()
    audit.record(
        db,
        actor=actor,
        action="mapping_profile.create",
        entity="mapping_profile",
        entity_id=profile.id,
        after=audit.snapshot(profile),
    )
    db.commit()
    return profile


@router.put("/{profile_id}", response_model=MappingProfileOut)
def update_profile(
    profile_id: uuid.UUID,
    body: MappingProfileIn,
    db: Session = Depends(get_db),
    _: User = Depends(require_roles(*ADMIN_ONLY)),
    actor: audit.Actor = Depends(get_actor),
) -> MappingProfile:
    profile = db.get(MappingProfile, profile_id)
    if profile is None:
        raise HTTPException(404, "mapping profile not found")
    before = audit.snapshot(profile)
    for key, value in body.model_dump().items():
        setattr(profile, key, value)
    db.flush()
    b, a = audit.diff(before, audit.snapshot(profile))
    audit.record(
        db,
        actor=actor,
        action="mapping_profile.update",
        entity="mapping_profile",
        entity_id=profile.id,
        before=b,
        after=a,
    )
    db.commit()
    return profile


@router.delete("/{profile_id}", status_code=204)
def deactivate_profile(
    profile_id: uuid.UUID,
    db: Session = Depends(get_db),
    _: User = Depends(require_roles(*ADMIN_ONLY)),
    actor: audit.Actor = Depends(get_actor),
) -> None:
    """Profiles are referenced by reports, so they are deactivated, never deleted."""
    profile = db.get(MappingProfile, profile_id)
    if profile is None:
        raise HTTPException(404, "mapping profile not found")
    profile.is_active = False
    audit.record(
        db,
        actor=actor,
        action="mapping_profile.deactivate",
        entity="mapping_profile",
        entity_id=profile.id,
        after={"is_active": False},
    )
    db.commit()


@router.post("/preview", response_model=PreviewOut)
async def preview(
    request: Request,
    file: UploadFile = File(...),
    profile: str | None = Form(None, description="MappingProfileIn as JSON"),
    machine_code: str | None = Form(None),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> PreviewOut:
    """Sample file -> detected columns + first 10 classified rows (nothing is stored)."""
    data = await file.read()
    filename = file.filename or "sample"
    kind = sniff_kind(filename, data)
    cfg_in = MappingProfileIn.model_validate(json.loads(profile)) if profile else None
    config = (
        ProfileConfig(
            name=cfg_in.name,
            file_kind=cfg_in.file_kind,
            delimiter=cfg_in.delimiter,
            decimal_separator=cfg_in.decimal_separator,
            header_row=cfg_in.header_row,
            column_map=cfg_in.column_map,
            header_fields=cfg_in.header_fields,
            unit=cfg_in.unit,
        )
        if cfg_in
        else ProfileConfig(
            name="detect", file_kind=kind, delimiter="," if kind == FileKind.CSV else "\t"
        )
    )
    ctx = FileContext(
        filename=filename,
        file_mtime=datetime.now(UTC),
        upload_form={"machine_code": machine_code} if machine_code else {},
    )
    columns: list[str] = []
    sample: list[list[Any]] = []
    if config.file_kind in {FileKind.CSV, FileKind.TSV, FileKind.XLSX}:
        try:
            columns, body, preamble = read_table(data, config)
            sample = [[None if c is None else str(c) for c in r] for r in body[:10]]
        except AdapterError as exc:
            return PreviewOut(
                detected_kind=kind, columns=[], sample=[], header={}, rows=[], error=str(exc)
            )
        if not cfg_in or not cfg_in.column_map:
            return PreviewOut(
                detected_kind=kind, columns=columns, sample=sample, header={}, rows=[]
            )
        try:
            parsed = rows_to_report(columns, body[:10], preamble, config, ctx)
        except AdapterError as exc:
            return PreviewOut(
                detected_kind=kind,
                columns=columns,
                sample=sample,
                header={},
                rows=[],
                error=str(exc),
            )
    else:
        try:
            parsed = adapter_for(config.file_kind).parse(data, config, ctx)
        except AdapterError as exc:
            return PreviewOut(
                detected_kind=kind, columns=[], sample=[], header={}, rows=[], error=str(exc)
            )

    part = find_part(db, parsed.part_no) if parsed.part_no else None
    chars = (
        {
            c.char_no: c
            for c in db.scalars(select(Characteristic).where(Characteristic.part_id == part.id))
        }
        if part
        else {}
    )
    guard = settings.guard_band_pct_default(db)
    rows = []
    for rec in parsed.records[:10]:
        c = chars.get(rec.char_no)
        if c is not None:
            lim = Limits(
                c.tolerance_type,
                c.nominal,
                c.usl,
                c.lsl,
                c.decimals,
                c.kind,
                c.guard_band_pct if c.guard_band_pct is not None else guard,
                c.reference_width,
            )
            src = "MASTER"
        else:
            usl, lsl = limits_from_tolerances(
                rec.nominal, rec.upper_tol, rec.lower_tol, rec.usl, rec.lsl
            )
            from app.models.enums import ToleranceType

            ttype = (
                ToleranceType.BILATERAL
                if usl is not None and lsl is not None
                else (ToleranceType.UPPER_ONLY if usl is not None else ToleranceType.LOWER_ONLY)
            )
            lim = (
                Limits(ttype, rec.nominal, usl, lsl, guard_band_pct=guard)
                if (usl is not None or lsl is not None)
                else None
            )
            src = "REPORT"
        result = classify(rec.actual, lim).result.value if lim else None
        rows.append(
            PreviewRow(
                char_no=rec.char_no,
                char_name=rec.char_name or (c.name if c else None),
                actual=rec.actual,
                nominal=lim.nominal if lim else rec.nominal,
                usl=lim.usl if lim else None,
                lsl=lim.lsl if lim else None,
                result=result,
                limits_source=src,
            )
        )
    header = parsed.model_dump(
        mode="json", include={"part_no", "serial_no", "machine_code", "measured_at"}
    )
    if parsed.part_no and part is None:
        return PreviewOut(
            detected_kind=kind,
            columns=columns,
            sample=sample,
            header=header,
            rows=rows,
            error=f"part {parsed.part_no!r} is not in the master data",
        )
    return PreviewOut(detected_kind=kind, columns=columns, sample=sample, header=header, rows=rows)
