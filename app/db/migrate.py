from sqlalchemy import func, select, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from app.models import Branch, Institute


def run_migrations(engine: Engine) -> None:
    """Apply lightweight schema updates for local dev (no Alembic)."""
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                ALTER TABLE sections
                ADD COLUMN IF NOT EXISTS branch_id VARCHAR(36)
                """
            )
        )
        conn.execute(
            text(
                """
                DO $$
                BEGIN
                  IF NOT EXISTS (
                    SELECT 1 FROM pg_constraint WHERE conname = 'sections_branch_id_fkey'
                  ) THEN
                    ALTER TABLE sections
                    ADD CONSTRAINT sections_branch_id_fkey
                    FOREIGN KEY (branch_id) REFERENCES branches(id);
                  END IF;
                EXCEPTION
                  WHEN undefined_table THEN NULL;
                END $$;
                """
            )
        )


def migrate_invitations(engine: Engine) -> None:
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                ALTER TABLE institute_invitations
                ADD COLUMN IF NOT EXISTS invitee_email VARCHAR(200) DEFAULT ''
                """
            )
        )
        conn.execute(
            text(
                """
                ALTER TABLE institute_invitations
                ALTER COLUMN invitee_user_id DROP NOT NULL
                """
            )
        )
        conn.execute(
            text(
                """
                ALTER TABLE institute_invitations
                DROP CONSTRAINT IF EXISTS institute_invitations_institute_id_invitee_user_id_status_key
                """
            )
        )
        conn.execute(
            text(
                """
                DO $$
                BEGIN
                  IF NOT EXISTS (
                    SELECT 1 FROM pg_constraint
                    WHERE conname = 'institute_invitations_institute_id_invitee_email_status_key'
                  ) THEN
                    ALTER TABLE institute_invitations
                    ADD CONSTRAINT institute_invitations_institute_id_invitee_email_status_key
                    UNIQUE (institute_id, invitee_email, status);
                  END IF;
                END $$;
                """
            )
        )


def seed_default_branches(db: Session) -> None:
    """Give existing institutes a primary branch if they have none."""
    institute_ids = db.scalars(select(Institute.id)).all()
    added = False
    for institute_id in institute_ids:
        count = db.scalar(
            select(func.count()).select_from(Branch).where(Branch.institute_id == institute_id)
        )
        if not count:
            db.add(
                Branch(
                    institute_id=institute_id,
                    name="Main campus",
                    address="",
                    city="",
                    is_primary=True,
                )
            )
            added = True
    if added:
        db.commit()
