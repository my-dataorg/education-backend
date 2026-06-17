# Phase 2 — Education MVP (started)

## Running

| Service | URL |
|---------|-----|
| Education UI | http://localhost:3010 |
| Education API | http://localhost:8010 |

## Try it

1. Subscribe to **Education** on platform marketplace (if not already)
2. Dashboard → **Launch** Education (or open http://localhost:3010)
3. **Create institute** — you become owner
4. Open institute → **Add section**
5. Open section → **Add assignment** (owner/teacher) or **Post note**
6. Share **join code** — another user joins as student → can **submit** work

## API (education-backend)

- `POST /v1/institutes` — create
- `POST /v1/institutes/join` — join with code
- `GET/POST /v1/institutes/{id}/sections`
- `POST /v1/sections/{id}/assignments`
- `POST /v1/sections/{id}/notes`
- `POST /v1/assignments/{id}/submissions`

All routes require JWT + active Education subscription.

## Still TODO (Phase 2 remainder)

- Email invitations
- Assign teachers/students to sections via UI
- Member role management UI
- Student reports + share links
