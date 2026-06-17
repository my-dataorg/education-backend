#!/usr/bin/env python3
"""Stage 2 API E2E checks — auto-subscribe on invite accept. Requires stack up."""

from __future__ import annotations

import json
import sys
import urllib.error
import urllib.parse
import urllib.request

KEYCLOAK = "http://localhost:8080"
PLATFORM = "http://localhost:8002"
EDUCATION = "http://localhost:8010"
INTERNAL_TOKEN = "mydata-internal-dev-token"
PASSWORD = "demo1234"


def post_form(url: str, data: dict) -> dict:
    body = urllib.parse.urlencode(data).encode()
    req = urllib.request.Request(url, data=body, method="POST")
    with urllib.request.urlopen(req, timeout=20) as resp:
        return json.loads(resp.read())


def request_json(method: str, url: str, *, headers: dict | None = None, payload: dict | None = None):
    data = json.dumps(payload).encode() if payload is not None else None
    h = dict(headers or {})
    if payload is not None:
        h["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, method=method, headers=h)
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            raw = resp.read()
            return resp.status, json.loads(raw) if raw else {}
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode()
        try:
            body = json.loads(raw)
        except json.JSONDecodeError:
            body = {"detail": raw}
        return exc.code, body


def get_json(url: str, headers: dict) -> dict | list:
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=20) as resp:
        return json.loads(resp.read())


def admin_token() -> str:
    data = post_form(
        f"{KEYCLOAK}/realms/master/protocol/openid-connect/token",
        {
            "grant_type": "password",
            "client_id": "admin-cli",
            "username": "admin",
            "password": "admin",
        },
    )
    return data["access_token"]


def ensure_user(admin_h: dict, email: str, first: str, last: str) -> str:
    q = urllib.parse.urlencode({"email": email, "exact": "true"})
    users = get_json(f"{KEYCLOAK}/admin/realms/mydata/users?{q}", admin_h)
    if users:
        return users[0]["id"]
    request_json(
        "POST",
        f"{KEYCLOAK}/admin/realms/mydata/users",
        headers=admin_h,
        payload={
            "username": email,
            "email": email,
            "firstName": first,
            "lastName": last,
            "enabled": True,
            "emailVerified": True,
            "credentials": [{"type": "password", "value": PASSWORD, "temporary": False}],
        },
    )
    users = get_json(f"{KEYCLOAK}/admin/realms/mydata/users?{q}", admin_h)
    return users[0]["id"]


def user_token(email: str) -> tuple[str, str]:
    data = post_form(
        f"{KEYCLOAK}/realms/mydata/protocol/openid-connect/token",
        {
            "grant_type": "password",
            "client_id": "platform-frontend",
            "username": email,
            "password": PASSWORD,
        },
    )
    token = data["access_token"]
    payload = token.split(".")[1]
    payload += "=" * (-len(payload) % 4)
    sub = json.loads(__import__("base64").urlsafe_b64decode(payload))["sub"]
    return token, sub


def has_education_subscription(token: str) -> bool:
    subs = get_json(f"{PLATFORM}/v1/users/me/subscriptions", {"Authorization": f"Bearer {token}"})
    return any(item.get("productSlug") == "education" for item in subs.get("items", []))


def invite_and_accept(
    demo_h: dict,
    iid: str,
    email: str,
    role: str,
) -> tuple[int, dict]:
    request_json(
        "POST",
        f"{EDUCATION}/v1/institutes/{iid}/invitations",
        headers=demo_h,
        payload={"email": email, "role": role},
    )
    token, _ = user_token(email)
    invitee_h = {"Authorization": f"Bearer {token}"}
    pending = get_json(f"{EDUCATION}/v1/users/me/invitations", invitee_h)
    if not pending:
        return 404, {"detail": "no pending invitation"}
    inv_id = pending[0]["id"]
    return request_json(
        "POST", f"{EDUCATION}/v1/invitations/{inv_id}/accept", headers=invitee_h, payload={}
    )


def main() -> int:
    failures: list[str] = []

    admin_h = {"Authorization": f"Bearer {admin_token()}"}
    ensure_user(admin_h, "applicant@mydata.local", "Applicant", "Test")

    demo_token, _ = user_token("demo@mydata.local")
    demo_h = {"Authorization": f"Bearer {demo_token}"}

    institutes = get_json(f"{EDUCATION}/v1/institutes", demo_h)
    if not institutes:
        print("No institutes for demo user — create one first")
        return 1
    iid = institutes[0]["id"]
    print(f"Using institute: {institutes[0]['name']}")

    # T2.1 / T2.2 — fresh accept auto-subscribes applicant (or re-accept if already member)
    applicant_token, applicant_sub = user_token("applicant@mydata.local")
    applicant_h = {"Authorization": f"Bearer {applicant_token}"}

    status, body = invite_and_accept(demo_h, iid, "applicant@mydata.local", "teacher")
    if status not in (200, 201):
        failures.append(f"T2.1 accept failed: {status} {body}")

    if not has_education_subscription(applicant_token):
        failures.append("T2.2 education subscription missing after accept")

    inst_status, inst_body = request_json("GET", f"{EDUCATION}/v1/institutes", headers=applicant_h)
    if inst_status != 200:
        failures.append(f"T2.1 institutes list failed: {inst_status} {inst_body}")

    # T2.3 — re-accept + duplicate subscribe is idempotent
    status, body = invite_and_accept(demo_h, iid, "applicant@mydata.local", "teacher")
    if status not in (200, 201):
        failures.append(f"T2.3 re-accept failed: {status} {body}")
    sub1 = request_json(
        "POST",
        f"{PLATFORM}/internal/users/{applicant_sub}/subscriptions",
        headers={"X-Internal-Token": INTERNAL_TOKEN},
        payload={"productSlug": "education"},
    )
    sub2 = request_json(
        "POST",
        f"{PLATFORM}/internal/users/{applicant_sub}/subscriptions",
        headers={"X-Internal-Token": INTERNAL_TOKEN},
        payload={"productSlug": "education"},
    )
    if sub1[0] != 200 or sub2[0] != 200:
        failures.append(f"T2.3 idempotent subscribe failed: {sub1[0]} {sub2[0]}")

    # T2.4 — student accept with a fresh user
    student_email = "student2@mydata.local"
    ensure_user(admin_h, student_email, "Student", "Two")
    status, body = invite_and_accept(demo_h, iid, student_email, "student")
    if status not in (200, 201):
        failures.append(f"T2.4 student accept failed: {status} {body}")
    else:
        stoken, _ = user_token(student_email)
        if not has_education_subscription(stoken):
            failures.append("T2.4 student missing education subscription")
        inst_status, _ = request_json(
            "GET", f"{EDUCATION}/v1/institutes", headers={"Authorization": f"Bearer {stoken}"}
        )
        if inst_status != 200:
            failures.append(f"T2.4 student cannot list institutes: {inst_status}")

    if failures:
        print("\nFAILURES:")
        for f in failures:
            print(f"  - {f}")
        return 1

    print("\nAll Stage 2 API E2E checks PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
