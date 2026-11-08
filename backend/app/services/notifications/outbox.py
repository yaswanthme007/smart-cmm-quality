"""Transactional outbox for email (Section 6 D7).

`enqueue_email` writes an outbox row in the caller's transaction. The worker's dispatcher picks
PENDING rows with FOR UPDATE SKIP LOCKED, sends them over SMTP and retries with backoff, so an
upload never blocks on SMTP and an email is never lost when SMTP is down.
"""

import logging
import smtplib
import uuid
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from email.message import EmailMessage

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models import Outbox
from app.models.enums import OutboxKind, OutboxStatus

logger = logging.getLogger(__name__)

MAX_ATTEMPTS = 8


def enqueue_email(
    session: Session, *, to: str, subject: str, body: str, alert_id: uuid.UUID | None
) -> Outbox:
    row = Outbox(
        kind=OutboxKind.EMAIL,
        payload={"to": to, "subject": subject, "body": body},
        alert_id=alert_id,
        status=OutboxStatus.PENDING,
        next_attempt_at=datetime.now(UTC),
    )
    session.add(row)
    return row


def smtp_send(to: str, subject: str, body: str) -> None:
    s = get_settings()
    msg = EmailMessage()
    msg["From"] = s.smtp_from
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(body)
    with smtplib.SMTP(s.smtp_host, s.smtp_port, timeout=10) as smtp:
        if s.smtp_user:
            smtp.starttls()
            smtp.login(s.smtp_user, s.smtp_password)
        smtp.send_message(msg)


def backoff(attempts: int) -> timedelta:
    return timedelta(seconds=min(2**attempts, 300))


def dispatch_batch(
    session: Session, sender: Callable[[str, str, str], None] = smtp_send, limit: int = 20
) -> int:
    """Send due emails. Returns the number sent. Caller commits."""
    now = datetime.now(UTC)
    rows = session.scalars(
        select(Outbox)
        .where(Outbox.status == OutboxStatus.PENDING, Outbox.next_attempt_at <= now)
        .order_by(Outbox.next_attempt_at)
        .limit(limit)
        .with_for_update(skip_locked=True)
    ).all()
    sent = 0
    for row in rows:
        row.attempts += 1
        try:
            sender(row.payload["to"], row.payload["subject"], row.payload["body"])
        except Exception as exc:
            row.last_error = str(exc)[:500]
            if row.attempts >= MAX_ATTEMPTS:
                row.status = OutboxStatus.FAILED
            else:
                row.next_attempt_at = datetime.now(UTC) + backoff(row.attempts)
            logger.warning(
                "email to %s failed (attempt %d): %s", row.payload["to"], row.attempts, exc
            )
            continue
        row.status = OutboxStatus.SENT
        row.sent_at = datetime.now(UTC)
        row.last_error = None
        sent += 1
    return sent
