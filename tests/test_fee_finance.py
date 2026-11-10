import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app import main
from app.db.session import get_db
from app.models import Base, Institute, InstituteMember, Section


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
    inst = Institute(id="inst-f1", name="School", join_code="F1SC")
    section = Section(id="sec-f1", institute_id=inst.id, name="A", class_name="10")
    db.add_all(
        [
            inst,
            section,
            InstituteMember(institute_id=inst.id, user_id="owner", role="owner"),
        ]
    )
    db.commit()
    return inst.id, section.id


def test_list_fee_structures_ensures_default_head(client: TestClient, db: Session):
    institute_id, _ = seed(db)
    res = client.get(f"/v1/institutes/{institute_id}/fee-structures")
    assert res.status_code == 200
    items = res.json()
    assert len(items) == 1
    assert items[0]["name"] == "Annual tuition"


def test_fee_plan_and_section_default(client: TestClient, db: Session):
    institute_id, section_id = seed(db)
    plan = client.post(
        f"/v1/institutes/{institute_id}/fee-plans",
        json={
            "name": "3 installments",
            "installmentCount": 3,
            "discountPercent": 0,
            "lateFeePaise": 50000,
            "dueScheduleNotes": "1 Apr, 1 Jul, 1 Oct",
        },
    )
    assert plan.status_code == 201
    body = plan.json()
    plan_id = body["id"]
    assert body["dueScheduleNotes"] == "1 Apr, 1 Jul, 1 Oct"

    put = client.put(
        f"/v1/institutes/{institute_id}/sections/{section_id}/fee-default",
        json={"amountPaise": 1000000, "feePlanId": plan_id},
    )
    assert put.status_code == 200
    assert put.json()["amountPaise"] == 1000000

    listed = client.get(f"/v1/institutes/{institute_id}/fee-plans")
    assert listed.status_code == 200
    assert len(listed.json()) == 1


def test_institute_expense(client: TestClient, db: Session):
    institute_id, _ = seed(db)
    res = client.post(
        f"/v1/institutes/{institute_id}/finance/expenses",
        json={
            "category": "institute",
            "kind": "rent",
            "label": "Building rent",
            "amountPaise": 25000000,
            "expenseDate": "2026-04-01",
            "notes": "April",
        },
    )
    assert res.status_code == 201
    items = client.get(f"/v1/institutes/{institute_id}/finance/expenses?category=institute")
    assert items.status_code == 200
    assert len(items.json()) == 1


def test_apply_unallocated_payments_to_lines():
    from app.services.fee_finance import apply_unallocated_payments_to_lines

    lines = [
        {"feeStructureId": "a", "amountPaise": 1_000_000, "paidPaise": 0, "balancePaise": 1_000_000},
        {"feeStructureId": "b", "amountPaise": 3_200_000, "paidPaise": 0, "balancePaise": 3_200_000},
    ]
    synced = apply_unallocated_payments_to_lines(lines, 4_200_000)
    assert sum(r["paidPaise"] for r in synced) == 4_200_000
    assert sum(r["balancePaise"] for r in synced) == 0


def test_section_fee_ledger_empty(client: TestClient, db: Session):
    institute_id, section_id = seed(db)
    overview = client.get(f"/v1/institutes/{institute_id}/section-fee-defaults")
    assert overview.status_code == 200
    assert len(overview.json()) == 1
    ledger = client.get(f"/v1/institutes/{institute_id}/sections/{section_id}/fees/ledger")
    assert ledger.status_code == 200
    assert ledger.json()["students"] == []
