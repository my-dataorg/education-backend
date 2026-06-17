#!/usr/bin/env python3
"""Stage 3 API E2E — join requests. Requires stack up."""

from __future__ import annotations

import json
import sys
import urllib.error
import urllib.parse
import urllib.request
import uuid

KEYCLOAK = "http://localhost:8080"
PLATFORM = "http://localhost:8002"
EDUCATION = "http://localhost:8010"
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


def ensure_user(admin_h: dict, email: str) -> None:
    q = urllib.parse.urlencode({"email": email, "exact": "true"})
    users = get_json(f"{KEYCLOAK}/admin/realms/mydata/users?{q}", admin_h)
    if users:
        return
    request_json(
        "POST",
        f"{KEYCLOAK}/admin/realms/mydata/users",
        headers=admin_h,
        payload={
            "username": email,
            "email": email,
            "firstName": "Join",
            "lastName": "Test",
            "enabled": True,
            "emailVerified": True,
            "credentials": [{"type": "password", "value": PASSWORD, "temporary": False}],
        },
    )


def user_token(email: str) -> str:
    data = post_form(
        f"{KEYCLOAK}/realms/mydata/protocol/openid-connect/token",
        {
            "grant_type": "password",
            "client_id": "platform-frontend",
            "username": email,
            "password": PASSWORD,
        },
    )
    return data["access_token"]


def main() -> int:
    failures: list[str] = []
    suffix = uuid.uuid4().hex[:8]
    applicant_email = f"joinreq-{suffix}@mydata.local"
    reject_email = f"joinreq-rej-{suffix}@mydata.local"

    admin_h = {"Authorization": f"Bearer {admin_token()}"}
    ensure_user(admin_h, applicant_email)
    ensure_user(admin_h, reject_email)

    demo_token = user_token("demo@mydata.local")
    demo_h = {"Authorization": f"Bearer {demo_token}"}
    applicant_token = user_token(applicant_email)
    applicant_h = {"Authorization": f"Bearer {applicant_token}"}
    teacher_token = user_token("teacher@mydata.local")
    teacher_h = {"Authorization": f"Bearer {teacher_token}"}

    institutes = get_json(f"{EDUCATION}/v1/institutes", demo_h)
    if not institutes:
        print("No institute for demo user")
        return 1
    iid = institutes[0]["id"]
    print(f"Using institute: {institutes[0]['name']}")

    status, body = request_json(
        "POST",
        f"{EDUCATION}/v1/institutes/{iid}/join-requests",
        headers=applicant_h,
        payload={"requestedRole": "student", "message": "E2E join request"},
    )
    if status not in (200, 201):
        failures.append(f"T3.1 submit failed: {status} {body}")
    req_id = body.get("id") if isinstance(body, dict) else None

    pending = get_json(f"{EDUCATION}/v1/users/me/join-requests", applicant_h)
    if not pending:
        failures.append("T3.1 no pending request for applicant")

    inst_status, inst_body = request_json("GET", f"{EDUCATION}/v1/institutes", headers=applicant_h)
    if inst_status == 200 and inst_body:
        failures.append("T3.1 applicant should not be member yet")

    if not req_id and pending:
        req_id = pending[0]["id"]

    status, body = request_json(
        "GET", f"{EDUCATION}/v1/institutes/{iid}/join-requests?status=pending", headers=demo_h
    )
    if status != 200:
        failures.append(f"T3.2 owner list failed: {status} {body}")
    elif req_id and not any(r.get("id") == req_id for r in body):
        failures.append("T3.2 owner does not see join request")

    status, _ = request_json(
        "GET", f"{EDUCATION}/v1/institutes/{iid}/join-requests", headers=teacher_h
    )
    if status != 403:
        failures.append(f"T3.5 expected 403 for teacher, got {status}")

    status, body = request_json(
        "POST",
        f"{EDUCATION}/v1/institutes/{iid}/join-requests",
        headers=applicant_h,
        payload={"requestedRole": "student", "message": "duplicate"},
    )
    if status not in (400, 409):
        failures.append(f"T3.6 expected 400 for duplicate, got {status} {body}")

    if req_id:
        status, body = request_json(
            "POST", f"{EDUCATION}/v1/join-requests/{req_id}/accept", headers=demo_h, payload={}
        )
        if status not in (200, 201):
            failures.append(f"T3.3 accept failed: {status} {body}")
        subs = get_json(f"{PLATFORM}/v1/users/me/subscriptions", applicant_h)
        if not any(s.get("productSlug") == "education" for s in subs.get("items", [])):
            failures.append("T3.3 applicant not subscribed after accept")
        inst_status, inst_body = request_json("GET", f"{EDUCATION}/v1/institutes", headers=applicant_h)
        if inst_status != 200 or not inst_body:
            failures.append("T3.3 applicant cannot see institute after accept")

    rej_token = user_token(reject_email)
    rej_h = {"Authorization": f"Bearer {rej_token}"}
    request_json(
        "POST",
        f"{EDUCATION}/v1/institutes/{iid}/join-requests",
        headers=rej_h,
        payload={"requestedRole": "teacher", "message": "reject me"},
    )
    pending2 = get_json(f"{EDUCATION}/v1/users/me/join-requests", rej_h)
    if pending2:
        rid = pending2[0]["id"]
        status, _ = request_json(
            "POST", f"{EDUCATION}/v1/join-requests/{rid}/reject", headers=demo_h, payload={}
        )
        if status not in (200, 204):
            failures.append(f"T3.4 reject failed: {status}")
        still_pending = get_json(f"{EDUCATION}/v1/users/me/join-requests", rej_h)
        if still_pending:
            failures.append("T3.4 request still pending after reject")

    if failures:
        print("\nFAILURES:")
        for f in failures:
            print(f"  - {f}")
        return 1
    print("\nAll Stage 3 API E2E checks PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
