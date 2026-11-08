"""Demo master data (Section 18.1). ALL VALUES ARE SYNTHETIC, labelled "(demo)".

Idempotent: running the seed twice updates rows in place by their natural keys.
"""

from dataclasses import dataclass
from decimal import Decimal
from functools import lru_cache
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.security import hash_password
from app.models import (
    Characteristic,
    Cmm,
    Department,
    Machine,
    MappingProfile,
    OwnershipRule,
    Part,
    Process,
    Setting,
    User,
)
from app.models.enums import (
    CharClass,
    CharKind,
    CmmVendor,
    FileKind,
    Role,
    ToleranceType,
)
from app.services import audit

D = Decimal

DEPARTMENTS = ["Machining (demo)", "Quality (demo)"]

USERS = [
    # username, full name, role, department
    ("inspector", "CMM Inspector (demo)", Role.INSPECTOR, "Quality (demo)"),
    ("owner.vmc02", "Process Owner VMC-02 (demo)", Role.PROCESS_OWNER, "Machining (demo)"),
    ("owner.hmc01", "Process Owner HMC-01 (demo)", Role.PROCESS_OWNER, "Machining (demo)"),
    ("supervisor", "Shift Supervisor (demo)", Role.SUPERVISOR, "Machining (demo)"),
    ("qhead", "Quality Head (demo)", Role.QUALITY_HEAD, "Quality (demo)"),
    ("admin", "Administrator (demo)", Role.ADMIN, "Quality (demo)"),
    ("viewer", "Plant Management Viewer (demo)", Role.VIEWER, None),
]
DEPARTMENT_HEADS = {"Machining (demo)": "supervisor", "Quality (demo)": "qhead"}
EMAIL_DOMAIN = "demo.local"

PROCESSES = [
    ("OP-20", "Rough boring", "Machining (demo)"),
    ("OP-30", "Finish boring", "Machining (demo)"),
    ("OP-40", "Facing", "Machining (demo)"),
]

MACHINES = [
    ("VMC-01", "Vertical machining centre 1 (demo)", "OP-20", "Line 1"),
    ("VMC-02", "Vertical machining centre 2 (demo)", "OP-30", "Line 1"),
    ("HMC-01", "Horizontal machining centre 1 (demo)", "OP-40", "Line 2"),
    ("CNC-T-01", "CNC turning centre 1 (demo)", "OP-20", "Line 2"),
    ("CNC-T-02", "CNC turning centre 2 (demo)", "OP-40", "Line 3"),
]


@dataclass(frozen=True)
class CharSpec:
    char_no: str
    name: str
    tolerance_type: ToleranceType
    nominal: Decimal
    usl: Decimal | None
    lsl: Decimal | None
    classification: CharClass
    process: str
    kind: CharKind = CharKind.DIMENSION


BI, UP = ToleranceType.BILATERAL, ToleranceType.UPPER_ONLY
CRIT, SIG, STD = CharClass.CRITICAL, CharClass.SIGNIFICANT, CharClass.STANDARD
GEO = CharKind.GEOMETRIC

PARTS: dict[str, tuple[str, list[CharSpec]]] = {
    "DC-101": (
        "Differential Case (demo)",
        [
            CharSpec(
                "C-01", "Pinion bore Ø", BI, D("48.000"), D("48.025"), D("48.000"), SIG, "OP-30"
            ),
            CharSpec(
                "C-02", "Flange face flatness", UP, D("0"), D("0.040"), None, STD, "OP-40", GEO
            ),
            CharSpec(
                "C-03", "Bearing bore Ø", BI, D("72.000"), D("72.030"), D("72.000"), CRIT, "OP-30"
            ),
            CharSpec("C-04", "Bore position", UP, D("0"), D("0.050"), None, SIG, "OP-30", GEO),
            CharSpec("C-05", "PCD Ø", BI, D("110.000"), D("110.050"), D("109.950"), STD, "OP-20"),
        ],
    ),
    "BD-205": (
        "Brake Drum (demo)",
        [
            CharSpec(
                "C-01",
                "Braking surface Ø",
                BI,
                D("254.000"),
                D("254.080"),
                D("253.920"),
                SIG,
                "OP-20",
            ),
            CharSpec("C-02", "Radial runout", UP, D("0"), D("0.060"), None, CRIT, "OP-40", GEO),
            CharSpec(
                "C-03", "Overall height", BI, D("96.000"), D("96.100"), D("95.900"), STD, "OP-40"
            ),
        ],
    ),
    "SK-310": (
        "Steering Knuckle (demo)",
        [
            CharSpec(
                "C-01", "Kingpin bore Ø", BI, D("30.000"), D("30.021"), D("30.000"), CRIT, "OP-30"
            ),
            CharSpec(
                "C-02", "Arm length", BI, D("142.000"), D("142.150"), D("141.850"), STD, "OP-20"
            ),
            CharSpec(
                "C-03", "Mounting face flatness", UP, D("0"), D("0.050"), None, SIG, "OP-40", GEO
            ),
        ],
    ),
}

# (machine code or None, process code or None, owner, supervisor, priority)
OWNERSHIP = [
    ("VMC-02", None, "owner.vmc02", "supervisor", 10),
    ("HMC-01", None, "owner.hmc01", "supervisor", 10),
    (None, "OP-20", "owner.vmc02", "supervisor", 5),
    (None, "OP-30", "owner.vmc02", "supervisor", 5),
    (None, "OP-40", "owner.hmc01", "supervisor", 5),
]

MAPPING_PROFILES: list[dict[str, Any]] = [
    {
        "name": "PC-DMIS CSV (CMM-02)",
        "vendor": CmmVendor.HEXAGON_PCDMIS,
        "file_kind": FileKind.CSV,
        "delimiter": ",",
        "decimal_separator": ".",
        "header_row": 1,
        "column_map": {
            "char_no": "Dimension",
            "char_name": "Description",
            "nominal": "Nominal",
            "upper_tol": "+Tol",
            "lower_tol": "-Tol",
            "actual": "Measured",
        },
        "header_fields": {
            "part_no": {"from": "filename", "regex": r"^(?P<v>[A-Z]{2}\d{3})_"},
            "serial_no": {"from": "filename", "regex": r"_SN(?P<v>\d+)"},
            "machine_code": {"from": "upload_form"},
            "measured_at": {"from": "file_mtime"},
        },
        "unit": "mm",
    },
    {
        "name": "CALYPSO table file _chr.txt (CMM-01)",
        "vendor": CmmVendor.ZEISS_CALYPSO,
        "file_kind": FileKind.CALYPSO_CHR,
        "delimiter": "\t",
        "decimal_separator": ".",
        "header_row": 1,
        "column_map": {
            "char_no": "id",
            "char_name": "comment",
            "actual": "actual",
            "nominal": "nominal",
            "upper_tol": "uppertol",
            "lower_tol": "lowertol",
        },
        "header_fields": {
            "part_no": {"from": "filename", "regex": r"^(?P<v>[A-Z]{2}\d{3})_"},
            "serial_no": {"from": "filename", "regex": r"_SN(?P<v>\d+)"},
            "machine_code": {"from": "column", "column": "machine"},
            "measured_at": {"from": "column", "column": "datetime"},
            "operator_name": {"from": "column", "column": "operator"},
        },
        "unit": "mm",
    },
    {
        "name": "PC-DMIS CSV German locale (demo)",
        "vendor": CmmVendor.HEXAGON_PCDMIS,
        "file_kind": FileKind.CSV,
        "delimiter": ";",
        "decimal_separator": ",",
        "header_row": 1,
        "column_map": {
            "char_no": "Dimension",
            "char_name": "Description",
            "nominal": "Nominal",
            "upper_tol": "+Tol",
            "lower_tol": "-Tol",
            "actual": "Measured",
        },
        "header_fields": {
            "part_no": {"from": "filename", "regex": r"^(?P<v>[A-Z]{2}\d{3})_"},
            "serial_no": {"from": "filename", "regex": r"_SN(?P<v>\d+)"},
            "machine_code": {"from": "upload_form"},
            "measured_at": {"from": "file_mtime"},
        },
        "unit": "mm",
    },
    {
        "name": "AQDEF subset (.dfq)",
        "vendor": CmmVendor.OTHER,
        "file_kind": FileKind.AQDEF,
        "delimiter": None,
        "decimal_separator": ".",
        "header_row": 0,
        "column_map": {},
        "header_fields": {},
        "unit": "mm",
    },
]

CMMS = [
    ("CMM-01", CmmVendor.ZEISS_CALYPSO, "CALYPSO table file _chr.txt (CMM-01)"),
    ("CMM-02", CmmVendor.HEXAGON_PCDMIS, "PC-DMIS CSV (CMM-02)"),
]

DEFAULT_SETTINGS: dict[str, Any] = {
    "guard_band_pct_default": 10,
    # Seconds until level 1 (supervisor) and level 2 (quality head) when unacknowledged.
    "escalation": {
        "profile": "demo",
        "timers": {
            "demo": {"CRITICAL": [60, 120], "SIGNIFICANT": [60, 120], "STANDARD": [60, 120]},
            "plant": {
                "CRITICAL": [600, 1800],
                "SIGNIFICANT": [1200, 3600],
                "STANDARD": [1800, 7200],
            },
        },
        "recurrence_escalate_at": 3,
    },
    "spc_rules_enabled": ["N1", "N2", "N3", "N5"],
    "recurrence_window_hours": 8,
    "ai_enabled": False,
    "uncertainty_rule_enabled": False,
    # ASSUMPTION (not confirmed with the plant): three 8-hour shifts, IST.
    "shifts": {
        "timezone": "Asia/Kolkata",
        "list": [
            {"name": "A", "start": "06:00"},
            {"name": "B", "start": "14:00"},
            {"name": "C", "start": "22:00"},
        ],
    },
}


@lru_cache(maxsize=4)
def _demo_hash(password: str) -> str:
    # All demo users share one password, so one Argon2id hash (with its own salt) is enough.
    return hash_password(password)


def user_email(username: str) -> str:
    return f"{username}@{EMAIL_DOMAIN}"


def _upsert(session: Session, model: type, key: dict[str, Any], values: dict[str, Any]) -> Any:
    obj = session.scalars(select(model).filter_by(**key)).one_or_none()
    if obj is None:
        obj = model(**key, **values)
        session.add(obj)
    else:
        for k, v in values.items():
            setattr(obj, k, v)
    session.flush()
    return obj


def seed_masters(session: Session) -> dict[str, int]:
    password = get_settings().demo_user_password
    if not password:
        raise RuntimeError("Set DEMO_USER_PASSWORD in .env before seeding demo users")

    depts = {name: _upsert(session, Department, {"name": name}, {}) for name in DEPARTMENTS}

    users: dict[str, User] = {}
    for username, full_name, role, dept in USERS:
        existing = session.scalars(select(User).filter_by(email=user_email(username))).one_or_none()
        values: dict[str, Any] = {
            "full_name": full_name,
            "role": role,
            "department_id": depts[dept].id if dept else None,
            "is_active": True,
        }
        if existing is None:
            values["password_hash"] = _demo_hash(password)
        users[username] = _upsert(session, User, {"email": user_email(username)}, values)

    for dept, head in DEPARTMENT_HEADS.items():
        depts[dept].head_user_id = users[head].id

    processes = {
        code: _upsert(
            session, Process, {"code": code}, {"name": name, "department_id": depts[dept].id}
        )
        for code, name, dept in PROCESSES
    }
    machines = {
        code: _upsert(
            session,
            Machine,
            {"code": code},
            {"name": name, "process_id": processes[proc].id, "line": line, "is_active": True},
        )
        for code, name, proc, line in MACHINES
    }

    n_chars = 0
    for part_no, (part_name, chars) in PARTS.items():
        part = _upsert(
            session,
            Part,
            {"part_no": part_no},
            {
                "name": part_name,
                "drawing_no": f"DEMO-{part_no.replace('-', '')}",
                "drawing_rev": "C",
                "is_active": True,
            },
        )
        for c in chars:
            _upsert(
                session,
                Characteristic,
                {"part_id": part.id, "char_no": c.char_no},
                {
                    "name": c.name,
                    "kind": c.kind,
                    "tolerance_type": c.tolerance_type,
                    "nominal": c.nominal,
                    "usl": c.usl,
                    "lsl": c.lsl,
                    "unit": "mm",
                    "decimals": 3,
                    "classification": c.classification,
                    "process_id": processes[c.process].id,
                    "is_active": True,
                },
            )
            n_chars += 1

    for machine, process, owner, supervisor, priority in OWNERSHIP:
        _upsert(
            session,
            OwnershipRule,
            {
                "machine_id": machines[machine].id if machine else None,
                "process_id": processes[process].id if process else None,
                "part_id": None,
            },
            {
                "owner_user_id": users[owner].id,
                "supervisor_user_id": users[supervisor].id,
                "priority": priority,
            },
        )

    profiles = {
        p["name"]: _upsert(
            session,
            MappingProfile,
            {"name": p["name"]},
            {k: v for k, v in p.items() if k != "name"},
        )
        for p in MAPPING_PROFILES
    }
    for code, vendor, profile in CMMS:
        _upsert(
            session,
            Cmm,
            {"code": code},
            {
                "vendor": vendor,
                "default_mapping_profile_id": profiles[profile].id,
                "inbox_path": f"inbox/{code}",
            },
        )

    for key, value in DEFAULT_SETTINGS.items():
        if session.get(Setting, key) is None:
            session.add(Setting(key=key, value=value))

    audit.record(
        session,
        actor=audit.SYSTEM,
        action="seed.masters",
        entity="seed",
        after={"parts": len(PARTS), "characteristics": n_chars, "users": len(users)},
    )
    session.flush()
    return {"parts": len(PARTS), "characteristics": n_chars, "users": len(users)}
