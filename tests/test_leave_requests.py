from datetime import date, datetime, timedelta

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
    PublishedTimetableEntry,
    ScheduleSettings,
    ScheduleSlot,
    Section,
    SectionMember,
    SectionSubject,
    Subject,
    TeacherAbsence,
    TimetableEntry,
)
from app.services.timetable import publish_timetable


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


def client_for(db: Session, user_id: str) -> TestClient:
    def override_db():
        yield db

    main.app.dependency_overrides[get_db] = override_db
    main.app.dependency_overrides[main.require_education_subscription] = (
        lambda: {"id": user_id, "email": f"{user_id}@example.com", "token": "test"}
    )
    return TestClient(main.app)


def seed_published_section(
    db: Session,
    *,
    teacher_id: str = "teacher-1",
    student_id: str = "student-1",
) -> tuple[str, str]:
    institute = Institute(id="institute-1", name="School", join_code="SCHOOL")
    section = Section(id="section-1", institute_id=institute.id, name="A", class_name="7")
    subject = Subject(id="math", institute_id=institute.id, name="Math")
    db.add_all(
        [
            institute,
            section,
            subject,
            InstituteMember(institute_id=institute.id, user_id="owner", role="owner"),
            InstituteMember(institute_id=institute.id, user_id=teacher_id, role="teacher"),
            InstituteMember(institute_id=institute.id, user_id=student_id, role="student"),
            SectionMember(section_id=section.id, user_id=student_id, member_type="student"),
            SectionSubject(section_id=section.id, subject_id=subject.id),
            ScheduleSettings(institute_id=institute.id, weekdays="1"),
        ]
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
    db.add(
        TimetableEntry(
            institute_id=institute.id,
            slot_id=slot.id,
            day_of_week=1,
            section_id=section.id,
            subject_id=subject.id,
            teacher_id=teacher_id,
        )
    )
    db.commit()
    publish_timetable(db, institute.id)
    return institute.id, section.id


def test_student_leave_creates_period_approval_lines(db: Session):
    institute_id, section_id = seed_published_section(db)
    client = client_for(db, "student-1")
    monday = date(2026, 10, 26)
    while monday.isoweekday() != 1:
        monday += timedelta(days=1)
    try:
        response = client.post(
            f"/v1/institutes/{institute_id}/leave-requests",
            json={
                "sectionId": section_id,
                "startDate": monday.isoformat(),
                "endDate": monday.isoformat(),
                "purpose": "Medical",
                "body": "Fever",
                "attachments": [],
            },
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["status"] == "pending"
        assert len(body["approvals"]) == 1
        assert body["approvals"][0]["assigneeUserId"] == "teacher-1"
    finally:
        main.app.dependency_overrides.clear()


def test_substitute_is_assignee_when_teacher_absent(db: Session):
    institute_id, section_id = seed_published_section(db, teacher_id="teacher-1")
    db.add(
        InstituteMember(institute_id=institute_id, user_id="sub-1", role="teacher"),
    )
    monday = date(2026, 10, 26)
    while monday.isoweekday() != 1:
        monday += timedelta(days=1)
    db.add(
        TeacherAbsence(
            institute_id=institute_id,
            teacher_id="teacher-1",
            absence_date=monday,
            substitute_teacher_id="sub-1",
        )
    )
    db.commit()
    client = client_for(db, "student-1")
    try:
        response = client.post(
            f"/v1/institutes/{institute_id}/leave-requests",
            json={
                "sectionId": section_id,
                "startDate": monday.isoformat(),
                "endDate": monday.isoformat(),
                "purpose": "Trip",
                "body": "",
                "attachments": [],
            },
        )
        assert response.status_code == 200
        assert response.json()["approvals"][0]["assigneeUserId"] == "sub-1"
        assert response.json()["approvals"][0]["assigneeKind"] == "substitute"
    finally:
        main.app.dependency_overrides.clear()


def test_staff_leave_manager_approval(db: Session):
    institute_id, _ = seed_published_section(db, teacher_id="teacher-1")
    client = client_for(db, "teacher-1")
    start = date(2026, 11, 3)
    try:
        create_res = client.post(
            f"/v1/institutes/{institute_id}/leave-requests",
            json={
                "startDate": start.isoformat(),
                "endDate": start.isoformat(),
                "purpose": "Personal",
                "body": "",
                "attachments": [],
            },
        )
        assert create_res.status_code == 200
        req = create_res.json()
        line_id = req["approvals"][0]["id"]
        owner_client = client_for(db, "owner")
        decide = owner_client.post(
            f"/v1/institutes/{institute_id}/leave-requests/{req['id']}/approvals/{line_id}/decide",
            json={"approve": True, "note": "OK"},
        )
        assert decide.status_code == 200
        assert decide.json()["status"] == "approved"
    finally:
        main.app.dependency_overrides.clear()
