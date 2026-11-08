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
    main.app.dependency_overrides[main.require_education_subscription] = (
        lambda: {"id": "owner", "email": "owner@example.com", "token": "test"}
    )
    yield TestClient(main.app)
    main.app.dependency_overrides.clear()


def seed(db: Session) -> str:
    inst = Institute(id="inst-as1", name="School", join_code="AS1X")
    db.add_all([inst, InstituteMember(institute_id=inst.id, user_id="owner", role="owner")])
    db.commit()
    return inst.id


def test_academic_hierarchy(client: TestClient, db: Session):
    institute_id = seed(db)
    tree = client.get(f"/v1/institutes/{institute_id}/academic-structure/tree")
    assert tree.status_code == 200
    root = tree.json()["tree"][0]
    band = client.post(
        f"/v1/institutes/{institute_id}/academic-structure/nodes",
        json={"parentId": root["id"], "level": 1, "label": "High school"},
    )
    assert band.status_code == 201
    band_id = band.json()["id"]
    klass = client.post(
        f"/v1/institutes/{institute_id}/academic-structure/nodes",
        json={"parentId": band_id, "level": 2, "label": "Grade 10"},
    )
    assert klass.status_code == 201
    section = client.post(
        f"/v1/institutes/{institute_id}/academic-structure/sections",
        json={"parentClassOrgNodeId": klass.json()["id"], "name": "A"},
    )
    assert section.status_code == 201
    refreshed = client.get(f"/v1/institutes/{institute_id}/academic-structure/tree")
    flat_levels = []

    def walk(nodes):
        for n in nodes:
            flat_levels.append(n["level"])
            walk(n.get("children") or [])

    walk(refreshed.json()["tree"])
    assert 1 in flat_levels and 2 in flat_levels and 3 in flat_levels
