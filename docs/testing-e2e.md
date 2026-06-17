# E2E testing — education membership lifecycle

Run against the local stack (`bash scripts/run-all.sh` from repo root).

## Prerequisites

| Service | Port | Health |
|---------|------|--------|
| Keycloak | 8080 | `curl -sf http://localhost:8080/realms/mydata` |
| platform-backend | 8002 | `curl -sf http://localhost:8002/health` |
| education-backend | 8010 | `curl -sf http://localhost:8010/health` |
| platform-frontend | 3000 | open http://localhost:3000 |
| education-frontend | 3010 | open http://localhost:3010 |

Ensure matching internal tokens in `.env`:

- `platform-backend`: `INTERNAL_API_TOKEN=mydata-internal-dev-token`
- `education-backend`: `PLATFORM_INTERNAL_TOKEN=mydata-internal-dev-token`

## Mock users (Keycloak realm `mydata`)

All passwords: **`demo1234`**

| Email | Purpose |
|-------|---------|
| `demo@mydata.local` | Default demo user; often institute owner in dev |
| `owner@mydata.local` | Dedicated institute owner for RBAC scenarios |
| `admin@mydata.local` | Institute admin |
| `teacher@mydata.local` | Invited teacher |
| `student@mydata.local` | Invited student |
| `applicant@mydata.local` | User with no institute (join-request flows) |

Users are seeded in `platform-backend/infra/local/keycloak/realm-mydata.json`.  
Re-import the realm or restart Keycloak after editing that file.

## Automated checks (Stage 0–1)

### Unit / integration (platform-backend)

```bash
cd platform-backend
.venv/bin/python -m pytest tests/test_internal_notifications.py tests/test_notifications_api.py -v
```

| ID | Check | Result |
|----|-------|--------|
| T0.1 | Missing/invalid `X-Internal-Token` → 401 | pytest |
| T0.2 | Valid token → 201 on `POST /internal/notifications` | pytest |
| — | User notifications API requires JWT | pytest |

### Live API E2E (Stage 1)

```bash
python314 education-backend/scripts/e2e_stage1_api.py
```

Requires at least one institute owned by `demo@mydata.local` (create via education UI if missing).

| ID | Scenario | Validates |
|----|----------|-----------|
| T1.1 | Owner sends teacher invite | `POST /v1/institutes/{id}/invitations` |
| T1.2 | Invitee sees platform notification | `GET /v1/users/me/notifications` |
| T1.3 | Teacher accepts via education API | invite removed from pending |
| T1.4 | Student invite + accept | same accept path |
| T1.5 | Wrong user cannot accept another's invite | 403/400/404 |
| T1.6 | Mark notification read | `PATCH /v1/users/me/notifications/{id}` |

Platform UI accept (`/invitations` BFF) proxies the same education-backend endpoint; API-level accept is sufficient for Stage 1 gate.

### Frontend builds

```bash
cd platform-frontend && npm run build
cd education-frontend && npm run build
```

## Manual smoke (optional)

1. Log in at http://localhost:3000 as `demo@mydata.local`.
2. Open **Inbox** from the user menu — notifications list loads.
3. Log in as `teacher@mydata.local` — inbox shows institute invite after owner sends invite.
4. Accept at http://localhost:3000/invitations or education app.

## Stage 1 verdict (2025-06-14)

**PASS** — pytest (5/5), live API E2E script, both frontend builds succeeded.

## Stage 2 — auto-subscribe on accept

### Unit / integration (platform-backend)

```bash
cd platform-backend
.venv/bin/python -m pytest tests/test_internal_subscriptions.py -v
```

### Live API E2E (Stage 2)

```bash
python314 education-backend/scripts/e2e_stage2_api.py
```

| ID | Scenario | Validates |
|----|----------|-----------|
| T2.1 | Accept invite without prior subscription | institutes list works |
| T2.2 | Subscriptions include `education` | platform-backend |
| T2.3 | Re-accept + idempotent subscribe | no error |
| T2.4 | Student accept + institute access | subscription + institutes |

**Platform unreachable:** membership accept still succeeds; subscribe failure is logged (task 2.4).

## Stage 2 verdict (2025-06-14)

**PASS** — internal subscribe pytest (4/4), live API E2E (`e2e_stage2_api.py`), frontend builds.

Next: Stage 3 (user → school join requests).

## Stage 3 verdict (2025-06-14)

**PASS** — `e2e_stage3_api.py` (T3.1–T3.6).

## Stage 4 — section enrollment

```bash
python314 education-backend/scripts/e2e_stage4_api.py
```

| ID | Scenario |
|----|----------|
| T4.1 | Admin assigns teacher to section |
| T4.2 | Admin assigns student |
| T4.3 | Teacher sees enrolled section only |
| T4.4 | Section overview for teacher |
| T4.5 | Assignment + student submit updates progress |
| T4.6 | Student sees enrolled section |
| T4.7 | Unassigned user has empty my-sections |

## Stage 4 verdict (2025-06-14)

**PASS** — `e2e_stage4_api.py` (T4.1–T4.7), education-frontend build.

Epic complete. Next: **documentation** agent updates `docs/api.md` contract docs.

## Stage 3 — join requests (reference)

```bash
python314 education-backend/scripts/e2e_stage3_api.py
```

| ID | Scenario |
|----|----------|
| T3.1 | Applicant submits join request (not a member yet) |
| T3.2 | Owner sees request in pending list |
| T3.3 | Owner accepts → member + subscribed |
| T3.4 | Owner rejects → not pending |
| T3.5 | Teacher cannot list requests (403) |
| T3.6 | Duplicate pending request blocked |
