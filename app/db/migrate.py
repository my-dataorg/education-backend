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


def migrate_academic_years(engine: Engine) -> None:
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS academic_years (
                  id VARCHAR(36) PRIMARY KEY,
                  institute_id VARCHAR(36) NOT NULL REFERENCES institutes(id),
                  label VARCHAR(32) NOT NULL,
                  start_date DATE NOT NULL,
                  end_date DATE NOT NULL,
                  board VARCHAR(32) NOT NULL DEFAULT 'CBSE',
                  term_count INTEGER NOT NULL DEFAULT 2,
                  grading_scale VARCHAR(64) NOT NULL DEFAULT 'Marks + grade (A1–E)',
                  medium VARCHAR(64) NOT NULL DEFAULT 'English',
                  is_active BOOLEAN NOT NULL DEFAULT TRUE,
                  CONSTRAINT academic_years_institute_label UNIQUE (institute_id, label)
                );
                CREATE TABLE IF NOT EXISTS academic_terms (
                  id VARCHAR(36) PRIMARY KEY,
                  academic_year_id VARCHAR(36) NOT NULL REFERENCES academic_years(id),
                  name VARCHAR(64) NOT NULL,
                  start_date DATE NOT NULL,
                  end_date DATE NOT NULL,
                  weight_percent INTEGER NOT NULL DEFAULT 50,
                  CONSTRAINT academic_terms_year_name UNIQUE (academic_year_id, name)
                );
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
                    weekly_periods INTEGER,
                    UNIQUE (section_id, subject_id)
                );
                ALTER TABLE section_subjects
                ADD COLUMN IF NOT EXISTS weekly_periods INTEGER;
                CREATE TABLE IF NOT EXISTS teacher_subject_assignments (
                    id VARCHAR(36) PRIMARY KEY,
                    section_id VARCHAR(36) NOT NULL REFERENCES sections(id),
                    subject_id VARCHAR(36) NOT NULL REFERENCES subjects(id),
                    teacher_id VARCHAR(64) NOT NULL,
                    UNIQUE (section_id, subject_id, teacher_id)
                );
                CREATE TABLE IF NOT EXISTS section_subject_student_assignments (
                    id VARCHAR(36) PRIMARY KEY,
                    section_id VARCHAR(36) NOT NULL REFERENCES sections(id),
                    subject_id VARCHAR(36) NOT NULL REFERENCES subjects(id),
                    student_id VARCHAR(64) NOT NULL,
                    UNIQUE (section_id, subject_id, student_id)
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


def migrate_institute_rooms(engine: Engine) -> None:
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS institute_rooms (
                    id VARCHAR(36) PRIMARY KEY,
                    institute_id VARCHAR(36) NOT NULL REFERENCES institutes(id),
                    name VARCHAR(30) NOT NULL,
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


def migrate_special_days(engine: Engine) -> None:
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS schedule_special_days (
                    id VARCHAR(36) PRIMARY KEY,
                    institute_id VARCHAR(36) NOT NULL REFERENCES institutes(id),
                    special_date DATE NOT NULL,
                    label VARCHAR(100) NOT NULL,
                    replace_regular BOOLEAN NOT NULL DEFAULT TRUE,
                    UNIQUE (institute_id, special_date)
                );
                CREATE TABLE IF NOT EXISTS special_day_activities (
                    id VARCHAR(36) PRIMARY KEY,
                    special_day_id VARCHAR(36) NOT NULL REFERENCES schedule_special_days(id),
                    activity_id VARCHAR(36) NOT NULL REFERENCES activities(id),
                    start_time TIME NOT NULL,
                    end_time TIME NOT NULL,
                    position INTEGER NOT NULL
                );
                CREATE TABLE IF NOT EXISTS special_day_activity_sections (
                    special_activity_id VARCHAR(36) NOT NULL REFERENCES special_day_activities(id),
                    section_id VARCHAR(36) NOT NULL REFERENCES sections(id),
                    PRIMARY KEY (special_activity_id, section_id)
                );
                CREATE TABLE IF NOT EXISTS special_day_activity_teachers (
                    special_activity_id VARCHAR(36) NOT NULL REFERENCES special_day_activities(id),
                    teacher_id VARCHAR(64) NOT NULL,
                    PRIMARY KEY (special_activity_id, teacher_id)
                );
                CREATE INDEX IF NOT EXISTS schedule_special_days_institute_date_idx
                    ON schedule_special_days (institute_id, special_date);
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


def migrate_teacher_workspace(engine: Engine) -> None:
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                ALTER TABLE assignments
                ADD COLUMN IF NOT EXISTS assignment_type VARCHAR(16) NOT NULL DEFAULT 'assignment'
                """
            )
        )
        conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS attendance_records (
                    id VARCHAR(36) PRIMARY KEY,
                    section_id VARCHAR(36) NOT NULL REFERENCES sections(id),
                    student_id VARCHAR(64) NOT NULL,
                    attendance_date DATE NOT NULL,
                    status VARCHAR(16) NOT NULL,
                    marked_by VARCHAR(64) NOT NULL,
                    UNIQUE (section_id, student_id, attendance_date)
                )
                """
            )
        )


def migrate_institute_role_settings(engine: Engine) -> None:
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS institute_role_settings (
                    institute_id VARCHAR(36) PRIMARY KEY REFERENCES institutes(id),
                    principal_can_edit_timetable BOOLEAN NOT NULL DEFAULT TRUE,
                    absence_alert_days INTEGER NOT NULL DEFAULT 3
                );
                """
            )
        )
        conn.execute(
            text(
                """
                ALTER TABLE institute_role_settings
                ADD COLUMN IF NOT EXISTS absence_alert_days INTEGER NOT NULL DEFAULT 3
                """
            )
        )


def migrate_timetable_substitutions(engine: Engine) -> None:
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS timetable_substitutions (
                    id VARCHAR(36) PRIMARY KEY,
                    institute_id VARCHAR(36) NOT NULL REFERENCES institutes(id),
                    substitution_date DATE NOT NULL,
                    slot_id VARCHAR(36) NOT NULL REFERENCES schedule_slots(id),
                    section_id VARCHAR(36) NOT NULL REFERENCES sections(id),
                    original_teacher_id VARCHAR(64) NOT NULL,
                    substitute_teacher_id VARCHAR(64) NOT NULL,
                    UNIQUE (institute_id, substitution_date, slot_id, section_id)
                );
                """
            )
        )


def migrate_timetable_publish(engine: Engine) -> None:
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                ALTER TABLE timetable_entries
                ADD COLUMN IF NOT EXISTS room VARCHAR(30)
                """
            )
        )
        conn.execute(
            text(
                """
                ALTER TABLE timetable_entries
                ADD COLUMN IF NOT EXISTS locked BOOLEAN NOT NULL DEFAULT FALSE
                """
            )
        )
        conn.execute(
            text(
                """
                ALTER TABLE schedule_settings
                ADD COLUMN IF NOT EXISTS published_at TIMESTAMPTZ
                """
            )
        )
        conn.execute(
            text(
                """
                ALTER TABLE schedule_settings
                ADD COLUMN IF NOT EXISTS draft_saved_at TIMESTAMPTZ
                """
            )
        )
        conn.execute(
            text(
                """
                ALTER TABLE section_subjects
                ADD COLUMN IF NOT EXISTS weekly_periods INTEGER
                """
            )
        )
        conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS published_timetable_entries (
                    id VARCHAR(36) PRIMARY KEY,
                    institute_id VARCHAR(36) NOT NULL REFERENCES institutes(id),
                    slot_id VARCHAR(36) NOT NULL REFERENCES schedule_slots(id),
                    day_of_week INTEGER NOT NULL,
                    section_id VARCHAR(36) NOT NULL REFERENCES sections(id),
                    subject_id VARCHAR(36) NOT NULL REFERENCES subjects(id),
                    teacher_id VARCHAR(64),
                    room VARCHAR(30),
                    locked BOOLEAN NOT NULL DEFAULT FALSE,
                    UNIQUE (slot_id, day_of_week, section_id)
                )
                """
            )
        )


def migrate_institute_posts(engine: Engine) -> None:
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS institute_posts (
                    id VARCHAR(36) PRIMARY KEY,
                    institute_id VARCHAR(36) NOT NULL REFERENCES institutes(id),
                    title VARCHAR(200) NOT NULL,
                    body TEXT NOT NULL,
                    posted_by VARCHAR(64) NOT NULL,
                    created_at TIMESTAMPTZ DEFAULT NOW()
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


def migrate_mvp_domains(engine: Engine) -> None:
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                ALTER TABLE institute_posts
                ADD COLUMN IF NOT EXISTS audience VARCHAR(32) NOT NULL DEFAULT 'everyone';
                ALTER TABLE institute_posts
                ADD COLUMN IF NOT EXISTS target_section_ids TEXT NOT NULL DEFAULT '';
                CREATE TABLE IF NOT EXISTS institute_calendar_events (
                    id VARCHAR(36) PRIMARY KEY,
                    institute_id VARCHAR(36) NOT NULL REFERENCES institutes(id),
                    branch_id VARCHAR(36) REFERENCES branches(id),
                    title VARCHAR(200) NOT NULL,
                    description TEXT NOT NULL DEFAULT '',
                    event_date DATE NOT NULL,
                    created_by VARCHAR(64) NOT NULL,
                    created_at TIMESTAMPTZ DEFAULT NOW()
                );
                ALTER TABLE institute_posts
                ADD COLUMN IF NOT EXISTS target_user_ids TEXT NOT NULL DEFAULT '';
                ALTER TABLE institute_posts
                ADD COLUMN IF NOT EXISTS student_gender VARCHAR(16);
                ALTER TABLE institute_posts
                ADD COLUMN IF NOT EXISTS distribution_list_id VARCHAR(36);
                CREATE TABLE IF NOT EXISTS notice_distribution_lists (
                    id VARCHAR(36) PRIMARY KEY,
                    institute_id VARCHAR(36) NOT NULL REFERENCES institutes(id),
                    name VARCHAR(120) NOT NULL,
                    audience VARCHAR(32) NOT NULL DEFAULT 'everyone',
                    target_section_ids TEXT NOT NULL DEFAULT '',
                    target_user_ids TEXT NOT NULL DEFAULT '',
                    student_gender VARCHAR(16),
                    created_at TIMESTAMPTZ DEFAULT NOW(),
                    UNIQUE (institute_id, name)
                );
                ALTER TABLE institute_calendar_events
                ADD COLUMN IF NOT EXISTS audience VARCHAR(32) NOT NULL DEFAULT 'everyone';
                ALTER TABLE institute_calendar_events
                ADD COLUMN IF NOT EXISTS target_section_ids TEXT NOT NULL DEFAULT '';
                ALTER TABLE institute_calendar_events
                ADD COLUMN IF NOT EXISTS target_user_ids TEXT NOT NULL DEFAULT '';
                ALTER TABLE institute_calendar_events
                ADD COLUMN IF NOT EXISTS student_gender VARCHAR(16);
                ALTER TABLE institute_calendar_events
                ADD COLUMN IF NOT EXISTS distribution_list_id VARCHAR(36);
                CREATE TABLE IF NOT EXISTS exams (
                    id VARCHAR(36) PRIMARY KEY,
                    institute_id VARCHAR(36) NOT NULL REFERENCES institutes(id),
                    academic_year_id VARCHAR(36) REFERENCES academic_years(id),
                    section_id VARCHAR(36) REFERENCES sections(id),
                    subject_id VARCHAR(36) REFERENCES subjects(id),
                    name VARCHAR(200) NOT NULL,
                    max_marks INTEGER NOT NULL DEFAULT 100,
                    scheduled_at DATE,
                    status VARCHAR(16) NOT NULL DEFAULT 'draft',
                    created_by VARCHAR(64) NOT NULL,
                    created_at TIMESTAMPTZ DEFAULT NOW()
                );
                CREATE TABLE IF NOT EXISTS mark_entries (
                    id VARCHAR(36) PRIMARY KEY,
                    exam_id VARCHAR(36) NOT NULL REFERENCES exams(id),
                    student_id VARCHAR(64) NOT NULL,
                    subject_id VARCHAR(36) REFERENCES subjects(id),
                    marks_obtained INTEGER,
                    remarks VARCHAR(500) NOT NULL DEFAULT '',
                    UNIQUE (exam_id, student_id, subject_id)
                );
                CREATE TABLE IF NOT EXISTS fee_structures (
                    id VARCHAR(36) PRIMARY KEY,
                    institute_id VARCHAR(36) NOT NULL REFERENCES institutes(id),
                    academic_year_id VARCHAR(36) REFERENCES academic_years(id),
                    name VARCHAR(200) NOT NULL,
                    amount_paise INTEGER NOT NULL,
                    UNIQUE (institute_id, academic_year_id, name)
                );
                CREATE TABLE IF NOT EXISTS student_fees (
                    id VARCHAR(36) PRIMARY KEY,
                    institute_id VARCHAR(36) NOT NULL REFERENCES institutes(id),
                    student_id VARCHAR(64) NOT NULL,
                    fee_structure_id VARCHAR(36) NOT NULL REFERENCES fee_structures(id),
                    amount_paise INTEGER NOT NULL,
                    paid_paise INTEGER NOT NULL DEFAULT 0,
                    UNIQUE (institute_id, student_id, fee_structure_id)
                );
                CREATE TABLE IF NOT EXISTS payments (
                    id VARCHAR(36) PRIMARY KEY,
                    institute_id VARCHAR(36) NOT NULL REFERENCES institutes(id),
                    student_id VARCHAR(64) NOT NULL,
                    amount_paise INTEGER NOT NULL,
                    method VARCHAR(32) NOT NULL DEFAULT 'cash',
                    reference VARCHAR(200) NOT NULL DEFAULT '',
                    receipt_number VARCHAR(64) NOT NULL,
                    recorded_by VARCHAR(64) NOT NULL,
                    created_at TIMESTAMPTZ DEFAULT NOW()
                );
                """
            )
        )


def migrate_institute_profile(engine: Engine) -> None:
    with engine.begin() as conn:
        for table, columns in (
            (
                "institutes",
                (
                    ("description", "TEXT DEFAULT ''"),
                    ("email", "VARCHAR(200) DEFAULT ''"),
                    ("phone", "VARCHAR(32) DEFAULT ''"),
                    ("website", "VARCHAR(300) DEFAULT ''"),
                    ("address", "VARCHAR(500) DEFAULT ''"),
                    ("city", "VARCHAR(100) DEFAULT ''"),
                    ("state", "VARCHAR(100) DEFAULT ''"),
                    ("postal_code", "VARCHAR(20) DEFAULT ''"),
                ),
            ),
            (
                "branches",
                (
                    ("state", "VARCHAR(100) DEFAULT ''"),
                    ("postal_code", "VARCHAR(20) DEFAULT ''"),
                    ("email", "VARCHAR(200) DEFAULT ''"),
                    ("phone", "VARCHAR(32) DEFAULT ''"),
                ),
            ),
        ):
            for column, definition in columns:
                conn.execute(
                    text(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {column} {definition}")
                )


def migrate_parent_guardian_messaging(engine: Engine) -> None:
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS guardian_link_cache (
                    guardian_user_id VARCHAR(64) PRIMARY KEY,
                    student_ids_json TEXT NOT NULL DEFAULT '[]',
                    expires_at TIMESTAMPTZ NOT NULL
                );
                CREATE TABLE IF NOT EXISTS parent_teacher_threads (
                    id VARCHAR(36) PRIMARY KEY,
                    institute_id VARCHAR(36) NOT NULL REFERENCES institutes(id),
                    student_id VARCHAR(64) NOT NULL,
                    subject VARCHAR(200) NOT NULL,
                    created_by_user_id VARCHAR(64) NOT NULL,
                    status VARCHAR(16) NOT NULL DEFAULT 'open',
                    created_at TIMESTAMPTZ DEFAULT NOW()
                );
                CREATE TABLE IF NOT EXISTS parent_teacher_messages (
                    id VARCHAR(36) PRIMARY KEY,
                    thread_id VARCHAR(36) NOT NULL REFERENCES parent_teacher_threads(id),
                    sender_user_id VARCHAR(64) NOT NULL,
                    body TEXT NOT NULL,
                    sent_at TIMESTAMPTZ DEFAULT NOW()
                );
                """
            )
        )


def migrate_section_class_teacher(engine: Engine) -> None:
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                ALTER TABLE sections
                ADD COLUMN IF NOT EXISTS class_teacher_user_id VARCHAR(64)
                """
            )
        )


def migrate_section_attendance_days(engine: Engine) -> None:
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS section_attendance_days (
                  section_id VARCHAR(36) NOT NULL REFERENCES sections(id),
                  attendance_date DATE NOT NULL,
                  publish_state VARCHAR(16) NOT NULL DEFAULT 'submitted',
                  marked_by VARCHAR(64) NOT NULL,
                  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                  PRIMARY KEY (section_id, attendance_date)
                );
                """
            )
        )


def migrate_assignment_works(engine: Engine) -> None:
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                ALTER TABLE assignments
                  ADD COLUMN IF NOT EXISTS publish_state VARCHAR(16) NOT NULL DEFAULT 'published';
                ALTER TABLE assignments
                  ADD COLUMN IF NOT EXISTS publish_at TIMESTAMPTZ;
                ALTER TABLE assignments
                  ADD COLUMN IF NOT EXISTS due_at TIMESTAMPTZ;
                ALTER TABLE assignments
                  ADD COLUMN IF NOT EXISTS audience_type VARCHAR(16) NOT NULL DEFAULT 'section';
                ALTER TABLE assignments
                  ADD COLUMN IF NOT EXISTS instructions TEXT NOT NULL DEFAULT '';
                ALTER TABLE assignments
                  ADD COLUMN IF NOT EXISTS scores_visible BOOLEAN NOT NULL DEFAULT false;
                ALTER TABLE assignments
                  ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW();

                CREATE TABLE IF NOT EXISTS assignment_audience_students (
                  assignment_id VARCHAR(36) NOT NULL REFERENCES assignments(id) ON DELETE CASCADE,
                  student_id VARCHAR(64) NOT NULL,
                  PRIMARY KEY (assignment_id, student_id)
                );

                CREATE TABLE IF NOT EXISTS assignment_questions (
                  id VARCHAR(36) PRIMARY KEY,
                  assignment_id VARCHAR(36) NOT NULL REFERENCES assignments(id) ON DELETE CASCADE,
                  sort_order INT NOT NULL DEFAULT 0,
                  question_type VARCHAR(32) NOT NULL,
                  points DOUBLE PRECISION NOT NULL DEFAULT 1,
                  required BOOLEAN NOT NULL DEFAULT true
                );

                CREATE TABLE IF NOT EXISTS assignment_question_variants (
                  id VARCHAR(36) PRIMARY KEY,
                  question_id VARCHAR(36) NOT NULL REFERENCES assignment_questions(id) ON DELETE CASCADE,
                  variant_index INT NOT NULL DEFAULT 0,
                  stem_text TEXT NOT NULL DEFAULT '',
                  metadata_json TEXT NOT NULL DEFAULT '{}'
                );

                CREATE TABLE IF NOT EXISTS assignment_question_options (
                  id VARCHAR(36) PRIMARY KEY,
                  variant_id VARCHAR(36) NOT NULL REFERENCES assignment_question_variants(id) ON DELETE CASCADE,
                  option_key VARCHAR(16) NOT NULL,
                  label TEXT NOT NULL DEFAULT '',
                  is_correct BOOLEAN NOT NULL DEFAULT false
                );

                CREATE TABLE IF NOT EXISTS assignment_attempts (
                  id VARCHAR(36) PRIMARY KEY,
                  assignment_id VARCHAR(36) NOT NULL REFERENCES assignments(id) ON DELETE CASCADE,
                  student_id VARCHAR(64) NOT NULL,
                  snapshot_json TEXT NOT NULL DEFAULT '{}',
                  status VARCHAR(16) NOT NULL DEFAULT 'in_progress',
                  submitted_at TIMESTAMPTZ,
                  score DOUBLE PRECISION,
                  max_score DOUBLE PRECISION,
                  UNIQUE (assignment_id, student_id)
                );

                CREATE TABLE IF NOT EXISTS assignment_responses (
                  id VARCHAR(36) PRIMARY KEY,
                  attempt_id VARCHAR(36) NOT NULL REFERENCES assignment_attempts(id) ON DELETE CASCADE,
                  question_id VARCHAR(36) NOT NULL REFERENCES assignment_questions(id) ON DELETE CASCADE,
                  answer_json TEXT NOT NULL DEFAULT '{}',
                  auto_score DOUBLE PRECISION,
                  teacher_score DOUBLE PRECISION,
                  feedback TEXT NOT NULL DEFAULT '',
                  UNIQUE (attempt_id, question_id)
                );
                """
            )
        )


def migrate_student_leave_requests(engine: Engine) -> None:
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS student_leave_requests (
                  id VARCHAR(36) PRIMARY KEY,
                  section_id VARCHAR(36) NOT NULL REFERENCES sections(id),
                  student_id VARCHAR(64) NOT NULL,
                  start_date DATE NOT NULL,
                  end_date DATE NOT NULL,
                  reason TEXT NOT NULL DEFAULT '',
                  status VARCHAR(16) NOT NULL DEFAULT 'pending',
                  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                );
                CREATE INDEX IF NOT EXISTS student_leave_requests_section_idx
                  ON student_leave_requests(section_id, status);
                """
            )
        )


def migrate_section_syllabus(engine: Engine) -> None:
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS section_syllabus_nodes (
                  id VARCHAR(36) PRIMARY KEY,
                  section_id VARCHAR(36) NOT NULL REFERENCES sections(id) ON DELETE CASCADE,
                  subject_id VARCHAR(36) NOT NULL REFERENCES subjects(id) ON DELETE CASCADE,
                  parent_id VARCHAR(36) REFERENCES section_syllabus_nodes(id) ON DELETE CASCADE,
                  title VARCHAR(200) NOT NULL,
                  weight_percent DOUBLE PRECISION NOT NULL,
                  sort_order INTEGER NOT NULL DEFAULT 0,
                  completed_percent DOUBLE PRECISION NOT NULL DEFAULT 0,
                  completed_by_user_id VARCHAR(64),
                  completed_at TIMESTAMPTZ
                );
                CREATE INDEX IF NOT EXISTS section_syllabus_nodes_section_subject_idx
                  ON section_syllabus_nodes(section_id, subject_id);
                """
            )
        )


def migrate_timetable_school_defaults(engine: Engine) -> None:
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS timetable_school_defaults (
                  id VARCHAR(36) PRIMARY KEY,
                  institute_id VARCHAR(36) NOT NULL REFERENCES institutes(id),
                  slot_id VARCHAR(36) NOT NULL REFERENCES schedule_slots(id),
                  day_of_week INTEGER NOT NULL,
                  subject_id VARCHAR(36) NOT NULL REFERENCES subjects(id),
                  teacher_id VARCHAR(64),
                  room VARCHAR(30),
                  CONSTRAINT timetable_school_defaults_unique
                    UNIQUE (institute_id, slot_id, day_of_week)
                );
                """
            )
        )


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
