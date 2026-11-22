# Observability

Each product API configures logging, rate limits, and error responses from environment variables. This stack is FastAPI, so the settings below replace a Spring `application.properties` / `logback-spring.xml` pair.

## Log files

Local development (working directory of the API process):

| File | Path |
|---|---|
| Application | `logs/application.log` |
| Errors | `logs/error.log` |
| Access | `logs/access.log` |

Docker, when `LOG_DIR` is unset and `RUNNING_IN_DOCKER=1`:

| Location | Path |
|---|---|
| Inside the container | `/var/log/mydata/application.log`, `error.log`, `access.log` |
| `docker logs <container>` | stdout and stderr (the same records, plus access lines) |
| Host volume example | `./logs/platform-backend:/var/log/mydata` |

Mount one host directory per service so files are not mixed:

```yaml
services:
  platform-backend:
    volumes:
      - ./logs/platform-backend:/var/log/mydata
```

Rotation keeps daily and size-based archives (`application.log.YYYYMMDD-HHMMSS-ffffff`). Defaults: 10 MB per file, 14 rotated files, 14 days. Older archives are deleted.

## Environment

```bash
LOG_LEVEL=INFO
LOG_DIR=logs
LOG_TO_FILE=true
LOG_MAX_BYTES=10485760
LOG_BACKUP_COUNT=14
LOG_RETENTION_DAYS=14
LOG_ACCESS_ENABLED=true

RATE_LIMIT_ENABLED=true
RATE_LIMIT_REQUESTS=120
RATE_LIMIT_WINDOW_SECONDS=60
RATE_LIMIT_AUTH_REQUESTS=30
RATE_LIMIT_AUTH_PATHS=/v1/auth/login,/v1/auth/signup,/v1/auth/token
RATE_LIMIT_EXEMPT_PATHS=/health,/ready,/docs,/redoc,/openapi.json,/favicon.ico
RATE_LIMIT_RULES=POST:/v1/auth/login=10
RATE_LIMIT_REDIS_URL=
RATE_LIMIT_TRUST_PROXY=false
```

`RATE_LIMIT_RULES` entries are `METHOD:/path=limit` or `METHOD:/prefix*=limit`, separated by commas. Auth paths use `RATE_LIMIT_AUTH_REQUESTS`. Every other route uses `RATE_LIMIT_REQUESTS` per client IP per window.

Set `RATE_LIMIT_REDIS_URL=redis://localhost:6379/0` when more than one API process is running. Local Redis is already defined in `platform-backend/infra/local/docker-compose.yml`. If Redis is down, the process logs a warning and uses its in-memory limiter so normal traffic is not blocked.

`/health` and `/ready` are exempt. `/ready` runs `SELECT 1` and returns 503 when the database is unavailable. Do not log passwords, tokens, or request bodies. Over-limit responses are HTTP 429 problem+json with `Retry-After` and `X-Request-Id`.

Run a service with access logs owned by this module:

```bash
uvicorn app.main:app --host 0.0.0.0 --port <service-port> --no-access-log
```

Pytest disables rate limits and file logging unless `RATE_LIMIT_ENABLED=true` or `LOG_TO_FILE=true` is set in the test.
