from app.services.assignment_grading import _norm, score_response
from app.services.assignment_snapshot import _rng_for


def test_rng_deterministic():
    a = _rng_for("s1", "a1").random()
    b = _rng_for("s1", "a1").random()
    c = _rng_for("s2", "a1").random()
    assert a == b
    assert a != c


def test_norm():
    assert _norm("  Hello   World ") == "hello world"
