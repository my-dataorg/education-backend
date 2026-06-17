# Roles — education-backend

Defined in `app/roles.py`.

## Roles

| Role | Label |
|------|-------|
| owner | Owner |
| admin | Admin |
| principal | Principal |
| teacher | Teacher |
| lecturer | Lecturer |
| professor | Professor |
| student | Student |

## Permission groups

| Group | Roles |
|-------|-------|
| MANAGE_ROLES | owner, admin |
| STAFF_ROLES | owner, admin, principal, teacher, lecturer, professor |
| TEACHING_STAFF | principal, teacher, lecturer, professor |
| STUDENT | student |

## Capabilities

| Action | owner/admin | teaching staff | student |
|--------|-------------|----------------|---------|
| Manage staff/students/branches | yes | read-only directory | no |
| Send invitations | yes | no | no |
| Create assignments/notes | yes | yes | no |
| Submit work | no* | no* | yes |

\*Unless also enrolled as student in section.

## Invitable roles

Staff: admin, principal, teacher, lecturer, professor  
Students: student

Owner cannot be assigned via invitation — only institute creator is owner.
