"""Owner resolution (Section 10.2).

Most specific rule first: machine -> process -> part -> department head. If nothing matches,
the Quality Head is alerted with a "no owner configured" warning; alerts are never dropped.
"""

import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Department, OwnershipRule, Process, User
from app.models.enums import Role


@dataclass(frozen=True)
class Owners:
    owner_user_id: uuid.UUID | None
    supervisor_user_id: uuid.UUID | None
    matched_by: str  # "machine" | "process" | "part" | "department_head" | "quality_head" | "none"
    warning: str | None = None


def _specificity(rule: OwnershipRule) -> tuple[int, int]:
    rank = 3 if rule.machine_id else 2 if rule.process_id else 1 if rule.part_id else 0
    return rank, rule.priority


def resolve_owners(
    session: Session,
    *,
    machine_id: uuid.UUID | None,
    process_id: uuid.UUID | None,
    part_id: uuid.UUID | None,
) -> Owners:
    candidates = []
    for rule in session.scalars(select(OwnershipRule)):
        if rule.machine_id and rule.machine_id != machine_id:
            continue
        if rule.process_id and rule.process_id != process_id:
            continue
        if rule.part_id and rule.part_id != part_id:
            continue
        if not (rule.machine_id or rule.process_id or rule.part_id):
            continue
        candidates.append(rule)
    if candidates:
        best = max(candidates, key=_specificity)
        level = {3: "machine", 2: "process", 1: "part"}[_specificity(best)[0]]
        return Owners(best.owner_user_id, best.supervisor_user_id, level)

    if process_id:
        process = session.get(Process, process_id)
        dept = session.get(Department, process.department_id) if process else None
        if dept and dept.head_user_id:
            return Owners(dept.head_user_id, None, "department_head")

    qhead = session.scalars(
        select(User).where(User.role == Role.QUALITY_HEAD, User.is_active).order_by(User.email)
    ).first()
    return Owners(
        qhead.id if qhead else None,
        None,
        "quality_head" if qhead else "none",
        "no owner configured for this machine/process; alerted the Quality Head",
    )


def quality_head_id(session: Session) -> uuid.UUID | None:
    return session.scalars(
        select(User.id).where(User.role == Role.QUALITY_HEAD, User.is_active).order_by(User.email)
    ).first()
