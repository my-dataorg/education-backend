import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app import main
from app.db.session import get_db
from app.models import (
    Base,
    Branch,
    Institute,
    InstituteInvitation,
    InstituteJoinRequest,
    InstituteMember,
    Section,
    SectionMember,
    SectionSubject,
    Subject,
    TeacherSubjectAssignment,
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


def seed_institute(db: Session, owner_id: str = "owner") -> Institute:
    institute = Institute(id="institute-1", name="School", join_code="OLDCODE12")
    db.add(institute)
    db.add(
        Branch(
            id="branch-1",
            institute_id=institute.id,
            name="Main",
            is_primary=True,
        )
    )
    db.add(InstituteMember(institute_id=institute.id, user_id=owner_id, role="owner"))
    db.add(InstituteMember(institute_id=institute.id, user_id="student-1", role="student"))
    db.add(InstituteMember(institute_id=institute.id, user_id="teacher-1", role="teacher"))
    db.commit()
    return institute


def test_roster_principal_can_read(db: Session, client: TestClient):
    institute = seed_institute(db)
    db.add(InstituteMember(institute_id=institute.id, user_id="principal-1", role="principal"))
    db.commit()
    main.app.dependency_overrides[main.require_education_subscription] = (
        lambda: {"id": "principal-1", "email": "p@example.com", "token": "test"}
    )
    response = client.get(f"/v1/institutes/{institute.id}/members/roster?tab=students")
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert body["tabCounts"]["students"] == 1


def test_roster_teacher_forbidden(db: Session, client: TestClient):
    institute = seed_institute(db)
    main.app.dependency_overrides[main.require_education_subscription] = (
        lambda: {"id": "teacher-1", "email": "t@example.com", "token": "test"}
    )
    response = client.get(f"/v1/institutes/{institute.id}/members/roster")
    assert response.status_code == 403


def test_roster_requests_and_invitations_tabs(db: Session, client: TestClient):
    institute = seed_institute(db)
    db.add(
        InstituteJoinRequest(
            institute_id=institute.id,
            user_id="applicant",
            requested_role="student",
            status="pending",
        )
    )
    db.add(
        InstituteInvitation(
            institute_id=institute.id,
            invitee_user_id=None,
            invitee_email="new@example.com",
            role="teacher",
            status="pending",
            invited_by="owner",
        )
    )
    db.commit()
    response = client.get(f"/v1/institutes/{institute.id}/members/roster?tab=requests")
    assert response.status_code == 200
    assert response.json()["total"] == 1
    invites = client.get(f"/v1/institutes/{institute.id}/members/roster?tab=invitations")
    assert invites.json()["total"] == 1


def test_regenerate_join_code_owner_only(db: Session, client: TestClient):
    institute = seed_institute(db)
    response = client.post(f"/v1/institutes/{institute.id}/join-code/regenerate")
    assert response.status_code == 200
    assert response.json()["joinCode"] != "OLDCODE12"

    main.app.dependency_overrides[main.require_education_subscription] = (
        lambda: {"id": "principal-1", "email": "p@example.com", "token": "test"}
    )
    db.add(InstituteMember(institute_id=institute.id, user_id="principal-1", role="principal"))
    db.commit()
    denied = client.post(f"/v1/institutes/{institute.id}/join-code/regenerate")
    assert denied.status_code == 403


def test_subject_teacher_matrix_and_copy(db: Session, client: TestClient):
    institute = seed_institute(db)
    sections = [
        Section(id="sec-a", institute_id=institute.id, name="A", class_name="6"),
        Section(id="sec-b", institute_id=institute.id, name="B", class_name="6"),
    ]
    subject = Subject(id="sub-1", institute_id=institute.id, name="Math")
    db.add_all([*sections, subject])
    for section in sections:
        db.add(SectionSubject(section_id=section.id, subject_id=subject.id, weekly_periods=6))
    db.add(
        SectionMember(section_id="sec-a", user_id="teacher-1", member_type="teacher"),
    )
    db.add(
        TeacherSubjectAssignment(
            section_id="sec-a",
            subject_id=subject.id,
            teacher_id="teacher-1",
        )
    )
    db.commit()

    matrix = client.get(f"/v1/institutes/{institute.id}/subject-teachers")
    assert matrix.status_code == 200
    rows = matrix.json()["rows"]
    assert len(rows) == 2
    empty_row = next(r for r in rows if r["sectionId"] == "sec-b")
    assert empty_row["cells"][0]["teacherId"] is None

    checks = client.get(f"/v1/institutes/{institute.id}/subject-teachers/checks")
    assert checks.json()["unassignedCount"] == 1

    copied = client.post(
        f"/v1/institutes/{institute.id}/subject-teachers/copy",
        json={"sourceSectionId": "sec-a", "targetSectionIds": ["sec-b"]},
    )
    assert copied.status_code == 200
    assert copied.json()["changeCount"] == 1

    after = client.get(f"/v1/institutes/{institute.id}/subject-teachers")
    filled = next(r for r in after.json()["rows"] if r["sectionId"] == "sec-b")
    assert filled["cells"][0]["teacherId"] == "teacher-1"
