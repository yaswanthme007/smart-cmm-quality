"""Settings: guard band, escalation timers (demo/plant profile), SPC rules, recurrence window,
uncertainty rule, shifts, AI flag. Quality Head and Admin edit; every change is audited."""

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.deps import SETTINGS_EDITORS, get_actor, get_current_user, require_roles
from app.core.config import get_settings
from app.core.db import get_db
from app.models import Setting, User
from app.seed.masters import DEFAULT_SETTINGS
from app.services import audit
from app.services.spc import ALL_RULES

router = APIRouter(prefix="/settings", tags=["settings"])

EDITABLE = set(DEFAULT_SETTINGS)


def validate(key: str, value: Any) -> None:
    if key == "guard_band_pct_default" and not (
        isinstance(value, (int, float)) and 0 <= value <= 50
    ):
        raise HTTPException(422, "guard band must be between 0 and 50 %")
    if key == "recurrence_window_hours" and not (isinstance(value, int) and 1 <= value <= 168):
        raise HTTPException(422, "recurrence window must be 1-168 hours")
    if key == "spc_rules_enabled" and not (
        isinstance(value, list) and set(value) <= set(ALL_RULES)
    ):
        raise HTTPException(422, f"SPC rules must be a subset of {ALL_RULES}")
    if key == "escalation":
        if not isinstance(value, dict) or value.get("profile") not in ("demo", "plant"):
            raise HTTPException(422, "escalation.profile must be 'demo' or 'plant'")
        for profile in value.get("timers", {}).values():
            for pair in profile.values():
                if not (isinstance(pair, list) and len(pair) == 2 and 0 < pair[0] < pair[1]):
                    raise HTTPException(
                        422, "each timer is [level1_s, level2_s] with level1 < level2"
                    )


@router.get("")
def get_all(db: Session = Depends(get_db), _: User = Depends(get_current_user)) -> dict[str, Any]:
    out = dict(DEFAULT_SETTINGS)
    for row in db.query(Setting).filter(Setting.key.in_(EDITABLE)):
        out[row.key] = row.value
    out["ai_available"] = get_settings().ai_enabled
    out["demo_mode"] = get_settings().demo_mode
    return out


@router.put("")
def put(
    body: dict[str, Any],
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*SETTINGS_EDITORS)),
    actor: audit.Actor = Depends(get_actor),
) -> dict[str, Any]:
    unknown = set(body) - EDITABLE
    if unknown:
        raise HTTPException(422, f"unknown settings: {', '.join(sorted(unknown))}")
    for key, value in body.items():
        validate(key, value)
        row = db.get(Setting, key)
        before = row.value if row else DEFAULT_SETTINGS.get(key)
        if row is None:
            db.add(Setting(key=key, value=value, updated_by=user.id))
        else:
            row.value, row.updated_by = value, user.id
        if before != value:
            audit.record(
                db,
                actor=actor,
                action="settings.update",
                entity="settings",
                entity_id=key,
                before={"value": before},
                after={"value": value},
            )
    db.commit()
    return get_all(db, user)
