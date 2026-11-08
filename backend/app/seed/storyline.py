"""Demo storyline reset (Section 18.3): `make demo-reset`.

1. Wipe all data (TRUNCATE; the audit trigger blocks row UPDATE/DELETE, not a full reset).
2. Seed demo masters and settings (escalation profile = demo: 60 s / 120 s).
3. Insert 30 days of synthetic history ending with the N3 drift on VMC-02 C-03.
4. Empty the inbox / processed / failed / uploads / evidence folders.
The live step is `make demo-drop`: DC101_SN0457_chr.txt with C-03 = 72.034 -> Not OK.
"""

import logging
import shutil

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models import Base, Setting
from app.seed.history import seed_history
from app.seed.masters import DEFAULT_SETTINGS, seed_masters

logger = logging.getLogger("app.seed.storyline")

DATA_SUBDIRS = ["inbox", "processed", "failed", "uploads", "evidence"]
CMMS = ["CMM-01", "CMM-02"]


def wipe(session: Session) -> None:
    tables = ", ".join(f'"{t.name}"' for t in Base.metadata.sorted_tables)
    session.execute(text(f"TRUNCATE {tables} RESTART IDENTITY CASCADE"))


def reset_folders() -> None:
    root = get_settings().data_dir
    for sub in DATA_SUBDIRS:
        path = root / sub
        if path.exists():
            shutil.rmtree(path, ignore_errors=True)
        path.mkdir(parents=True, exist_ok=True)
    for cmm in CMMS:
        for sub in ("inbox", "processed", "failed"):
            (root / sub / cmm).mkdir(parents=True, exist_ok=True)


def clear_mailpit() -> None:
    """Best effort: empty the demo Mailpit inbox (its web API listens on port 8025)."""
    import urllib.request

    url = f"http://{get_settings().smtp_host}:8025/api/v1/messages"
    try:
        urllib.request.urlopen(urllib.request.Request(url, method="DELETE"), timeout=2)
    except OSError:
        logger.info("mailpit not reachable at %s; inbox not cleared", url)


def reset(session: Session, days: int = 30, seed: int = 42) -> dict[str, int]:
    wipe(session)
    seed_masters(session)
    escalation = dict(DEFAULT_SETTINGS["escalation"]) | {"profile": "demo"}
    session.merge(Setting(key="escalation", value=escalation))
    counts = seed_history(session, days=days, seed=seed)
    reset_folders()
    clear_mailpit()
    return counts
