import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker

from app import main
from app.db.session import get_db
from app.models import (
    Base,
    Institute,
    InstituteInvitation,
    InstituteMember,
    Section,
    SectionMember,
    SectionSubject,
    TeacherSubjectAssignment,
)
from app.services import invitations, subjects


@pytest.fixture
def db():
    engine = create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False}
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


def add_institute(db: Session, *, user_id: str = "owner") -> Institute:
    institute = Institute(id="institute-1", name="School", join_code="SCHOOL")
    db.add(institute)
    db.add(InstituteMember(institute_id=institute.id, user_id=user_id, role="owner"))
    db.commit()
    return institute


def test_institute_creation_requires_subscription(db: Session):
    def override_db():
        yield db

    def no_subscription():
        raise HTTPException(status_code=403, detail="Education subscription required")

    main.app.dependency_overrides[get_db] = override_db
    main.app.dependency_overrides[main.require_education_subscription] = no_subscription
    try:
        response = TestClient(main.app).post("/v1/institutes", json={"name": "School"})
        assert response.status_code == 403
        assert db.scalar(select(func.count()).select_from(Institute)) == 0
    finally:
        main.app.dependency_overrides.clear()


def test_non_owner_cannot_invite_or_assign_section_member(db: Session, client: TestClient):
    institute = add_institute(db)
    section = Section(id="section-1", institute_id=institute.id, name="A", class_name="1")
    db.add(section)
    db.commit()

    main.app.dependency_overrides[main.require_education_subscription] = (
        lambda: {"id": "staff", "email": "staff@example.com", "token": "test"}
    )
    invite = client.post(
        f"/v1/institutes/{institute.id}/invitations",
        json={"userId": "teacher", "role": "teacher"},
    )
    assign = client.post(
        f"/v1/sections/{section.id}/members",
        json={"userId": "teacher", "memberType": "teacher"},
    )

    assert invite.status_code == 403
    assert assign.status_code == 403


def test_invitation_acceptance_is_idempotent_and_subscribes_user(db: Session, monkeypatch):
    institute = add_institute(db)
    invitation = InstituteInvitation(
        id="invitation-1",
        institute_id=institute.id,
        invitee_user_id="teacher",
        invitee_email="teacher@example.com",
        role="teacher",
        status="pending",
        invited_by="owner",
    )
    db.add(invitation)
    db.commit()

    subscriptions = []
    monkeypatch.setattr(
        invitations,
        "on_member_joined",
        lambda _db, _institute_id, user_id, _role, email="": subscriptions.append(user_id),
    )
    monkeypatch.setattr(invitations, "notify_user", lambda *args, **kwargs: None)

    first = invitations.accept_invitation(db, invitation.id, "teacher", "TEACHER@example.com")
    second = invitations.accept_invitation(db, invitation.id, "teacher", "teacher@example.com")

    assert first.id == second.id
    assert invitation.status == "accepted"
    assert subscriptions == ["teacher"]
    assert db.scalar(
        select(func.count()).select_from(InstituteMember).where(InstituteMember.user_id == "teacher")
    ) == 1


def test_owner_can_create_link_and_assign_subject(db: Session):
    institute = add_institute(db)
    section = Section(id="section-1", institute_id=institute.id, name="A", class_name="1")
    db.add_all(
        [
            section,
            InstituteMember(institute_id=institute.id, user_id="teacher", role="teacher"),
            SectionMember(section_id=section.id, user_id="teacher", member_type="teacher"),
        ]
    )
    db.commit()

    subject = subjects.create_subject(db, institute.id, " Mathematics ")
    subjects.link_subject(db, section.id, subject.id)
    subjects.assign_teacher(db, section.id, subject.id, "teacher")

    assert subject.name == "Mathematics"
    assert db.scalar(select(SectionSubject).where(SectionSubject.section_id == section.id))
    assert db.scalar(
        select(TeacherSubjectAssignment).where(
            TeacherSubjectAssignment.section_id == section.id,
            TeacherSubjectAssignment.teacher_id == "teacher",
        )
    )


def test_non_member_cannot_access_institute(db: Session, client: TestClient):
    institute = add_institute(db)
    main.app.dependency_overrides[main.require_education_subscription] = (
        lambda: {"id": "outsider", "email": "outsider@example.com", "token": "test"}
    )

    response = client.get(f"/v1/institutes/{institute.id}")

    assert response.status_code == 403
