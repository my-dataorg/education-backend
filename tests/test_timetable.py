from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app import main
from app.db.session import get_db
from app.models import (
    Base,
    Institute,
    InstituteMember,
    ScheduleSettings,
    ScheduleSlot,
    Section,
    SectionMember,
    SectionSubject,
    Subject,
    TimetableEntry,
)
from app.services.timetable import (
    detect_clashes,
    detect_period_limit_warnings,
    publish_timetable,
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


def seed_schedule(db: Session, institute_id: str, section_id: str, subject_id: str) -> str:
    db.add(
        ScheduleSettings(
            institute_id=institute_id,
            weekdays="1",
        )
    )
    slot = ScheduleSlot(
        id="slot-1",
        institute_id=institute_id,
        label="P1",
        kind="instruction",
        start_time=datetime.strptime("08:00", "%H:%M").time(),
        end_time=datetime.strptime("08:45", "%H:%M").time(),
        position=0,
    )
    db.add(slot)
    db.add(
        TimetableEntry(
            id="entry-a",
            institute_id=institute_id,
            slot_id=slot.id,
            day_of_week=1,
            section_id=section_id,
            subject_id=subject_id,
            teacher_id="teacher-1",
        )
    )
    db.commit()
    return slot.id


def add_institute(db: Session, user_id: str, role: str) -> Institute:
    institute = Institute(id="institute-1", name="School", join_code="SCHOOL")
    db.add(institute)
    db.add(InstituteMember(institute_id=institute.id, user_id=user_id, role=role))
    return institute


def test_detect_clashes_for_teacher_double_booked(db: Session):
    institute = add_institute(db, "owner", "owner")
    sections = [
        Section(id="section-a", institute_id=institute.id, name="A", class_name="7"),
        Section(id="section-b", institute_id=institute.id, name="B", class_name="7"),
    ]
    subject = Subject(id="math", institute_id=institute.id, name="Math")
    db.add_all([*sections, subject])
    for section in sections:
        db.add(SectionSubject(section_id=section.id, subject_id=subject.id))
    db.add(InstituteMember(institute_id=institute.id, user_id="teacher-1", role="teacher"))
    db.commit()

    db.add(
        ScheduleSettings(institute_id=institute.id, weekdays="1"),
    )
    slot = ScheduleSlot(
        id="slot-1",
        institute_id=institute.id,
        label="P1",
        kind="instruction",
        start_time=datetime.strptime("08:00", "%H:%M").time(),
        end_time=datetime.strptime("08:45", "%H:%M").time(),
        position=0,
    )
    db.add(slot)
    for section in sections:
        db.add(
            TimetableEntry(
                institute_id=institute.id,
                slot_id=slot.id,
                day_of_week=1,
                section_id=section.id,
                subject_id=subject.id,
                teacher_id="teacher-1",
            )
        )
    db.commit()

    clashes = detect_clashes(db, institute.id)

    assert any(clash["type"] == "teacher" for clash in clashes)


def test_period_limit_is_warning_not_clash(db: Session):
    institute = add_institute(db, "owner", "owner")
    section = Section(id="section-a", institute_id=institute.id, name="A", class_name="10")
    subject = Subject(id="english", institute_id=institute.id, name="English")
    db.add_all([section, subject, SectionSubject(section_id=section.id, subject_id=subject.id, weekly_periods=1)])
    db.add(ScheduleSettings(institute_id=institute.id, weekdays="1,2,3,4,5"))
    slots = []
    for index in range(2):
        slots.append(
            ScheduleSlot(
                id=f"slot-{index}",
                institute_id=institute.id,
                label=f"P{index + 1}",
                kind="instruction",
                start_time=datetime.strptime(f"{8 + index}:00", "%H:%M").time(),
                end_time=datetime.strptime(f"{8 + index}:45", "%H:%M").time(),
                position=index,
            )
        )
    db.add_all(slots)
    for slot in slots:
        db.add(
            TimetableEntry(
                institute_id=institute.id,
                slot_id=slot.id,
                day_of_week=1,
                section_id=section.id,
                subject_id=subject.id,
                teacher_id=f"teacher-{slot.id}",
            )
        )
    db.commit()

    clashes = detect_clashes(db, institute.id)
    warnings = detect_period_limit_warnings(db, institute.id)

    assert not clashes
    assert len(warnings) == 1
    publish_timetable(db, institute.id)


def test_detect_clashes_when_class_double_booked(db: Session):
    institute = add_institute(db, "owner", "owner")
    section = Section(id="section-a", institute_id=institute.id, name="A", class_name="10")
    subjects = [
        Subject(id="english", institute_id=institute.id, name="English"),
        Subject(id="math", institute_id=institute.id, name="Math"),
    ]
    db.add_all([section, *subjects])
    for subject in subjects:
        db.add(SectionSubject(section_id=section.id, subject_id=subject.id))
    db.add(ScheduleSettings(institute_id=institute.id, weekdays="1"))
    overlapping_slots = [
        ScheduleSlot(
            id="slot-1",
            institute_id=institute.id,
            label="P1",
            kind="instruction",
            start_time=datetime.strptime("08:00", "%H:%M").time(),
            end_time=datetime.strptime("08:50", "%H:%M").time(),
            position=0,
        ),
        ScheduleSlot(
            id="slot-2",
            institute_id=institute.id,
            label="P2",
            kind="instruction",
            start_time=datetime.strptime("08:40", "%H:%M").time(),
            end_time=datetime.strptime("09:25", "%H:%M").time(),
            position=1,
        ),
    ]
    db.add_all(overlapping_slots)
    db.add_all(
        [
            TimetableEntry(
                institute_id=institute.id,
                slot_id="slot-1",
                day_of_week=1,
                section_id=section.id,
                subject_id=subjects[0].id,
                teacher_id="teacher-a",
            ),
            TimetableEntry(
                institute_id=institute.id,
                slot_id="slot-2",
                day_of_week=1,
                section_id=section.id,
                subject_id=subjects[1].id,
                teacher_id="teacher-b",
            ),
        ]
    )
    db.commit()

    clashes = detect_clashes(db, institute.id)

    assert any(clash["type"] == "section" for clash in clashes)


def test_publish_blocked_when_clash_exists(db: Session):
    institute = add_institute(db, "owner", "owner")
    sections = [
        Section(id="section-a", institute_id=institute.id, name="A", class_name="7"),
        Section(id="section-b", institute_id=institute.id, name="B", class_name="7"),
    ]
    subject = Subject(id="math", institute_id=institute.id, name="Math")
    db.add_all([*sections, subject])
    for section in sections:
        db.add(SectionSubject(section_id=section.id, subject_id=subject.id))
    db.commit()
    db.add(ScheduleSettings(institute_id=institute.id, weekdays="1"))
    slot = ScheduleSlot(
        id="slot-1",
        institute_id=institute.id,
        label="P1",
        kind="instruction",
        start_time=datetime.strptime("08:00", "%H:%M").time(),
        end_time=datetime.strptime("08:45", "%H:%M").time(),
        position=0,
    )
    db.add(slot)
    for section in sections:
        db.add(
            TimetableEntry(
                institute_id=institute.id,
                slot_id=slot.id,
                day_of_week=1,
                section_id=section.id,
                subject_id=subject.id,
                teacher_id="teacher-1",
            )
        )
    db.commit()

    with pytest.raises(ValueError, match="clash"):
        publish_timetable(db, institute.id)


def test_principal_can_patch_cell(db: Session, client: TestClient):
    institute = add_institute(db, "principal", "principal")
    section = Section(id="section-1", institute_id=institute.id, name="A", class_name="9")
    subject = Subject(id="english", institute_id=institute.id, name="English")
    db.add_all(
        [
            section,
            subject,
            SectionSubject(section_id=section.id, subject_id=subject.id),
            InstituteMember(institute_id=institute.id, user_id="teacher-1", role="teacher"),
        ]
    )
    slot_id = seed_schedule(db, institute.id, section.id, subject.id)
    db.commit()

    main.app.dependency_overrides[main.require_education_subscription] = (
        lambda: {"id": "principal", "email": "p@example.com", "token": "test"}
    )

    response = client.patch(
        f"/v1/institutes/{institute.id}/timetable/cells",
        json={
            "sectionId": section.id,
            "dayOfWeek": 1,
            "slotId": slot_id,
            "subjectId": subject.id,
            "teacherId": "teacher-1",
            "room": "Lab 1",
        },
    )

    assert response.status_code == 200
    assert response.json()["cells"][0]["room"] == "Lab 1"


def test_teacher_can_browse_class_timetable_published(db: Session, client: TestClient):
    institute = add_institute(db, "owner", "owner")
    section = Section(id="section-1", institute_id=institute.id, name="A", class_name="9")
    subject = Subject(id="english", institute_id=institute.id, name="English")
    db.add_all(
        [
            section,
            subject,
            SectionSubject(section_id=section.id, subject_id=subject.id),
            InstituteMember(institute_id=institute.id, user_id="teacher-1", role="teacher"),
        ]
    )
    seed_schedule(db, institute.id, section.id, subject.id)
    publish_timetable(db, institute.id)

    main.app.dependency_overrides[main.require_education_subscription] = (
        lambda: {"id": "teacher-1", "email": "t@example.com", "token": "test"}
    )

    response = client.get(
        f"/v1/institutes/{institute.id}/timetable",
        params={"view": "class", "id": section.id, "state": "published"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["view"] == "class"
    assert body["itemId"] == section.id
    assert len(body["cells"]) == 1


def test_student_reads_published_schedule_only(db: Session, client: TestClient):
    institute = add_institute(db, "owner", "owner")
    section = Section(id="section-1", institute_id=institute.id, name="A", class_name="9")
    subject = Subject(id="english", institute_id=institute.id, name="English")
    db.add_all(
        [
            section,
            subject,
            SectionSubject(section_id=section.id, subject_id=subject.id),
            InstituteMember(institute_id=institute.id, user_id="student-1", role="student"),
            SectionMember(section_id=section.id, user_id="student-1", member_type="student"),
        ]
    )
    slot_id = seed_schedule(db, institute.id, section.id, subject.id)

    publish_timetable(db, institute.id)

    entry = db.get(TimetableEntry, "entry-a")
    entry.room = "Draft room"
    settings = db.get(ScheduleSettings, institute.id)
    settings.draft_saved_at = datetime.now(timezone.utc)
    db.commit()

    main.app.dependency_overrides[main.require_education_subscription] = (
        lambda: {"id": "student-1", "email": "s@example.com", "token": "test"}
    )

    response = client.get(f"/v1/institutes/{institute.id}/schedule")

    assert response.status_code == 200
    body = response.json()
    assert body["entries"][0]["room"] is None
    assert body["entries"][0]["slotId"] == slot_id
