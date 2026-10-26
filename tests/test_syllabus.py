import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app import main
from app.db.session import get_db
from app.models import (
    Base,
    Institute,
    InstituteMember,
    Section,
    SectionMember,
    SectionSubject,
    Subject,
)
from app.services.syllabus import (
    apply_weight_updates,
    build_tree,
    copy_syllabus_between_sections,
    create_node,
    delete_node,
    set_leaf_completion,
    validate_sibling_weights,
)
from app.models import SectionSyllabusNode


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


def seed_section_with_subject(db: Session) -> tuple[str, str]:
    institute = Institute(id="inst-1", name="School", join_code="CODE123456")
    db.add(institute)
    db.add(InstituteMember(institute_id=institute.id, user_id="owner", role="owner"))
    db.add(InstituteMember(institute_id=institute.id, user_id="teacher-1", role="teacher"))
    section = Section(id="sec-1", institute_id=institute.id, name="A", class_name="7")
    subject = Subject(id="sub-1", institute_id=institute.id, name="Math")
    db.add_all([section, subject])
    db.add(SectionSubject(section_id=section.id, subject_id=subject.id, weekly_periods=5))
    db.add(SectionMember(section_id=section.id, user_id="teacher-1", member_type="teacher"))
    db.commit()
    return section.id, subject.id


def test_validate_sibling_weights_rejects_bad_sum():
    nodes = [
        SectionSyllabusNode(
            section_id="s",
            subject_id="j",
            title="a",
            weight_percent=40,
            sort_order=0,
        ),
        SectionSyllabusNode(
            section_id="s",
            subject_id="j",
            title="b",
            weight_percent=50,
            sort_order=1,
        ),
    ]
    with pytest.raises(ValueError, match="sum to 100"):
        validate_sibling_weights(nodes)


def test_rollup_nested_and_subject_total(db: Session):
    section_id, subject_id = seed_section_with_subject(db)
    r1 = SectionSyllabusNode(
        section_id=section_id,
        subject_id=subject_id,
        title="R1",
        weight_percent=10,
        sort_order=0,
    )
    r2 = SectionSyllabusNode(
        section_id=section_id,
        subject_id=subject_id,
        title="R2",
        weight_percent=30,
        sort_order=1,
    )
    r3 = SectionSyllabusNode(
        section_id=section_id,
        subject_id=subject_id,
        title="R3",
        weight_percent=60,
        sort_order=2,
    )
    db.add_all([r1, r2, r3])
    db.flush()
    ch1 = SectionSyllabusNode(
        section_id=section_id,
        subject_id=subject_id,
        parent_id=r1.id,
        title="Ch1",
        weight_percent=100,
        sort_order=0,
    )
    db.add(ch1)
    db.flush()
    l1 = SectionSyllabusNode(
        section_id=section_id,
        subject_id=subject_id,
        parent_id=ch1.id,
        title="L1",
        weight_percent=50,
        sort_order=0,
    )
    l2 = SectionSyllabusNode(
        section_id=section_id,
        subject_id=subject_id,
        parent_id=ch1.id,
        title="L2",
        weight_percent=50,
        sort_order=1,
    )
    db.add_all([l1, l2])
    db.commit()
    set_leaf_completion(db, section_id, subject_id, l1.id, 80, "teacher-1")
    set_leaf_completion(db, section_id, subject_id, l2.id, 40, "teacher-1")
    tree = build_tree(db, section_id, subject_id, can_edit_completion=False)
    ch1_out = tree["nodes"][0]["children"][0]
    assert ch1_out["effectiveCompletedPercent"] == 60.0
    assert tree["subjectTotalCompletedPercent"] == 6.0


def test_leaf_only_completion_rejects_parent(db: Session, client: TestClient):
    section_id, subject_id = seed_section_with_subject(db)
    root = create_node(db, section_id, subject_id, "Only", 100)
    child = create_node(db, section_id, subject_id, "Child", 100, parent_id=root.id)
    main.app.dependency_overrides[main.require_education_subscription] = (
        lambda: {"id": "teacher-1", "email": "t@example.com", "token": "test"}
    )
    res = client.patch(
        f"/v1/sections/{section_id}/subjects/{subject_id}/syllabus/nodes/{root.id}/completion",
        json={"completedPercent": 50},
    )
    assert res.status_code == 422


def test_unlinked_subject_returns_404(db: Session, client: TestClient):
    section_id, _subject_id = seed_section_with_subject(db)
    other = Subject(id="sub-2", institute_id="inst-1", name="Science")
    db.add(other)
    db.commit()
    res = client.get(f"/v1/sections/{section_id}/subjects/sub-2/syllabus")
    assert res.status_code == 404


def test_teacher_cannot_create_nodes(db: Session, client: TestClient):
    section_id, subject_id = seed_section_with_subject(db)
    main.app.dependency_overrides[main.require_education_subscription] = (
        lambda: {"id": "teacher-1", "email": "t@example.com", "token": "test"}
    )
    res = client.post(
        f"/v1/sections/{section_id}/subjects/{subject_id}/syllabus/nodes",
        json={"title": "Ch", "weightPercent": 100},
    )
    assert res.status_code == 403


def test_copy_syllabus_to_other_section_resets_completion(db: Session):
    institute = Institute(id="inst-1", name="School", join_code="CODE123456")
    db.add(institute)
    db.add(InstituteMember(institute_id=institute.id, user_id="owner", role="owner"))
    subject = Subject(id="sub-1", institute_id=institute.id, name="Math")
    sec_a = Section(id="sec-a", institute_id=institute.id, name="A", class_name="7")
    sec_b = Section(id="sec-b", institute_id=institute.id, name="B", class_name="7")
    db.add_all([subject, sec_a, sec_b])
    for sid in ("sec-a", "sec-b"):
        db.add(SectionSubject(section_id=sid, subject_id=subject.id, weekly_periods=5))
    db.commit()

    leaf = create_node(db, "sec-a", subject.id, "Leaf", 100)
    set_leaf_completion(db, "sec-a", subject.id, leaf.id, 75, "teacher-1")

    result = copy_syllabus_between_sections(db, institute.id, "sec-a", ["sec-b"])
    assert result["subjectsCopied"] == 1
    assert result["nodesCopied"] == 1

    tree_b = build_tree(db, "sec-b", subject.id, can_edit_completion=False)
    assert len(tree_b["nodes"]) == 1
    assert tree_b["nodes"][0]["title"] == "Leaf"
    assert tree_b["nodes"][0]["completedPercent"] == 0


def test_copy_syllabus_rejects_self(db: Session):
    section_id, subject_id = seed_section_with_subject(db)
    create_node(db, section_id, subject_id, "Ch", 100)
    with pytest.raises(ValueError, match="itself"):
        copy_syllabus_between_sections(db, "inst-1", section_id, [section_id])


def _seed_root_weights(db: Session, section_id: str, subject_id: str, weights: list[tuple[str, float]]):
    nodes = [
        SectionSyllabusNode(
            section_id=section_id,
            subject_id=subject_id,
            title=title,
            weight_percent=weight,
            sort_order=i,
        )
        for i, (title, weight) in enumerate(weights)
    ]
    db.add_all(nodes)
    db.commit()
    return nodes


def test_apply_weight_updates_batch(db: Session):
    section_id, subject_id = seed_section_with_subject(db)
    roots = _seed_root_weights(
        db, section_id, subject_id, [("A", 25), ("B", 35), ("C", 40)]
    )
    apply_weight_updates(
        db,
        section_id,
        subject_id,
        [(roots[0].id, 30), (roots[1].id, 35), (roots[2].id, 35)],
    )
    tree = build_tree(db, section_id, subject_id, can_edit_completion=False)
    weights = {n["title"]: n["weightPercent"] for n in tree["nodes"]}
    assert weights == {"A": 30.0, "B": 35.0, "C": 35.0}


def test_apply_weight_updates_rejects_invalid_group(db: Session):
    section_id, subject_id = seed_section_with_subject(db)
    roots = _seed_root_weights(db, section_id, subject_id, [("A", 50), ("B", 50)])
    with pytest.raises(ValueError, match="sum to 100"):
        apply_weight_updates(db, section_id, subject_id, [(roots[0].id, 80)])


def test_delete_node_prorates_siblings(db: Session):
    section_id, subject_id = seed_section_with_subject(db)
    roots = _seed_root_weights(
        db,
        section_id,
        subject_id,
        [("A", 50), ("B", 25), ("C", 15), ("D", 10)],
    )
    delete_node(db, section_id, subject_id, roots[1].id)
    tree = build_tree(db, section_id, subject_id, can_edit_completion=False)
    titles = {n["title"]: n["weightPercent"] for n in tree["nodes"]}
    assert "B" not in titles
    assert abs(sum(titles.values()) - 100) < 0.05
    assert titles["A"] > 50


def test_second_sibling_splits_fifty_fifty(db: Session):
    section_id, subject_id = seed_section_with_subject(db)
    first = create_node(db, section_id, subject_id, "Only", 100)
    second = create_node(db, section_id, subject_id, "Second", 50)
    tree = build_tree(db, section_id, subject_id, can_edit_completion=False)
    by_title = {n["title"]: n["weightPercent"] for n in tree["nodes"]}
    assert by_title["Only"] == 50.0
    assert by_title["Second"] == 50.0
    assert first.id != second.id


def test_owner_cannot_patch_completion(db: Session, client: TestClient):
    section_id, subject_id = seed_section_with_subject(db)
    leaf = create_node(db, section_id, subject_id, "Leaf", 100)
    res = client.patch(
        f"/v1/sections/{section_id}/subjects/{subject_id}/syllabus/nodes/{leaf.id}/completion",
        json={"completedPercent": 25},
    )
    assert res.status_code == 403
