import pytest
from sqlalchemy import select
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
    InstituteMember,
    Section,
    SectionMember,
    Subject,
)
from app.models import SectionSubject


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


def seed_two_campuses(db: Session) -> tuple[Institute, str, str, str, str]:
    institute = Institute(id="inst-1", name="School", join_code="JOIN1")
    campus_a = Branch(id="branch-a", institute_id=institute.id, name="North", is_primary=True)
    campus_b = Branch(id="branch-b", institute_id=institute.id, name="South", is_primary=False)
    sec_a = Section(
        id="sec-a",
        institute_id=institute.id,
        branch_id=campus_a.id,
        name="A",
        class_name="6",
    )
    sec_b = Section(
        id="sec-b",
        institute_id=institute.id,
        branch_id=campus_b.id,
        name="A",
        class_name="7",
    )
    db.add_all(
        [
            institute,
            campus_a,
            campus_b,
            sec_a,
            sec_b,
            InstituteMember(institute_id=institute.id, user_id="owner", role="owner"),
            InstituteMember(institute_id=institute.id, user_id="teacher-a", role="teacher"),
            InstituteMember(institute_id=institute.id, user_id="teacher-b", role="teacher"),
            InstituteMember(institute_id=institute.id, user_id="student-a", role="student"),
            InstituteMember(institute_id=institute.id, user_id="student-b", role="student"),
            SectionMember(section_id=sec_a.id, user_id="teacher-a", member_type="teacher"),
            SectionMember(section_id=sec_b.id, user_id="teacher-b", member_type="teacher"),
            SectionMember(section_id=sec_a.id, user_id="student-a", member_type="student"),
            SectionMember(section_id=sec_b.id, user_id="student-b", member_type="student"),
        ]
    )
    db.commit()
    return institute, sec_a.id, sec_b.id, "student-a", "student-b"


def test_overview_filters_by_campus(db: Session, client: TestClient):
    institute, _, _, _, _ = seed_two_campuses(db)
    all_campuses = client.get(f"/v1/institutes/{institute.id}/overview")
    assert all_campuses.status_code == 200
    assert all_campuses.json()["stats"]["students"] == 2

    north = client.get(
        f"/v1/institutes/{institute.id}/overview?campus_id=branch-a"
    )
    assert north.status_code == 200
    assert north.json()["stats"]["students"] == 1

    south = client.get(
        f"/v1/institutes/{institute.id}/overview?campus_id=branch-b"
    )
    assert south.json()["stats"]["students"] == 1
    assert south.json()["stats"]["staff"] == 1


def test_post_section_subject_accepts_weekly_periods(db: Session, client: TestClient):
    institute, section_id, _, _, _ = seed_two_campuses(db)
    subject = Subject(id="sub-1", institute_id=institute.id, name="Math")
    db.add(subject)
    db.commit()

    response = client.post(
        f"/v1/sections/{section_id}/subjects",
        json={"subjectId": subject.id, "weeklyPeriods": 6},
    )
    assert response.status_code == 201
    assert response.json()["weeklyPeriods"] == 6
    link = db.scalar(
        select(SectionSubject).where(
            SectionSubject.section_id == section_id,
            SectionSubject.subject_id == subject.id,
        )
    )
    assert link is not None
    assert link.weekly_periods == 6


def test_bulk_assign_section_members(db: Session, client: TestClient):
    institute, section_id, _, _, student_b = seed_two_campuses(db)
    db.add(InstituteMember(institute_id=institute.id, user_id="student-c", role="student"))
    db.commit()

    response = client.post(
        f"/v1/sections/{section_id}/members/bulk",
        json={
            "members": [
                {"userId": "student-c", "memberType": "student"},
                {"userId": "unknown-user", "memberType": "student"},
            ]
        },
    )
    assert response.status_code == 201
    body = response.json()
    assert body["added"] == 1
    assert len(body["skipped"]) == 1
    assert body["skipped"][0]["userId"] == "unknown-user"


def test_transfer_student_between_sections(db: Session, client: TestClient):
    institute, sec_a, sec_b, student_a, _ = seed_two_campuses(db)
    response = client.post(
        f"/v1/institutes/{institute.id}/enrollments/transfer",
        json={"studentId": student_a, "toSectionId": sec_b, "reason": "Balancing"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["fromSectionId"] == sec_a
    assert data["toSectionId"] == sec_b
    moved = db.scalar(
        select(SectionMember).where(
            SectionMember.section_id == sec_b,
            SectionMember.user_id == student_a,
            SectionMember.member_type == "student",
        )
    )
    assert moved is not None
    old = db.scalar(
        select(SectionMember).where(
            SectionMember.section_id == sec_a,
            SectionMember.user_id == student_a,
        )
    )
    assert old is None
