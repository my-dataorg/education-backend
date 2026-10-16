import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app import main
from app.db.session import get_db
from app.models import Base, GuardianLinkCache, Institute, InstituteMember
from app.services.social_client import clear_guardian_cache_stub, write_guardian_cache_stub


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
        clear_guardian_cache_stub()


@pytest.fixture
def client(db: Session):
    def override_db():
        yield db

    main.app.dependency_overrides[get_db] = override_db
    main.app.dependency_overrides[main.require_education_subscription] = (
        lambda: {"id": "parent-1", "email": "parent@example.com", "token": "test"}
    )
    yield TestClient(main.app)
    main.app.dependency_overrides.clear()


def seed_parent_institute(db: Session) -> Institute:
    institute = Institute(id="inst-1", name="School", join_code="JOIN1")
    db.add_all(
        [
            institute,
            InstituteMember(institute_id=institute.id, user_id="parent-1", role="parent"),
            InstituteMember(institute_id=institute.id, user_id="student-1", role="student"),
        ]
    )
    db.commit()
    write_guardian_cache_stub("parent-1", ["student-1"])
    return institute


def test_guardian_children_requires_parent_membership(db: Session, client: TestClient):
    institute = Institute(id="inst-1", name="School", join_code="JOIN1")
    db.add_all(
        [
            institute,
            InstituteMember(institute_id=institute.id, user_id="teacher", role="teacher"),
        ]
    )
    db.commit()
    main.app.dependency_overrides[main.require_education_subscription] = (
        lambda: {"id": "teacher", "email": "t@example.com", "token": "test"}
    )

    response = client.get("/v1/users/me/guardian-children")

    assert response.status_code == 403


def test_guardian_children_lists_linked_enrolled_students(db: Session, client: TestClient):
    institute = seed_parent_institute(db)

    response = client.get("/v1/users/me/guardian-children")

    assert response.status_code == 200
    payload = response.json()
    assert payload["children"] == [
        {"studentId": "student-1", "instituteIds": [institute.id]}
    ]


def test_parent_threads_and_messages(db: Session, client: TestClient):
    institute = seed_parent_institute(db)

    create = client.post(
        f"/v1/institutes/{institute.id}/parent/children/student-1/threads",
        json={"subject": "Homework", "initialMessage": "Need help with math"},
    )
    assert create.status_code == 201
    thread_id = create.json()["id"]

    listed = client.get(
        f"/v1/institutes/{institute.id}/parent/children/student-1/threads"
    )
    assert listed.status_code == 200
    assert len(listed.json()) == 1
    assert listed.json()[0]["subject"] == "Homework"

    message = client.post(
        f"/v1/institutes/{institute.id}/parent/children/student-1/threads/{thread_id}/messages",
        json={"body": "Follow-up question"},
    )
    assert message.status_code == 201
    assert message.json()["body"] == "Follow-up question"


def test_owner_can_seed_guardian_links(db: Session, client: TestClient):
    institute = Institute(id="inst-1", name="School", join_code="JOIN1")
    db.add_all(
        [
            institute,
            InstituteMember(institute_id=institute.id, user_id="owner", role="owner"),
            InstituteMember(institute_id=institute.id, user_id="parent-1", role="parent"),
            InstituteMember(institute_id=institute.id, user_id="student-1", role="student"),
        ]
    )
    db.commit()
    main.app.dependency_overrides[main.require_education_subscription] = (
        lambda: {"id": "owner", "email": "owner@example.com", "token": "test"}
    )

    response = client.post(
        f"/v1/institutes/{institute.id}/guardian-links/seed",
        json={
            "links": [
                {"guardianUserId": "parent-1", "studentUserIds": ["student-1"]},
            ]
        },
    )

    assert response.status_code == 200
    assert response.json()["guardiansUpdated"] == 1
    row = db.get(GuardianLinkCache, "parent-1")
    assert row is not None
    assert "student-1" in row.student_ids_json


def test_parent_threads_rejects_unlinked_child(db: Session, client: TestClient):
    institute = seed_parent_institute(db)
    write_guardian_cache_stub("parent-1", [])

    response = client.get(
        f"/v1/institutes/{institute.id}/parent/children/student-1/threads"
    )

    assert response.status_code == 403
