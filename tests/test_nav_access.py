import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app import main
from app.db.session import get_db
from app.models import Base, Institute, InstituteMember


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
    yield TestClient(main.app)
    main.app.dependency_overrides.clear()


def seed(db: Session):
    inst = Institute(id="inst-1", name="School", join_code="ABC")
    db.add_all(
        [
            inst,
            InstituteMember(institute_id=inst.id, user_id="owner", role="owner"),
            InstituteMember(institute_id=inst.id, user_id="teacher", role="teacher"),
        ]
    )
    db.commit()
    return inst


def test_nav_access_matrix_owner_only(db: Session, client: TestClient):
    seed(db)
    main.app.dependency_overrides[main.require_education_subscription] = (
        lambda: {"id": "teacher", "email": "t@example.com", "token": "test"}
    )
    r = client.get("/v1/institutes/inst-1/nav-access/matrix")
    assert r.status_code == 403

    main.app.dependency_overrides[main.require_education_subscription] = (
        lambda: {"id": "owner", "email": "o@example.com", "token": "test"}
    )
    r = client.get("/v1/institutes/inst-1/nav-access/matrix")
    assert r.status_code == 200
    body = r.json()
    assert "overview" in body["featureIds"]
    assert body["overrides"] == {}


def test_nav_access_classes_tab_keys(db: Session, client: TestClient):
    seed(db)
    main.app.dependency_overrides[main.require_education_subscription] = (
        lambda: {"id": "owner", "email": "o@example.com", "token": "test"}
    )
    r = client.get("/v1/institutes/inst-1/nav-access/matrix")
    assert r.status_code == 200
    assert "classes.timetable" in r.json()["featureIds"]


def test_nav_access_save_and_read(db: Session, client: TestClient):
    seed(db)
    main.app.dependency_overrides[main.require_education_subscription] = (
        lambda: {"id": "owner", "email": "o@example.com", "token": "test"}
    )
    put = client.put(
        "/v1/institutes/inst-1/nav-access/matrix",
        json={"overrides": {"exams": {"teacher": {"visible": False, "editable": False}}}},
    )
    assert put.status_code == 200
    assert put.json()["overrides"]["exams"]["teacher"]["visible"] is False

    main.app.dependency_overrides[main.require_education_subscription] = (
        lambda: {"id": "teacher", "email": "t@example.com", "token": "test"}
    )
    r = client.get("/v1/institutes/inst-1/nav-access")
    assert r.status_code == 200
    assert r.json()["role"] == "teacher"
    assert r.json()["overrides"]["exams"]["teacher"]["visible"] is False
