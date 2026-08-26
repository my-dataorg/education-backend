from app.services.user_identity import enrich_rows


def test_enrich_rows_uses_platform_names(monkeypatch):
    monkeypatch.setattr(
        "app.services.user_identity.get_users_brief",
        lambda ids: {
            "t1": {
                "firstName": "Priya",
                "lastName": "Sharma",
                "displayName": "Priya Sharma",
                "email": "priya@school.test",
                "username": "priya",
            }
        },
    )
    rows = enrich_rows([{"userId": "t1", "role": "teacher"}])
    assert rows[0]["firstName"] == "Priya"
    assert rows[0]["lastName"] == "Sharma"
    assert rows[0]["displayName"] == "Priya Sharma"
