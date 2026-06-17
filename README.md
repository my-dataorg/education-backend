# education-backend

Education product API — institutes, members, invitations, branches, sections, assignments.

**Org:** [my-dataorg](https://github.com/my-dataorg) · **Stack:** FastAPI · SQLAlchemy · PostgreSQL

## Run locally

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
uvicorn app.main:app --reload --port 8010
```

Database: PostgreSQL `education_db` on localhost **5433** (see platform-backend infra).

## Documentation

| Doc | Description |
|-----|-------------|
| [AGENTS.md](AGENTS.md) | Cursor agents |
| [docs/api.md](docs/api.md) | REST routes |
| [docs/roles.md](docs/roles.md) | Permission matrix |
| [docs/architecture.md](docs/architecture.md) | Domain model |
| [docs/roadmap.md](docs/roadmap.md) | MVP status |

## Related repos

- [education-frontend](https://github.com/my-dataorg/education-frontend)
- [platform-backend](https://github.com/my-dataorg/platform-backend) — subscription checks

## Tests

```bash
pytest
```
