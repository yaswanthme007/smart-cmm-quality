"""Typed access to the `settings` table, falling back to seeded defaults."""

from decimal import Decimal
from typing import Any

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models import Setting
from app.models.enums import CharClass
from app.seed.masters import DEFAULT_SETTINGS


def get_value(session: Session, key: str) -> Any:
    row = session.get(Setting, key)
    return row.value if row is not None else DEFAULT_SETTINGS.get(key)


def guard_band_pct_default(session: Session) -> Decimal:
    return Decimal(str(get_value(session, "guard_band_pct_default") or 10))


def recurrence_window_hours(session: Session) -> int:
    return int(get_value(session, "recurrence_window_hours") or 8)


def escalation_timers(session: Session, severity: CharClass) -> tuple[int, int]:
    """Seconds until level 1 and level 2 for the active profile (demo or plant)."""
    cfg = get_value(session, "escalation") or DEFAULT_SETTINGS["escalation"]
    profile = cfg.get("profile") or get_settings().escalation_profile
    timers = cfg["timers"].get(profile) or cfg["timers"]["plant"]
    l1, l2 = timers.get(severity.value, timers.get("STANDARD"))
    return int(l1), int(l2)


def recurrence_escalate_at(session: Session) -> int:
    cfg = get_value(session, "escalation") or {}
    return int(cfg.get("recurrence_escalate_at", 3))


def spc_rules_enabled(session: Session) -> list[str]:
    return list(get_value(session, "spc_rules_enabled") or ["N1", "N2", "N3", "N5"])


def uncertainty_rule_enabled(session: Session) -> bool:
    return bool(get_value(session, "uncertainty_rule_enabled"))


def ai_enabled(session: Session) -> bool:
    return bool(get_settings().ai_enabled and get_value(session, "ai_enabled"))
