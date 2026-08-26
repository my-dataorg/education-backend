import uuid

from sqlalchemy import func, select, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from app.models import Branch, Class, Institute, Section


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
                CREATE UNIQUE INDEX IF NOT EXISTS institute_invitations_email_status_idx
                ON institute_invitations (institute_id, lower(invitee_email), status)
                WHERE invitee_email <> ''
                """
            )
        )
        conn.execute(
            text(
                """
                CREATE UNIQUE INDEX IF NOT EXISTS institute_invitations_user_status_idx
                ON institute_invitations (institute_id, invitee_user_id, status)
                WHERE invitee_user_id IS NOT NULL
                """
            )
        )


def migrate_subjects(engine: Engine) -> None:
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                ALTER TABLE section_members
                ADD COLUMN IF NOT EXISTS subject_id VARCHAR(36)
                """
            )
        )
        conn.execute(
            text(
                """
                ALTER TABLE section_members
                DROP CONSTRAINT IF EXISTS section_members_section_id_user_id_member_type_key
                """
            )
        )
        conn.execute(
            text(
                """
                DO $$
                BEGIN
                  IF NOT EXISTS (
                    SELECT 1 FROM pg_constraint WHERE conname = 'section_members_subject_id_fkey'
                  ) THEN
                    ALTER TABLE section_members
                    ADD CONSTRAINT section_members_subject_id_fkey
                    FOREIGN KEY (subject_id) REFERENCES subjects(id);
                  END IF;
                EXCEPTION
                  WHEN undefined_table THEN NULL;
                END $$;
                """
            )
        )
        conn.execute(
            text(
                """
                CREATE UNIQUE INDEX IF NOT EXISTS section_members_student_unique
                ON section_members (section_id, user_id)
                WHERE member_type = 'student'
                """
            )
        )
        conn.execute(
            text(
                """
                CREATE UNIQUE INDEX IF NOT EXISTS section_members_teacher_subject_unique
                ON section_members (section_id, subject_id)
                WHERE member_type = 'teacher' AND subject_id IS NOT NULL
                """
            )
        )


def migrate_grade_bands(engine: Engine) -> None:
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                ALTER TABLE sections
                ADD COLUMN IF NOT EXISTS grade_band VARCHAR(16) DEFAULT 'primary'
                """
            )
        )
        conn.execute(
            text(
                """
                UPDATE sections SET grade_band = 'primary' WHERE grade_band IS NULL OR grade_band = ''
                """
            )
        )
        conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS teacher_grade_bands (
                    id VARCHAR(36) PRIMARY KEY,
                    institute_id VARCHAR(36) NOT NULL REFERENCES institutes(id),
                    user_id VARCHAR(64) NOT NULL,
                    grade_band VARCHAR(16) NOT NULL,
                    UNIQUE (institute_id, user_id, grade_band)
                )
                """
            )
        )
        conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS periods (
                    id VARCHAR(36) PRIMARY KEY,
                    institute_id VARCHAR(36) NOT NULL REFERENCES institutes(id),
                    section_id VARCHAR(36) NOT NULL REFERENCES sections(id),
                    subject_id VARCHAR(36) NOT NULL REFERENCES subjects(id),
                    teacher_user_id VARCHAR(64) NOT NULL,
                    semester VARCHAR(80) NOT NULL,
                    weekday VARCHAR(80) NOT NULL,
                    start_time VARCHAR(5) NOT NULL,
                    duration_minutes INTEGER DEFAULT 60
                )
                """
            )
        )
        conn.execute(
            text(
                """
                ALTER TABLE periods
                ADD COLUMN IF NOT EXISTS weekday VARCHAR(80)
                """
            )
        )
        conn.execute(
            text(
                """
                ALTER TABLE periods
                ADD COLUMN IF NOT EXISTS start_time VARCHAR(5)
                """
            )
        )
        conn.execute(
            text(
                """
                DO $$
                BEGIN
                  ALTER TABLE periods ALTER COLUMN weekday TYPE VARCHAR(80);
                EXCEPTION
                  WHEN undefined_column THEN NULL;
                  WHEN undefined_table THEN NULL;
                END $$;
                """
            )
        )
        conn.execute(
            text(
                """
                ALTER TABLE periods
                ADD COLUMN IF NOT EXISTS semester VARCHAR(80) DEFAULT ''
                """
            )
        )
        conn.execute(
            text(
                """
                DO $$
                BEGIN
                  ALTER TABLE periods ALTER COLUMN starts_at DROP NOT NULL;
                EXCEPTION
                  WHEN undefined_column THEN NULL;
                  WHEN undefined_table THEN NULL;
                END $$;
                """
            )
        )
        conn.execute(
            text(
                """
                DO $$
                BEGIN
                  UPDATE periods
                  SET weekday = lower(trim(to_char(starts_at AT TIME ZONE 'UTC', 'Day'))),
                      start_time = to_char(starts_at AT TIME ZONE 'UTC', 'HH24:MI')
                  WHERE (weekday IS NULL OR weekday = '')
                    AND starts_at IS NOT NULL;
                EXCEPTION
                  WHEN undefined_column THEN NULL;
                  WHEN undefined_table THEN NULL;
                END $$;
                """
            )
        )


def migrate_classes(engine: Engine) -> None:
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS classes (
                    id VARCHAR(36) PRIMARY KEY,
                    institute_id VARCHAR(36) NOT NULL REFERENCES institutes(id),
                    name VARCHAR(200) NOT NULL,
                    grade_band VARCHAR(16) NOT NULL DEFAULT 'primary',
                    UNIQUE (institute_id, name)
                )
                """
            )
        )
        conn.execute(
            text(
                """
                ALTER TABLE sections
                ADD COLUMN IF NOT EXISTS class_id VARCHAR(36)
                """
            )
        )
        # Rows are linked in seed_classes() after create_all.
        conn.execute(
            text(
                """
                DO $$
                BEGIN
                  IF NOT EXISTS (
                    SELECT 1 FROM pg_constraint WHERE conname = 'sections_class_id_fkey'
                  ) THEN
                    ALTER TABLE sections
                    ADD CONSTRAINT sections_class_id_fkey
                    FOREIGN KEY (class_id) REFERENCES classes(id);
                  END IF;
                EXCEPTION
                  WHEN undefined_table THEN NULL;
                END $$;
                """
            )
        )
        conn.execute(
            text(
                """
                ALTER TABLE daily_notes
                ADD COLUMN IF NOT EXISTS subject_id VARCHAR(36)
                """
            )
        )
        conn.execute(
            text(
                """
                ALTER TABLE assignments
                ADD COLUMN IF NOT EXISTS subject_id VARCHAR(36)
                """
            )
        )
        conn.execute(
            text(
                """
                DO $$
                BEGIN
                  IF NOT EXISTS (
                    SELECT 1 FROM pg_constraint WHERE conname = 'daily_notes_subject_id_fkey'
                  ) THEN
                    ALTER TABLE daily_notes
                    ADD CONSTRAINT daily_notes_subject_id_fkey
                    FOREIGN KEY (subject_id) REFERENCES subjects(id);
                  END IF;
                EXCEPTION
                  WHEN undefined_table THEN NULL;
                END $$;
                """
            )
        )
        conn.execute(
            text(
                """
                DO $$
                BEGIN
                  IF NOT EXISTS (
                    SELECT 1 FROM pg_constraint WHERE conname = 'assignments_subject_id_fkey'
                  ) THEN
                    ALTER TABLE assignments
                    ADD CONSTRAINT assignments_subject_id_fkey
                    FOREIGN KEY (subject_id) REFERENCES subjects(id);
                  END IF;
                EXCEPTION
                  WHEN undefined_table THEN NULL;
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


def seed_classes(db: Session) -> None:
    """Attach existing sections to Class rows (one class per institute + name)."""
    sections = list(db.scalars(select(Section).where(Section.class_id.is_(None))))
    if not sections:
        return
    cache: dict[tuple[str, str], Class] = {}
    for existing in db.scalars(select(Class)):
        cache[(existing.institute_id, existing.name)] = existing
    for section in sections:
        name = (section.class_name or "").strip() or "Unnamed class"
        key = (section.institute_id, name)
        row = cache.get(key)
        if not row:
            row = Class(
                id=str(uuid.uuid4()),
                institute_id=section.institute_id,
                name=name,
                grade_band=section.grade_band or "primary",
            )
            db.add(row)
            cache[key] = row
        section.class_id = row.id
        section.class_name = row.name
        section.grade_band = row.grade_band
    db.commit()


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
