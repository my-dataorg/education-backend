# API — education-backend

Base URL: `http://localhost:8010` · Prefix: `/v1`

## Auth tiers

| Tier | Dependency | Routes |
|------|------------|--------|
| Public health | None | `/health` |
| Logged-in user | JWT only | Invitations, join requests (submit/list own), institute lookup |
| Education subscriber | JWT + `education` subscription | Most institute admin routes |

Header: `Authorization: Bearer <JWT>` · Optional: `X-User-Email` for invitation matching

## Institutes

| Method | Path | Description |
|--------|------|-------------|
| GET | `/v1/institutes` | List user's institutes |
| POST | `/v1/institutes` | Create (→ owner) |
| POST | `/v1/institutes/join` | Join with code (→ student) |
| GET | `/v1/institutes/{id}` | Detail + stats |
| DELETE | `/v1/institutes/{id}` | Delete (owner only) |
| GET | `/v1/institutes/{id}/summary` | Branch summary |

## Members & invitations

| Method | Path | Description |
|--------|------|-------------|
| GET | `/v1/institutes/{id}/members` | Roster (`?group=staff\|students`) |
| PATCH | `/v1/institutes/{id}/members/{userId}` | Change role |
| DELETE | `/v1/institutes/{id}/members/{userId}` | Remove member |
| GET | `/v1/institutes/{id}/invitations` | List invitations |
| POST | `/v1/institutes/{id}/invitations` | Send invite |
| GET | `/v1/institutes/{id}/users/search?q=` | Keycloak user search (2+ chars) |
| GET | `/v1/users/me/invitations` | Pending for current user |
| POST | `/v1/invitations/{id}/accept` | Accept |
| POST | `/v1/invitations/{id}/reject` | Decline |

## Join requests

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| GET | `/v1/institutes/lookup?joinCode=` | JWT | Resolve institute by join code |
| POST | `/v1/institutes/{id}/join-requests` | JWT | Submit request `{ requestedRole, message }` |
| GET | `/v1/institutes/{id}/join-requests?status=pending` | Subscriber + manage | Admin list pending |
| GET | `/v1/users/me/join-requests` | JWT | User's pending requests |
| POST | `/v1/join-requests/{id}/accept` | Subscriber + manage | Accept → member + auto-subscribe |
| POST | `/v1/join-requests/{id}/reject` | Subscriber + manage | Reject + notify user |

## Section enrollment

| Method | Path | Description |
|--------|------|-------------|
| GET | `/v1/institutes/{id}/members/{userId}/sections` | Admin: member enrollments |
| GET | `/v1/users/me/institutes/{id}/sections` | Current user's enrolled sections |
| POST | `/v1/sections/{id}/members` | Assign `{ userId, memberType }` |
| DELETE | `/v1/sections/{id}/members/{userId}` | Remove enrollment |
| GET | `/v1/sections/{id}/overview` | Students, assignments, progress |

## Branches & sections

| Method | Path | Description |
|--------|------|-------------|
| GET/POST | `/v1/institutes/{id}/branches` | List / create |
| PATCH/DELETE | `/v1/institutes/{id}/branches/{branchId}` | Update / delete |
| GET/POST | `/v1/institutes/{id}/sections` | List / create sections |
| POST | `/v1/sections/{id}/teachers` | Assign teacher |
| POST | `/v1/sections/{id}/students` | Enroll student |

## Instruction

| Method | Path | Description |
|--------|------|-------------|
| GET/POST | `/v1/sections/{id}/notes` | Daily notes |
| GET/POST | `/v1/sections/{id}/assignments` | Assignments |
| POST | `/v1/assignments/{id}/submissions` | Student submit |

## Subscription check

Calls `platform-backend` `GET /v1/users/me/subscriptions` — requires `education` slug.
