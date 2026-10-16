from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app import main
from app.db.session import get_db
from app.models import (
    AttendanceRecord,
    Base,
    Institute,
    InstituteMember,
    InstitutePost,
    Section,
    SectionMember,
)
from app.services import exams as exam_service


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


def seed_institute(db: Session) -> Institute:
    institute = Institute(id="inst-1", name="School", join_code="JOIN1")
    section = Section(id="sec-1", institute_id=institute.id, name="A", class_name="6")
    db.add_all(
        [
            institute,
            section,
            InstituteMember(institute_id=institute.id, user_id="owner", role="owner"),
            InstituteMember(institute_id=institute.id, user_id="teacher", role="teacher"),
            InstituteMember(institute_id=institute.id, user_id="student-1", role="student"),
            SectionMember(section_id=section.id, user_id="teacher", member_type="teacher"),
            SectionMember(section_id=section.id, user_id="student-1", member_type="student"),
        ]
    )
    db.commit()
    return institute


def test_exam_publish_hides_draft_from_student(db: Session, client: TestClient):
    institute = seed_institute(db)
    exam = exam_service.create_exam(
        db, institute.id, "owner", name="Unit test", section_id="sec-1", max_marks=50
    )
    exam_service.upsert_marks(
        db, exam.id, "owner", [{"studentId": "student-1", "marksObtained": 42}]
    )
    exam_service.publish_exam(db, exam.id, "owner")

    main.app.dependency_overrides[main.require_education_subscription] = (
        lambda: {"id": "student-1", "email": "s@example.com", "token": "test"}
    )
    listed = client.get(f"/v1/institutes/{institute.id}/exams")
    assert listed.status_code == 200
    assert len(listed.json()) == 1
    marks = client.get(f"/v1/exams/{exam.id}/marks")
    assert marks.status_code == 200
    assert marks.json()[0]["marksObtained"] == 42

    draft = exam_service.create_exam(db, institute.id, "owner", name="Draft exam")
    listed2 = client.get(f"/v1/institutes/{institute.id}/exams")
    assert len(listed2.json()) == 1


def test_student_cannot_see_unpublished_marks(db: Session, client: TestClient):
    institute = seed_institute(db)
    exam = exam_service.create_exam(db, institute.id, "owner", name="Midterm")
    exam_service.upsert_marks(
        db, exam.id, "owner", [{"studentId": "student-1", "marksObtained": 30}]
    )
    main.app.dependency_overrides[main.require_education_subscription] = (
        lambda: {"id": "student-1", "email": "s@example.com", "token": "test"}
    )
    response = client.get(f"/v1/exams/{exam.id}/marks")
    assert response.status_code == 403


def test_fee_payment_returns_receipt_and_reduces_dues(db: Session, client: TestClient):
    institute = seed_institute(db)
    structure = client.post(
        f"/v1/institutes/{institute.id}/fee-structures",
        json={"name": "Tuition", "amountPaise": 50000},
    )
    assert structure.status_code == 201
    fee_structure_id = structure.json()["id"]
    assign = client.post(
        f"/v1/institutes/{institute.id}/student-fees",
        json={"studentId": "student-1", "feeStructureId": fee_structure_id},
    )
    assert assign.status_code == 201

    payment = client.post(
        f"/v1/institutes/{institute.id}/fees/payments",
        json={"studentId": "student-1", "amountPaise": 20000, "method": "cash"},
    )
    assert payment.status_code == 201
    receipt_number = payment.json()["receiptNumber"]
    assert receipt_number.startswith("RCP-")

    receipt = client.get(f"/v1/institutes/{institute.id}/fee-receipts/{receipt_number}")
    assert receipt.status_code == 200
    dues = client.get(f"/v1/institutes/{institute.id}/fees/dues")
    assert dues.json()[0]["balancePaise"] == 30000


def test_attendance_summary_for_owner(db: Session, client: TestClient):
    institute = seed_institute(db)
    db.add(
        AttendanceRecord(
            section_id="sec-1",
            student_id="student-1",
            attendance_date=date(2026, 10, 13),
            status="present",
            marked_by="teacher",
        )
    )
    db.commit()
    response = client.get(
        f"/v1/institutes/{institute.id}/attendance/summary?day=2026-10-13"
    )
    assert response.status_code == 200
    body = response.json()
    assert body["present"] == 1
    assert body["sectionsPending"] == 0


def test_notice_audience_filters_for_student(db: Session, client: TestClient):
    institute = seed_institute(db)
    db.add_all(
        [
            InstitutePost(
                institute_id=institute.id,
                title="Staff only",
                body="x",
                posted_by="owner",
                audience="staff",
            ),
            InstitutePost(
                institute_id=institute.id,
                title="Everyone",
                body="y",
                posted_by="owner",
                audience="everyone",
            ),
        ]
    )
    db.commit()
    main.app.dependency_overrides[main.require_education_subscription] = (
        lambda: {"id": "student-1", "email": "s@example.com", "token": "test"}
    )
    response = client.get(f"/v1/institutes/{institute.id}/posts")
    assert response.status_code == 200
    titles = [row["title"] for row in response.json()]
    assert titles == ["Everyone"]


def test_reports_csv(db: Session, client: TestClient):
    institute = seed_institute(db)
    attendance = client.get(f"/v1/institutes/{institute.id}/reports/attendance")
    assert attendance.status_code == 200
    assert "class_name" in attendance.text
    enrollment = client.get(f"/v1/institutes/{institute.id}/reports/enrollment")
    assert enrollment.status_code == 200
    assert "student_count" in enrollment.text
