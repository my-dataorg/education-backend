import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from app import main
from app.db.session import get_db
from app.models import Base, Institute, InstituteMember, Section
from app.services import fee_finance as finance_service


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
    inst = Institute(id="inst-res", name="School", join_code="RESSC")
    section = Section(id="sec-res", institute_id=inst.id, name="A", class_name="10")
    db.add_all([inst, section, InstituteMember(institute_id=inst.id, user_id="owner", role="owner")])
    db.commit()
    return inst.id, section.id


def test_fee_ladder_resolution(client: TestClient, db: Session):
    institute_id, section_id = seed(db)
    finance_service.put_institute_fee_default(db, institute_id, "owner", 500_000, None, None)
    put = client.put(
        f"/v1/institutes/{institute_id}/sections/{section_id}/fee-default",
        json={"amountPaise": 2_000_000, "feePlanId": None, "feeStructureId": None},
    )
    assert put.status_code == 200

    from app.services.fee_resolution import resolve_standard_fee

    resolved = resolve_standard_fee(db, institute_id, section_id, "student-1")
    assert resolved["resolvedFrom"] == "section"
    assert resolved["amountPaise"] == 2_000_000

    finance_service.put_class_fee_default(db, institute_id, "owner", "10", 1_500_000, None, None)
    resolved2 = resolve_standard_fee(db, institute_id, section_id, "student-2")
    assert resolved2["resolvedFrom"] == "section"
    assert resolved2["amountPaise"] == 2_000_000

    db.execute(
        __import__("sqlalchemy").text("DELETE FROM section_fee_defaults WHERE section_id = :sid"),
        {"sid": section_id},
    )
    db.commit()
    resolved3 = resolve_standard_fee(db, institute_id, section_id, "student-3")
    assert resolved3["resolvedFrom"] == "class"
    assert resolved3["amountPaise"] == 1_500_000
