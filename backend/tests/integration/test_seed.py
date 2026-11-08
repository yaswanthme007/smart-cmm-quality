from decimal import Decimal as D

from sqlalchemy import func, select

from app.core.security import verify_password
from app.models import Characteristic, Cmm, OwnershipRule, Part, Setting, User
from app.models.enums import CharClass, Role
from app.seed.masters import seed_masters, user_email


def test_seed_creates_demo_masters(db):
    counts = seed_masters(db)
    db.commit()

    assert counts == {"parts": 3, "characteristics": 11, "users": 7}
    c03 = db.scalars(
        select(Characteristic)
        .join(Part)
        .where(Part.part_no == "DC-101", Characteristic.char_no == "C-03")
    ).one()
    assert (c03.lsl, c03.usl, c03.classification) == (D("72"), D("72.030"), CharClass.CRITICAL)
    assert all("(demo)" in p.name for p in db.scalars(select(Part)))
    assert db.scalar(select(func.count()).select_from(Cmm)) == 2
    assert db.scalar(select(func.count()).select_from(OwnershipRule)) == 5
    assert db.get(Setting, "guard_band_pct_default").value == 10

    qhead = db.scalars(select(User).where(User.email == user_email("qhead"))).one()
    assert qhead.role == Role.QUALITY_HEAD
    assert verify_password(qhead.password_hash, "test-demo-password")


def test_seed_is_idempotent(db):
    seed_masters(db)
    db.commit()
    seed_masters(db)
    db.commit()

    assert db.scalar(select(func.count()).select_from(Part)) == 3
    assert db.scalar(select(func.count()).select_from(Characteristic)) == 11
    assert db.scalar(select(func.count()).select_from(User)) == 7
