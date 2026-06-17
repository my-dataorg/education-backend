# Cursor agents — education-backend

Education product API: institutes, members, invitations, branches, sections, assignments.

## Education agents

| Agent | When to use |
|-------|-------------|
| **backend-developer** | **Primary** — all API implementation, services, auth, migrations |
| **edu-super** | Domain model, permissions, API design |
| **edu-staff** | Staff roles, invitations, branches, member APIs |
| **edu-student** | Admissions, sections, submissions |

## General agents

| Agent | When to use |
|-------|-------------|
| **planner** | Task breakdown |
| **testing-agent** | Run `pytest` |
| **code-review** | Review diff |
| **documentation** | Update `docs/api.md` |

## Feature flow

```
edu-super → planner → implement → testing-agent → code-review → documentation
```

## Docs in this repo

| Doc | Purpose |
|-----|---------|
| [README.md](README.md) | Run on port 8010 |
| [docs/api.md](docs/api.md) | REST routes |
| [docs/roles.md](docs/roles.md) | Role matrix |
| [docs/architecture.md](docs/architecture.md) | Domain model, data ownership |

## Rules

See `.cursor/rules/` — `backend-python`, `api-boundaries`, `simple-code`.

## Related repos

- [education-frontend](https://github.com/my-dataorg/education-frontend)
- [platform-backend](https://github.com/my-dataorg/platform-backend) — subscription checks
