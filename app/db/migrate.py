from sqlalchemy import func, select, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from app.models import Activity, Branch, Institute


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
                ALTER TABLE institute_invitations
                DROP CONSTRAINT IF EXISTS institute_invitations_institute_id_invitee_email_status_key
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
                    WHERE conname = 'institute_invitations_institute_id_invitee_user_id_status_key'
                  ) THEN
                    ALTER TABLE institute_invitations
                    ADD CONSTRAINT institute_invitations_institute_id_invitee_user_id_status_key
                    UNIQUE (institute_id, invitee_user_id, status);
                  END IF;
                END $$;
                """
            )
        )


def migrate_join_requests(engine: Engine) -> None:
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS institute_join_requests (
                    id VARCHAR(36) PRIMARY KEY,
                    institute_id VARCHAR(36) NOT NULL REFERENCES institutes(id),
                    user_id VARCHAR(64) NOT NULL,
                    requested_role VARCHAR(32) NOT NULL,
                    message TEXT DEFAULT '',
                    status VARCHAR(16) DEFAULT 'pending',
                    reviewed_by VARCHAR(64),
                    created_at TIMESTAMPTZ DEFAULT NOW(),
                    responded_at TIMESTAMPTZ,
                    UNIQUE (institute_id, user_id, status)
                )
                """
            )
        )


def migrate_subjects(engine: Engine) -> None:
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS subjects (
                    id VARCHAR(36) PRIMARY KEY,
                    institute_id VARCHAR(36) NOT NULL REFERENCES institutes(id),
                    name VARCHAR(200) NOT NULL,
                    UNIQUE (institute_id, name)
                );
                CREATE TABLE IF NOT EXISTS section_subjects (
                    id VARCHAR(36) PRIMARY KEY,
                    section_id VARCHAR(36) NOT NULL REFERENCES sections(id),
                    subject_id VARCHAR(36) NOT NULL REFERENCES subjects(id),
                    UNIQUE (section_id, subject_id)
                );
                CREATE TABLE IF NOT EXISTS teacher_subject_assignments (
                    id VARCHAR(36) PRIMARY KEY,
                    section_id VARCHAR(36) NOT NULL REFERENCES sections(id),
                    subject_id VARCHAR(36) NOT NULL REFERENCES subjects(id),
                    teacher_id VARCHAR(64) NOT NULL,
                    UNIQUE (section_id, subject_id, teacher_id)
                );
                """
            )
        )


def migrate_activities(engine: Engine) -> None:
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS activities (
                    id VARCHAR(36) PRIMARY KEY,
                    institute_id VARCHAR(36) NOT NULL REFERENCES institutes(id),
                    name VARCHAR(100) NOT NULL,
                    is_system BOOLEAN NOT NULL DEFAULT FALSE,
                    UNIQUE (institute_id, name)
                );
                """
            )
        )


def migrate_schedule(engine: Engine) -> None:
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS schedule_settings (
                    institute_id VARCHAR(36) PRIMARY KEY REFERENCES institutes(id),
                    timezone VARCHAR(64) NOT NULL DEFAULT 'Asia/Kolkata',
                    school_start TIME NOT NULL DEFAULT '08:00',
                    school_end TIME NOT NULL DEFAULT '15:00',
                    weekdays VARCHAR(32) NOT NULL DEFAULT '1,2,3,4,5,6',
                    revision INTEGER NOT NULL DEFAULT 1
                );
                CREATE TABLE IF NOT EXISTS schedule_slots (
                    id VARCHAR(36) PRIMARY KEY,
                    institute_id VARCHAR(36) NOT NULL REFERENCES institutes(id),
                    label VARCHAR(100) NOT NULL,
                    kind VARCHAR(16) NOT NULL DEFAULT 'instruction',
                    start_time TIME NOT NULL,
                    end_time TIME NOT NULL,
                    position INTEGER NOT NULL,
                    day_of_week INTEGER,
                    UNIQUE (institute_id, position)
                );
                CREATE TABLE IF NOT EXISTS timetable_entries (
                    id VARCHAR(36) PRIMARY KEY,
                    institute_id VARCHAR(36) NOT NULL REFERENCES institutes(id),
                    slot_id VARCHAR(36) NOT NULL REFERENCES schedule_slots(id),
                    day_of_week INTEGER NOT NULL,
                    section_id VARCHAR(36) NOT NULL REFERENCES sections(id),
                    subject_id VARCHAR(36) NOT NULL REFERENCES subjects(id),
                    teacher_id VARCHAR(64),
                    UNIQUE (slot_id, day_of_week, section_id)
                );
                """
            )
        )
        conn.execute(
            text(
                """
                ALTER TABLE schedule_slots
                ADD COLUMN IF NOT EXISTS day_of_week INTEGER
                """
            )
        )
        conn.execute(
            text(
                """
                ALTER TABLE schedule_slots
                ADD COLUMN IF NOT EXISTS activity_id VARCHAR(36)
                """
            )
        )
        conn.execute(
            text(
                """
                DO $$
                BEGIN
                  IF NOT EXISTS (
                    SELECT 1 FROM pg_constraint WHERE conname = 'schedule_slots_activity_id_fkey'
                  ) THEN
                    ALTER TABLE schedule_slots
                    ADD CONSTRAINT schedule_slots_activity_id_fkey
                    FOREIGN KEY (activity_id) REFERENCES activities(id);
                  END IF;
                EXCEPTION
                  WHEN undefined_table THEN NULL;
                END $$;
                """
            )
        )


def migrate_teacher_absences(engine: Engine) -> None:
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS teacher_absences (
                    id VARCHAR(36) PRIMARY KEY,
                    institute_id VARCHAR(36) NOT NULL REFERENCES institutes(id),
                    teacher_id VARCHAR(64) NOT NULL,
                    absence_date DATE NOT NULL,
                    substitute_teacher_id VARCHAR(64),
                    note VARCHAR(500) NOT NULL DEFAULT '',
                    UNIQUE (institute_id, teacher_id, absence_date)
                )
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


def seed_default_activities(db: Session) -> None:
    """Create the standard non-subject schedule activities for every institute."""
    institute_ids = db.scalars(select(Institute.id)).all()
    added = False
    for institute_id in institute_ids:
        existing = set(
            db.scalars(
                select(Activity.name).where(Activity.institute_id == institute_id)
            )
        )
        for name in ("Break", "Play time", "Lunch time"):
            if name not in existing:
                db.add(Activity(institute_id=institute_id, name=name, is_system=True))
                added = True
    if added:
        db.commit()
