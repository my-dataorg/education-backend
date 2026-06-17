#!/usr/bin/env python3
"""Stage 0–1 API E2E checks for testing-agent. Run with stack up."""

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
    status, _ = request_json(
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
    if status not in (201, 409):
        raise RuntimeError(f"create user {email} failed: {status}")
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


def main() -> int:
    failures: list[str] = []

    # T0.1 / T0.2 live internal API
    status, _ = request_json(
        "POST",
        f"{PLATFORM}/internal/notifications",
        payload={"userId": "e2e-user", "type": "test", "title": "T", "body": "b"},
    )
    if status != 401:
        failures.append(f"T0.1 expected 401 without token, got {status}")

    status, body = request_json(
        "POST",
        f"{PLATFORM}/internal/notifications",
        headers={"X-Internal-Token": INTERNAL_TOKEN},
        payload={
            "userId": "e2e-user",
            "type": "test",
            "title": "Internal OK",
            "body": "live",
        },
    )
    if status != 201:
        failures.append(f"T0.2 expected 201 with token, got {status}: {body}")

    admin_h = {"Authorization": f"Bearer {admin_token()}"}
    teacher_id = ensure_user(admin_h, "teacher@mydata.local", "Teacher", "Test")
    student_id = ensure_user(admin_h, "student@mydata.local", "Student", "Test")
    ensure_user(admin_h, "applicant@mydata.local", "Applicant", "Test")

    demo_token, _ = user_token("demo@mydata.local")
    demo_h = {"Authorization": f"Bearer {demo_token}"}

    institutes = get_json(f"{EDUCATION}/v1/institutes", demo_h)
    if not institutes:
        failures.append("T1.1 demo user has no institutes — create one in UI first")
        print_results(failures)
        return 1

    institute = institutes[0]
    iid = institute["id"]
    print(f"Using institute: {institute['name']} as {institute['role']}")

    # T1.1 send invite
    status, body = request_json(
        "POST",
        f"{EDUCATION}/v1/institutes/{iid}/invitations",
        headers=demo_h,
        payload={"email": "teacher@mydata.local", "role": "teacher"},
    )
    if status not in (200, 201):
        if "already pending" not in str(body).lower() and "already a member" not in str(body).lower():
            failures.append(f"T1.1 invite failed: {status} {body}")

    teacher_token, _ = user_token("teacher@mydata.local")
    teacher_h = {"Authorization": f"Bearer {teacher_token}"}

    # T1.2 platform inbox
    notifs = get_json(f"{PLATFORM}/v1/users/me/notifications", teacher_h)
    if not notifs.get("items"):
        failures.append("T1.2 teacher has no platform notifications after invite")
    else:
        print(f"T1.2 notification: {notifs['items'][0]['title']}")

    # T1.3 accept on education
    pending = get_json(f"{EDUCATION}/v1/users/me/invitations", teacher_h)
    if not pending:
        failures.append("T1.3 no pending invitation for teacher")
    else:
        inv_id = pending[0]["id"]
        status, body = request_json(
            "POST", f"{EDUCATION}/v1/invitations/{inv_id}/accept", headers=teacher_h, payload={}
        )
        if status not in (200, 201):
            failures.append(f"T1.3 accept failed: {status} {body}")
        else:
            pending2 = get_json(f"{EDUCATION}/v1/users/me/invitations", teacher_h)
            if pending2:
                failures.append("T1.3 invite still pending after accept")

    # T1.4 student invite + accept via education API (platform UI same backend)
    status, _ = request_json(
        "POST",
        f"{EDUCATION}/v1/institutes/{iid}/invitations",
        headers=demo_h,
        payload={"email": "student@mydata.local", "role": "student"},
    )
    student_token, _ = user_token("student@mydata.local")
    student_h = {"Authorization": f"Bearer {student_token}"}
    student_pending = get_json(f"{EDUCATION}/v1/users/me/invitations", student_h)
    if student_pending:
        inv_id = student_pending[0]["id"]
        status, _ = request_json(
            "POST", f"{EDUCATION}/v1/invitations/{inv_id}/accept", headers=student_h, payload={}
        )
        if status not in (200, 201):
            failures.append(f"T1.4 student accept failed: {status}")

    # T1.5 wrong user cannot accept someone else's invite
    status, _ = request_json(
        "POST",
        f"{EDUCATION}/v1/institutes/{iid}/invitations",
        headers=demo_h,
        payload={"email": "applicant@mydata.local", "role": "student"},
    )
    applicant_token, _ = user_token("applicant@mydata.local")
    applicant_h = {"Authorization": f"Bearer {applicant_token}"}
    app_pending = get_json(f"{EDUCATION}/v1/users/me/invitations", applicant_h)
    if app_pending and student_pending:
        # try to accept applicant's invite as student
        inv_id = app_pending[0]["id"]
        status, _ = request_json(
            "POST", f"{EDUCATION}/v1/invitations/{inv_id}/accept", headers=student_h, payload={}
        )
        if status not in (403, 400, 404):
            failures.append(f"T1.5 expected 403/400 for wrong user accept, got {status}")

    # T1.6 mark read
    notifs = get_json(f"{PLATFORM}/v1/users/me/notifications", teacher_h)
    if notifs.get("items"):
        nid = notifs["items"][0]["id"]
        status, out = request_json(
            "PATCH",
            f"{PLATFORM}/v1/users/me/notifications/{nid}",
            headers=teacher_h,
            payload={"read": True},
        )
        if status != 200 or not out.get("read"):
            failures.append(f"T1.6 mark read failed: {status}")

    # Platform frontend BFF smoke
    status, _ = request_json(
        "GET",
        "http://localhost:3000/api/notifications",
        headers={"Cookie": ""},
    )
    if status != 401:
        print(f"T1 BFF note: /api/notifications without session returned {status} (401 expected)")

    print_results(failures)
    return 1 if failures else 0


def print_results(failures: list[str]) -> None:
    if failures:
        print("\nFAILURES:")
        for f in failures:
            print(f"  - {f}")
    else:
        print("\nAll Stage 0–1 API E2E checks PASSED")


if __name__ == "__main__":
    sys.exit(main())
