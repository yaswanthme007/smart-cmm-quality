"""Master data CRUD (Section 14): parts, characteristics, machines, processes, CMMs, ownership
rules, users, departments. Everyone can read (users: Admin only); only Admin writes. Every write is
audited. Rows referenced by history are deactivated rather than deleted.
"""

import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.deps import ADMIN_ONLY, get_actor, get_current_user, require_roles
from app.core.db import get_db
from app.core.security import hash_password
from app.models import (
    Characteristic,
    Cmm,
    Department,
    Machine,
    OwnershipRule,
    Part,
    Process,
    User,
)
from app.models.enums import CharClass, CharKind, CmmVendor, Role, ToleranceType
from app.services import audit

router = APIRouter(tags=["masters"])


class PartIn(BaseModel):
    part_no: str
    name: str
    drawing_no: str | None = None
    drawing_rev: str | None = None
    is_active: bool = True


class CharacteristicIn(BaseModel):
    char_no: str
    name: str
    kind: CharKind = CharKind.DIMENSION
    tolerance_type: ToleranceType
    nominal: float | None = None
    usl: float | None = None
    lsl: float | None = None
    reference_width: float | None = None
    unit: str = "mm"
    decimals: int = Field(3, ge=0, le=6)
    classification: CharClass = CharClass.STANDARD
    process_id: uuid.UUID | None = None
    guard_band_pct: float | None = None
    expanded_uncertainty: float | None = None
    is_active: bool = True


class MachineIn(BaseModel):
    code: str
    name: str
    process_id: uuid.UUID | None = None
    line: str | None = None
    is_active: bool = True


class ProcessIn(BaseModel):
    code: str
    name: str
    department_id: uuid.UUID | None = None


class CmmIn(BaseModel):
    code: str
    vendor: CmmVendor
    default_mapping_profile_id: uuid.UUID | None = None
    inbox_path: str | None = None


class OwnershipRuleIn(BaseModel):
    part_id: uuid.UUID | None = None
    process_id: uuid.UUID | None = None
    machine_id: uuid.UUID | None = None
    owner_user_id: uuid.UUID
    supervisor_user_id: uuid.UUID | None = None
    priority: int = 0


class UserIn(BaseModel):
    email: str
    full_name: str
    role: Role
    department_id: uuid.UUID | None = None
    is_active: bool = True
    password: str | None = Field(None, min_length=8)


def _out(obj: Any) -> dict[str, Any]:
    return audit.snapshot(obj)


def _crud(
    path: str,
    model: type,
    schema: type[BaseModel],
    entity: str,
    order: Any,
    read_roles: tuple[Role, ...] | None = None,
    parent: tuple[str, str] | None = None,
) -> None:
    """Register list/create/update(/deactivate) routes for one master table."""
    reader = require_roles(*read_roles) if read_roles else get_current_user

    def to_values(body: BaseModel) -> dict[str, Any]:
        values = body.model_dump(exclude_unset=False)
        if model is User:
            password = values.pop("password", None)
            if password:
                values["password_hash"] = hash_password(password)
        return values

    @router.get(path, name=f"list_{entity}")
    def list_rows(
        db: Session = Depends(get_db), _: User = Depends(reader), parent_id: uuid.UUID | None = None
    ) -> list[dict[str, Any]]:
        q = select(model).order_by(order)
        if parent and parent_id:
            q = q.where(getattr(model, parent[1]) == parent_id)
        return [_out(r) for r in db.scalars(q)]

    @router.post(path, status_code=201, name=f"create_{entity}")
    def create_row(
        body: schema,  # type: ignore[valid-type]
        db: Session = Depends(get_db),
        _: User = Depends(require_roles(*ADMIN_ONLY)),
        actor: audit.Actor = Depends(get_actor),
        parent_id: uuid.UUID | None = None,
    ) -> dict[str, Any]:
        values = to_values(body)
        if parent:
            if not parent_id:
                raise HTTPException(422, f"parent_id ({parent[0]}) query parameter required")
            values[parent[1]] = parent_id
        if model is User and "password_hash" not in values:
            raise HTTPException(422, "password required for a new user")
        row = model(**values)
        db.add(row)
        try:
            db.flush()
        except IntegrityError as exc:
            db.rollback()
            raise HTTPException(409, "duplicate or invalid reference") from exc
        audit.record(
            db,
            actor=actor,
            action=f"{entity}.create",
            entity=entity,
            entity_id=row.id,
            after=_out(row),
        )
        db.commit()
        return _out(row)

    @router.put(f"{path}/{{row_id}}", name=f"update_{entity}")
    def update_row(
        row_id: uuid.UUID,
        body: schema,  # type: ignore[valid-type]
        db: Session = Depends(get_db),
        _: User = Depends(require_roles(*ADMIN_ONLY)),
        actor: audit.Actor = Depends(get_actor),
    ) -> dict[str, Any]:
        row = db.get(model, row_id)
        if row is None:
            raise HTTPException(404, f"{entity} not found")
        before = _out(row)
        for key, value in to_values(body).items():
            setattr(row, key, value)
        try:
            db.flush()
        except IntegrityError as exc:
            db.rollback()
            raise HTTPException(409, "duplicate or invalid reference") from exc
        b, a = audit.diff(before, _out(row))
        audit.record(
            db,
            actor=actor,
            action=f"{entity}.update",
            entity=entity,
            entity_id=row.id,
            before=b,
            after=a,
        )
        db.commit()
        return _out(row)


_crud("/parts", Part, PartIn, "part", Part.part_no)
# POST /characteristics?parent_id=<part> creates; PUT /characteristics/{id} updates;
# GET /parts/{part_id}/characteristics lists one part's characteristics.
_crud(
    "/characteristics",
    Characteristic,
    CharacteristicIn,
    "characteristic",
    Characteristic.char_no,
    parent=("part_id", "part_id"),
)
_crud("/machines", Machine, MachineIn, "machine", Machine.code)
_crud("/processes", Process, ProcessIn, "process", Process.code)
_crud("/cmms", Cmm, CmmIn, "cmm", Cmm.code)
_crud(
    "/ownership-rules",
    OwnershipRule,
    OwnershipRuleIn,
    "ownership_rule",
    OwnershipRule.priority.desc(),
)
_crud("/users", User, UserIn, "user", User.email, read_roles=ADMIN_ONLY)


@router.get("/parts/{part_id}/characteristics")
def list_characteristics(
    part_id: uuid.UUID, db: Session = Depends(get_db), _: User = Depends(get_current_user)
) -> list[dict[str, Any]]:
    rows = db.scalars(
        select(Characteristic)
        .where(Characteristic.part_id == part_id)
        .order_by(Characteristic.char_no)
    )
    return [_out(r) for r in rows]


@router.get("/departments")
def list_departments(
    db: Session = Depends(get_db), _: User = Depends(get_current_user)
) -> list[dict[str, Any]]:
    return [_out(d) for d in db.scalars(select(Department).order_by(Department.name))]


@router.get("/people")
def list_people(
    db: Session = Depends(get_db), _: User = Depends(get_current_user)
) -> list[dict[str, Any]]:
    """Names and roles only, for owner pickers and display (any logged-in user)."""
    return [
        {"id": str(u.id), "full_name": u.full_name, "role": u.role.value, "email": u.email}
        for u in db.scalars(select(User).where(User.is_active).order_by(User.full_name))
    ]
