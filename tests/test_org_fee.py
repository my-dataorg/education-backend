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


def test_org_node_fee_items_and_student_lines(client: TestClient, db: Session):
    institute_id, section_id = seed(db)
    flat = client.get(f"/v1/institutes/{institute_id}/org-nodes").json()
    sec_node = next(n for n in flat if n.get("sectionId") == section_id)

    tuition = client.post(
        f"/v1/institutes/{institute_id}/fee-structures",
        json={"name": "Tuition", "amountPaise": 100},
    )
    transport = client.post(
        f"/v1/institutes/{institute_id}/fee-structures",
        json={"name": "Transport", "amountPaise": 100},
    )
    assert tuition.status_code == 201
    assert transport.status_code == 201
    t_id, tr_id = tuition.json()["id"], transport.json()["id"]

    put = client.put(
        f"/v1/institutes/{institute_id}/org-nodes/{sec_node['id']}/fee-items",
        json={
            "items": [
                {"feeStructureId": t_id, "amountPaise": 600000, "feePlanId": None},
                {"feeStructureId": tr_id, "amountPaise": 50000, "feePlanId": None},
            ]
        },
    )
    assert put.status_code == 200
    assert len(put.json()) == 2

    detail = client.get(
        f"/v1/institutes/{institute_id}/sections/{section_id}/students/stu-1/fees"
    )
    assert detail.status_code == 200
    fees = {row["feeStructureId"]: row for row in detail.json()["fees"]}
    assert fees[t_id]["amountPaise"] == 600000
    assert fees[tr_id]["amountPaise"] == 50000
    assert detail.json()["billedPaise"] == 650000


def test_resolver_prefers_deeper_org_node(client: TestClient, db: Session):
    institute_id, section_id = seed(db)
    flat = client.get(f"/v1/institutes/{institute_id}/org-nodes").json()
    sec_node = next(n for n in flat if n.get("sectionId") == section_id)
    parent_id = sec_node.get("parentId")
    assert parent_id

    tuition = client.post(
        f"/v1/institutes/{institute_id}/fee-structures",
        json={"name": "Annual tuition", "amountPaise": 100},
    ).json()
    t_id = tuition["id"]

    client.put(
        f"/v1/institutes/{institute_id}/org-nodes/{parent_id}/fee-items",
        json={"items": [{"feeStructureId": t_id, "amountPaise": 400000, "feePlanId": None}]},
    )
    client.put(
        f"/v1/institutes/{institute_id}/org-nodes/{sec_node['id']}/fee-items",
        json={"items": [{"feeStructureId": t_id, "amountPaise": 500000, "feePlanId": None}]},
    )

    detail = client.get(
        f"/v1/institutes/{institute_id}/sections/{section_id}/students/stu-1/fees"
    ).json()
    tuition_line = next(f for f in detail["fees"] if f["feeStructureId"] == t_id)
    assert tuition_line["amountPaise"] == 500000
