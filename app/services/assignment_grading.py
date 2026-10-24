"""Auto-score objective assignment responses."""

import json
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import AssignmentQuestion, AssignmentQuestionOption, AssignmentQuestionVariant


def _norm(s: str) -> str:
    return " ".join(s.strip().lower().split())


def score_response(
    db: Session,
    question: AssignmentQuestion,
    variant_id: str,
    answer: Any,
) -> float | None:
    qtype = question.question_type
    points = float(question.points or 0)
    if qtype == "essay":
        return None
    if qtype == "single_choice":
        if not isinstance(answer, str):
            return 0.0
        correct = db.scalar(
            select(AssignmentQuestionOption.option_key).where(
                AssignmentQuestionOption.variant_id == variant_id,
                AssignmentQuestionOption.is_correct.is_(True),
            )
        )
        return points if answer == correct else 0.0
    if qtype == "short_text":
        if not isinstance(answer, str):
            return 0.0
        variant = db.get(AssignmentQuestionVariant, variant_id)
        meta = json.loads(variant.metadata_json if variant else "{}")
        acceptable = meta.get("acceptable") or []
        if not acceptable and variant:
            acceptable = [_norm(variant.stem_text)] if variant.stem_text else []
        return points if _norm(answer) in {_norm(a) for a in acceptable} else 0.0
    if qtype == "fill_blank":
        if not isinstance(answer, dict):
            return 0.0
        variant = db.get(AssignmentQuestionVariant, variant_id)
        meta = json.loads(variant.metadata_json if variant else "{}")
        blanks = meta.get("blanks") or []
        if not blanks:
            return None
        got = 0
        for blank in blanks:
            bid = blank.get("id")
            opts = blank.get("acceptable") or []
            val = answer.get(bid) if isinstance(answer, dict) else None
            if val and _norm(str(val)) in {_norm(str(o)) for o in opts}:
                got += 1
        return points * (got / len(blanks)) if blanks else 0.0
    if qtype == "match_pairs":
        if not isinstance(answer, dict):
            return 0.0
        variant = db.get(AssignmentQuestionVariant, variant_id)
        meta = json.loads(variant.metadata_json if variant else "{}")
        pairs = meta.get("pairs") or []
        if not pairs:
            return None
        correct = 0
        for pair in pairs:
            left = pair.get("left")
            right = pair.get("right")
            if answer.get(left) == right:
                correct += 1
        return points * (correct / len(pairs)) if pairs else 0.0
    if qtype == "order_items":
        if not isinstance(answer, list):
            return 0.0
        variant = db.get(AssignmentQuestionVariant, variant_id)
        meta = json.loads(variant.metadata_json if variant else "{}")
        expected = meta.get("items") or []
        if not expected:
            return None
        return points if answer == expected else 0.0
    return None
