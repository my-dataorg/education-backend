import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app import main
from app.db.session import get_db
from app.models import Base, Institute, InstituteMember, Section, SectionMember


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


def seed(db: Session) -> tuple[str, str]:
    inst = Institute(id="inst-o1", name="School", join_code="O1SC")
    section = Section(id="sec-o1", institute_id=inst.id, name="A", class_name="10")
    db.add_all(
        [
            inst,
            section,
            InstituteMember(institute_id=inst.id, user_id="owner", role="owner"),
            SectionMember(section_id=section.id, user_id="stu-1", member_type="student"),
        ]
    )
    db.commit()
    return inst.id, section.id


def test_org_tree_and_node_default(client: TestClient, db: Session):
    institute_id, section_id = seed(db)
    nodes = client.get(f"/v1/institutes/{institute_id}/org-nodes")
    assert nodes.status_code == 200
    flat = nodes.json()
    assert any(n["sectionId"] == section_id and n["level"] == 3 for n in flat)
    sec_node = next(n for n in flat if n["sectionId"] == section_id)

    put = client.put(
        f"/v1/institutes/{institute_id}/org-nodes/{sec_node['id']}/fee-default",
        json={"amountPaise": 500000, "feePlanId": None, "feeStructureId": None},
    )
    assert put.status_code == 200
    assert put.json()["amountPaise"] == 500000

    detail = client.get(
        f"/v1/institutes/{institute_id}/sections/{section_id}/students/stu-1/fees"
    )
    assert detail.status_code == 200
    body = detail.json()
    assert body["resolvedAmountPaise"] == 500000
    assert body["resolvedFrom"] == "section"
