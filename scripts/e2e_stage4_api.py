#!/usr/bin/env python3
"""Stage 4 API E2E — section enrollment + workspace. Requires stack up."""

from __future__ import annotations

import json
import sys
import urllib.error
import urllib.parse
import urllib.request

KEYCLOAK = "http://localhost:8080"
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


def get_json(url: str, headers: dict):
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=20) as resp:
        return json.loads(resp.read())


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


def user_id_from_token(token: str) -> str:
    payload = token.split(".")[1]
    payload += "=" * (-len(payload) % 4)
    return json.loads(__import__("base64").urlsafe_b64decode(payload))["sub"]


def token_for_user_id(user_id: str, emails: list[str]) -> str | None:
    for email in emails:
        try:
            token = user_token(email)
            if user_id_from_token(token) == user_id:
                return token
        except Exception:
            continue
    return None


def main() -> int:
    failures: list[str] = []
    demo_h = {"Authorization": f"Bearer {user_token('demo@mydata.local')}"}

    institutes = get_json(f"{EDUCATION}/v1/institutes", demo_h)
    if not institutes:
        print("No institute")
        return 1
    iid = institutes[0]["id"]

    sections = get_json(f"{EDUCATION}/v1/institutes/{iid}/sections", demo_h)
    if not sections:
        status, sec = request_json(
            "POST",
            f"{EDUCATION}/v1/institutes/{iid}/sections",
            headers=demo_h,
            payload={"name": "Section A", "className": "Grade 10"},
        )
        if status not in (200, 201):
            failures.append(f"Could not create section: {status}")
            return 1
        sid = sec["id"]
    else:
        sid = sections[0]["id"]

    members = get_json(f"{EDUCATION}/v1/institutes/{iid}/members", demo_h)
    teacher_id = next((m["userId"] for m in members if m["role"] == "teacher"), None)
    student_id = next((m["userId"] for m in members if m["role"] == "student"), None)
    if not teacher_id or not student_id:
        failures.append("Need teacher and student members in institute")
        return 1

    teacher_token = token_for_user_id(
        teacher_id, ["teacher@mydata.local", "applicant@mydata.local"]
    )
    student_token = token_for_user_id(
        student_id,
        [
            "student@mydata.local",
            "student2@mydata.local",
            "joinreq@mydata.local",
            "applicant@mydata.local",
        ],
    )
    if not teacher_token or not student_token:
        print("Could not match member userIds to known test emails")
        return 1

    teacher_h = {"Authorization": f"Bearer {teacher_token}"}
    student_h = {"Authorization": f"Bearer {student_token}"}

    # T4.1 assign teacher
    status, _ = request_json(
        "POST",
        f"{EDUCATION}/v1/sections/{sid}/members",
        headers=demo_h,
        payload={"userId": teacher_id, "memberType": "teacher"},
    )
    if status not in (200, 201):
        failures.append(f"T4.1 assign teacher failed: {status}")

    # T4.2 assign student
    status, _ = request_json(
        "POST",
        f"{EDUCATION}/v1/sections/{sid}/members",
        headers=demo_h,
        payload={"userId": student_id, "memberType": "student"},
    )
    if status not in (200, 201):
        failures.append(f"T4.2 assign student failed: {status}")

    # T4.3 teacher sees only enrolled sections
    my_sections = get_json(f"{EDUCATION}/v1/users/me/institutes/{iid}/sections", teacher_h)
    if not any(s["id"] == sid for s in my_sections):
        failures.append("T4.3 teacher missing enrolled section")

    # T4.4 overview for teacher
    status, overview = request_json(
        "GET", f"{EDUCATION}/v1/sections/{sid}/overview", headers=teacher_h
    )
    if status != 200:
        failures.append(f"T4.4 overview failed: {status}")
    elif "students" not in overview:
        failures.append("T4.4 overview missing students for teacher")

    # T4.5 teacher creates assignment, student submits
    status, asn = request_json(
        "POST",
        f"{EDUCATION}/v1/sections/{sid}/assignments",
        headers=teacher_h,
        payload={"title": "E2E Homework", "description": "Test"},
    )
    if status not in (200, 201):
        failures.append(f"T4.5 create assignment failed: {status}")
    else:
        sub_status, _ = request_json(
            "POST",
            f"{EDUCATION}/v1/assignments/{asn['id']}/submissions",
            headers=student_h,
            payload={"content": "My work"},
        )
        if sub_status not in (200, 201):
            failures.append(f"T4.5 student submit failed: {sub_status}")
        _, overview2 = request_json(
            "GET", f"{EDUCATION}/v1/sections/{sid}/overview", headers=teacher_h
        )
        asn_overview = next(
            (a for a in overview2.get("assignments", []) if a.get("id") == asn["id"]),
            None,
        )
        if not asn_overview or asn_overview.get("submittedCount", 0) < 1:
            failures.append("T4.5 progress not updated after submit")

    # T4.6 student my-sections only enrolled
    status, student_sections = request_json(
        "GET", f"{EDUCATION}/v1/users/me/institutes/{iid}/sections", headers=student_h
    )
    if status != 200 or not any(s["id"] == sid for s in student_sections):
        failures.append("T4.6 student not seeing enrolled section")

    # T4.7 unassigned owner has empty my-sections
    owner_sections = get_json(f"{EDUCATION}/v1/users/me/institutes/{iid}/sections", demo_h)
    if any(s["id"] == sid for s in owner_sections):
        failures.append("T4.7 unassigned owner should not see section in my-sections")

    if failures:
        print("\nFAILURES:")
        for f in failures:
            print(f"  - {f}")
        return 1
    print("\nAll Stage 4 API E2E checks PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
