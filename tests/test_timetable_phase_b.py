from datetime import date, datetime, time

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app import main
from app.db.session import get_db
from app.models import (
    Activity,
    Base,
    Institute,
    InstituteMember,
    InstituteRoleSettings,
    ScheduleSettings,
    ScheduleSlot,
    Section,
    SectionSubject,
    Subject,
    TeacherAbsence,
    TeacherSubjectAssignment,
    TimetableEntry,
)


@pytest.fixture
def db():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def client(db: Session):
    def override_db():
        yield db

    main.app.dependency_overrides[get_db] = override_db
    main.app.dependency_overrides[main.require_education_subscription] = (
        lambda: {"id": "owner", "email": "owner@example.com", "token": "test"}
    )
    yield TestClient(main.app)
    main.app.dependency_overrides.clear()


def seed_timetable(db: Session) -> tuple[Institute, Section, Subject, str, int]:
    day = date.today().isoweekday()
    institute = Institute(id="inst-1", name="School", join_code="SCH1")
    section = Section(id="sec-1", institute_id=institute.id, name="A", class_name="9")
    subject = Subject(id="eng", institute_id=institute.id, name="English")
    db.add_all(
        [
            institute,
            section,
            subject,
            InstituteMember(institute_id=institute.id, user_id="owner", role="owner"),
            InstituteMember(institute_id=institute.id, user_id="teacher-1", role="teacher"),
            SectionSubject(section_id=section.id, subject_id=subject.id, weekly_periods=2),
            TeacherSubjectAssignment(
                section_id=section.id, subject_id=subject.id, teacher_id="teacher-1"
            ),
            ScheduleSettings(institute_id=institute.id, weekdays=str(day)),
        ]
    )
    slot = ScheduleSlot(
        id="slot-1",
        institute_id=institute.id,
        label="P1",
        kind="instruction",
        start_time=time(8, 0),
        end_time=time(8, 45),
        position=0,
    )
    db.add(slot)
    db.commit()
    return institute, section, subject, slot.id, day


def test_auto_fill_preview_and_accept(db: Session, client: TestClient):
    institute, section, subject, slot_id, day = seed_timetable(db)

    preview = client.post(
        f"/v1/institutes/{institute.id}/timetable/auto-fill",
        json={"accept": False, "sectionIds": [section.id]},
    )
    assert preview.status_code == 200
    body = preview.json()
    assert body["proposedCount"] >= 1
    proposed = body["proposed"]

    accept = client.post(
        f"/v1/institutes/{institute.id}/timetable/auto-fill",
        json={"accept": True, "proposed": proposed},
    )
    assert accept.status_code == 200
    assert accept.json()["appliedCount"] >= 1

    entry = db.scalar(
        select(TimetableEntry).where(
            TimetableEntry.section_id == section.id,
            TimetableEntry.slot_id == slot_id,
            TimetableEntry.day_of_week == day,
        )
    )
    assert entry is not None


def test_role_settings_blocks_principal_timetable_edit(db: Session, client: TestClient):
    institute, section, subject, slot_id, day = seed_timetable(db)
    db.add(InstituteMember(institute_id=institute.id, user_id="principal", role="principal"))
    db.add(InstituteRoleSettings(institute_id=institute.id, principal_can_edit_timetable=False))
    db.commit()

    main.app.dependency_overrides[main.require_education_subscription] = (
        lambda: {"id": "principal", "email": "p@example.com", "token": "test"}
    )
    denied = client.patch(
        f"/v1/institutes/{institute.id}/timetable/cells",
        json={
            "sectionId": section.id,
            "dayOfWeek": day,
            "slotId": slot_id,
            "subjectId": subject.id,
            "teacherId": "teacher-1",
        },
    )
    assert denied.status_code == 403


def test_substitutions_for_absent_teacher(db: Session, client: TestClient):
    institute, section, subject, slot_id, day = seed_timetable(db)
    db.add(
        InstituteMember(institute_id=institute.id, user_id="teacher-2", role="teacher"),
    )
    db.add(
        TimetableEntry(
            institute_id=institute.id,
            slot_id=slot_id,
            day_of_week=day,
            section_id=section.id,
            subject_id=subject.id,
            teacher_id="teacher-1",
        )
    )
    today = date.today()
    db.add(
        TeacherAbsence(
            institute_id=institute.id,
            teacher_id="teacher-1",
            absence_date=today,
            note="Leave",
        )
    )
    db.commit()

    listing = client.get(
        f"/v1/institutes/{institute.id}/timetable/substitutions",
        params={"substitution_date": today.isoformat()},
    )
    assert listing.status_code == 200
    assert listing.json()["items"]

    saved = client.post(
        f"/v1/institutes/{institute.id}/timetable/substitutions",
        json={
            "date": today.isoformat(),
            "substitutions": [
                {
                    "sectionId": section.id,
                    "slotId": slot_id,
                    "originalTeacherId": "teacher-1",
                    "substituteTeacherId": "teacher-2",
                }
            ],
        },
    )
    assert saved.status_code == 200
    assert saved.json()["savedCount"] == 1


def test_patch_section_subject_weekly_periods(db: Session, client: TestClient):
    institute, section, subject, _, _ = seed_timetable(db)
    response = client.patch(
        f"/v1/sections/{section.id}/subjects/{subject.id}",
        json={"weeklyPeriods": 5},
    )
    assert response.status_code == 200
    assert response.json()["weeklyPeriods"] == 5
