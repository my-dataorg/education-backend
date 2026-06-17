# API — education-backend

Base URL: `http://localhost:8010` · Prefix: `/v1`

## Auth tiers

| Tier | Dependency | Routes |
|------|------------|--------|
| Public health | None | `/health` |
| Logged-in user | JWT only | Invitation list/accept/reject |
| Education subscriber | JWT + `education` subscription | Most institute routes |

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
