# Architecture — education-backend

## Domain model

```
Institute
├── InstituteMember (role)
├── Branch
├── InstituteInvitation (pending → accepted/rejected)
└── Section (optional branch_id)
    ├── SectionMember (teacher | student)
    ├── Assignment → Submission
    └── DailyNote
```

## Owns (PostgreSQL `education_db`)

- Institutes, members, invitations, branches, sections
- Assignments, notes, submissions

## Does not own

- Global identity (Keycloak JWT `sub`)
- Subscriptions ([platform-backend](https://github.com/my-dataorg/platform-backend))
- Social relationships (future: social-backend API)

## Key modules

| Path | Purpose |
|------|---------|
| `app/services/institutes.py` | CRUD, members, branches, summary |
| `app/services/invitations.py` | Invite, accept, reject |
| `app/services/keycloak_users.py` | Admin user search for invites |
| `app/roles.py` | Role constants and permission helpers |
| `app/auth.py` | JWT + subscription gate |

## Tenancy

Every query scopes by `institute_id`. Cross-institute data leakage is forbidden.

## Events (planned)

- `education.institute.created`
- `education.assignment.submitted`
