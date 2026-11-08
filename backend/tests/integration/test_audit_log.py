import uuid

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError

from app.core.logging import request_id_var
from app.models import AuditLog, Part
from app.services import audit


def test_record_writes_entry_with_actor_and_request_id(db):
    actor = audit.Actor(user_id=None, role="ADMIN", ip="10.0.0.5")
    token = request_id_var.set("req-42")
    try:
        part = Part(part_no="DC-101", name="Differential Case (demo)")
        db.add(part)
        db.flush()
        audit.record(
            db,
            actor=actor,
            action="part.create",
            entity="part",
            entity_id=part.id,
            after=audit.snapshot(part),
        )
        db.commit()
    finally:
        request_id_var.reset(token)

    entry = db.scalars(select(AuditLog)).one()
    assert entry.action == "part.create"
    assert entry.entity_id == str(part.id)
    assert entry.after["part_no"] == "DC-101"
    assert entry.request_id == "req-42"
    assert entry.actor_role == "ADMIN"
    assert entry.ip == "10.0.0.5"


def _insert_entry(db) -> int:
    audit.record(db, actor=audit.SYSTEM, action="test", entity="x", entity_id=uuid.uuid4())
    db.commit()
    return db.scalars(select(AuditLog.id)).one()


def test_update_on_audit_log_is_rejected(db):
    entry_id = _insert_entry(db)
    with pytest.raises(DBAPIError, match="append-only"):
        db.execute(
            text("UPDATE audit_log SET action = 'tampered' WHERE id = :id"), {"id": entry_id}
        )
    db.rollback()
    assert db.scalars(select(AuditLog.action)).one() == "test"


def test_delete_on_audit_log_is_rejected(db):
    entry_id = _insert_entry(db)
    with pytest.raises(DBAPIError, match="append-only"):
        db.execute(text("DELETE FROM audit_log WHERE id = :id"), {"id": entry_id})
    db.rollback()
    assert db.scalars(select(AuditLog)).one().id == entry_id


def test_snapshot_never_contains_password_hash():
    from app.models import User
    from app.models.enums import Role

    user = User(email="a@demo.local", full_name="A", role=Role.ADMIN, password_hash="secret")
    assert "password_hash" not in audit.snapshot(user)


def test_diff_returns_only_changed_keys():
    before, after = audit.diff(
        {"a": 1, "b": 2, "updated_at": "t1"}, {"a": 1, "b": 3, "updated_at": "t2"}
    )
    assert before == {"b": 2}
    assert after == {"b": 3}
