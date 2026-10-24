"""Build per-student frozen question snapshots (variants + shuffle)."""

import hashlib
import json
import random
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    AssignmentQuestion,
    AssignmentQuestionOption,
    AssignmentQuestionVariant,
)


def _rng_for(student_id: str, assignment_id: str) -> random.Random:
    digest = hashlib.sha256(f"{assignment_id}:{student_id}".encode()).hexdigest()
    seed = int(digest[:16], 16)
    return random.Random(seed)


def build_snapshot(
    db: Session,
    assignment_id: str,
    student_id: str,
    questions: list[AssignmentQuestion],
) -> dict[str, Any]:
    rng = _rng_for(student_id, assignment_id)
    question_rows = sorted(questions, key=lambda q: q.sort_order)
    rng.shuffle(question_rows)

    items: list[dict[str, Any]] = []
    for q in question_rows:
        variants = list(
            db.scalars(
                select(AssignmentQuestionVariant)
                .where(AssignmentQuestionVariant.question_id == q.id)
                .order_by(AssignmentQuestionVariant.variant_index)
            )
        )
        if not variants:
            continue
        variant = variants[rng.randrange(len(variants))]
        meta = json.loads(variant.metadata_json or "{}")
        item: dict[str, Any] = {
            "questionId": q.id,
            "type": q.question_type,
            "points": q.points,
            "required": q.required,
            "variantId": variant.id,
            "stem": variant.stem_text,
            "metadata": meta,
        }
        if q.question_type == "single_choice":
            options = list(
                db.scalars(
                    select(AssignmentQuestionOption).where(
                        AssignmentQuestionOption.variant_id == variant.id
                    )
                )
            )
            opt_payload = [{"key": o.option_key, "label": o.label} for o in options]
            rng.shuffle(opt_payload)
            item["options"] = opt_payload
        items.append(item)

    return {"assignmentId": assignment_id, "studentId": student_id, "questions": items}
