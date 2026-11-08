"""audit_log append-only trigger

Revision ID: 0002
Revises: 0001
Create Date: 2026-11-08

Section 16: a trigger raises on UPDATE or DELETE of audit_log. TRUNCATE stays possible for the
admin-only `make demo-reset`, which wipes the whole demo database.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE OR REPLACE FUNCTION audit_log_reject_change() RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION 'audit_log is append-only: % is not allowed', TG_OP
                USING ERRCODE = 'insufficient_privilege';
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE TRIGGER audit_log_append_only
        BEFORE UPDATE OR DELETE ON audit_log
        FOR EACH ROW EXECUTE FUNCTION audit_log_reject_change();
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS audit_log_append_only ON audit_log")
    op.execute("DROP FUNCTION IF EXISTS audit_log_reject_change()")
