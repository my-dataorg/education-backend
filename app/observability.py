"""Request logging, rate limiting, and safe error responses.

Configured with environment variables. File logs rotate by size and by day.
Redis is used for rate limits when RATE_LIMIT_REDIS_URL is set; otherwise
each process keeps an in-memory counter.
"""

from __future__ import annotations

import logging
import os
import re
import sys
import threading
import time
import uuid
from contextvars import ContextVar
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from starlette.datastructures import MutableHeaders

request_id_var: ContextVar[str] = ContextVar("request_id", default="-")

TRACE = 5
logging.addLevelName(TRACE, "TRACE")

_SECRET = re.compile(
    r"(?i)\b(password|passwd|secret|api[_-]?key|access[_-]?token|refresh[_-]?token|"
    r"authorization|jwt)\b(\s*[\"']?\s*[:=]\s*[\"']?)([^\"'\s,}&]+)"
)
_BEARER = re.compile(r"(?i)\bBearer\s+[A-Za-z0-9\-._~+/]+=*")

_configured = False
_env_loaded = False
_config_lock = threading.Lock()
_redis_client = None
_redis_lock = threading.Lock()
_last_redis_warning = 0.0

logger = logging.getLogger("app.observability")
access_logger = logging.getLogger("mydata.access")


def redact(value: str) -> str:
    cleaned = _BEARER.sub("Bearer [redacted]", value)
    return _SECRET.sub(r"\1\2[redacted]", cleaned)


class RedactFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str):
            record.msg = redact(record.msg)
        if isinstance(record.args, tuple):
            record.args = tuple(redact(item) if isinstance(item, str) else item for item in record.args)
        elif isinstance(record.args, dict):
            record.args = {
                key: redact(item) if isinstance(item, str) else item for key, item in record.args.items()
            }
        record.request_id = request_id_var.get() or "-"
        return True


class DailySizeRotatingFileHandler(logging.Handler):
    """Rotate when the file crosses max_bytes or the local date changes."""

    def __init__(self, directory: Path, basename: str, max_bytes: int, backup_count: int, retention_days: int):
        super().__init__()
        self.directory = directory
        self.basename = basename
        self.max_bytes = max_bytes
        self.backup_count = backup_count
        self.retention_days = retention_days
        self._lock = threading.RLock()
        self._day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        self._stream = None
        self._bytes = 0
        self._open_current()

    def _path(self) -> Path:
        return self.directory / self.basename

    def _open_current(self) -> None:
        self.directory.mkdir(parents=True, exist_ok=True)
        path = self._path()
        self._stream = open(path, "a", encoding="utf-8")  # noqa: SIM115
        self._bytes = path.stat().st_size if path.exists() else 0

    def emit(self, record: logging.LogRecord) -> None:
        try:
            message = self.format(record) + "\n"
            payload = message.encode("utf-8")
            with self._lock:
                day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
                if day != self._day or (self.max_bytes > 0 and self._bytes + len(payload) > self.max_bytes):
                    self._rollover(day)
                self._stream.write(message)
                self._stream.flush()
                self._bytes += len(payload)
        except Exception:  # noqa: BLE001
            self.handleError(record)

    def _rollover(self, day: str) -> None:
        self._stream.close()
        path = self._path()
        if path.exists() and path.stat().st_size > 0:
            stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S-%f")
            os.replace(path, self.directory / f"{self.basename}.{stamp}")
        self._day = day
        self._prune()
        self._open_current()

    def _prune(self) -> None:
        rotated = sorted(self.directory.glob(f"{self.basename}.*"))
        cutoff = datetime.now(timezone.utc) - timedelta(days=self.retention_days)
        kept: list[Path] = []
        for path in rotated:
            modified = datetime.fromtimestamp(path.stat().st_mtime, timezone.utc)
            if modified < cutoff:
                path.unlink(missing_ok=True)
                continue
            kept.append(path)
        if self.backup_count >= 0:
            for path in kept[: max(0, len(kept) - self.backup_count)]:
                path.unlink(missing_ok=True)

    def close(self) -> None:
        with self._lock:
            if self._stream and not self._stream.closed:
                self._stream.close()
        super().close()


class MemoryRateLimiter:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._counts: dict[tuple[str, str, int], int] = {}

    def reset(self) -> None:
        with self._lock:
            self._counts.clear()

    def hit(self, identity: str, rule: str, limit: int, window_seconds: int) -> tuple[bool, int, int]:
        now = int(time.time())
        window = max(1, window_seconds)
        bucket = now // window
        key = (identity, rule, bucket)
        with self._lock:
            stale = [item for item in self._counts if item[2] < bucket - 1]
            for item in stale:
                del self._counts[item]
            count = self._counts.get(key, 0) + 1
            self._counts[key] = count
        retry_after = window - (now % window)
        remaining = max(0, limit - count)
        return count <= limit, retry_after, remaining


memory_limiter = MemoryRateLimiter()


def load_local_env() -> None:
    """Apply .env when the process was not given those variables already."""
    global _env_loaded
    if _env_loaded or "pytest" in sys.modules:
        return
    _env_loaded = True
    path = Path(".env")
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if key and key not in os.environ:
            os.environ[key] = value.strip().strip('"').strip("'")


def _flag(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def rate_limit_enabled() -> bool:
    under_test = "pytest" in sys.modules
    return _flag("RATE_LIMIT_ENABLED", default=not under_test)


def file_logging_enabled() -> bool:
    under_test = "pytest" in sys.modules
    return _flag("LOG_TO_FILE", default=not under_test)


def log_directory() -> Path:
    raw = os.getenv("LOG_DIR")
    if raw:
        return Path(raw)
    if os.getenv("RUNNING_IN_DOCKER") == "1":
        return Path("/var/log/mydata")
    return Path("logs")


def _csv(name: str, default: str) -> list[str]:
    raw = os.getenv(name, default)
    return [part.strip() for part in raw.split(",") if part.strip()]


def _rules() -> list[tuple[str, str, int]]:
    rules: list[tuple[str, str, int]] = []
    for part in _csv("RATE_LIMIT_RULES", ""):
        try:
            left, limit_text = part.rsplit("=", 1)
            method, path = left.split(":", 1)
        except ValueError:
            continue
        rules.append((method.strip().upper(), path.strip(), int(limit_text)))
    return rules


def _limit_for(method: str, path: str) -> tuple[str, int]:
    for rule_method, rule_path, limit in _rules():
        if rule_method not in {"*", method.upper()}:
            continue
        if rule_path.endswith("*") and path.startswith(rule_path[:-1]):
            return f"{rule_method}:{rule_path}", limit
        if path == rule_path:
            return f"{rule_method}:{rule_path}", limit
    auth_paths = _csv(
        "RATE_LIMIT_AUTH_PATHS",
        "/v1/auth/login,/v1/auth/signup,/v1/auth/token",
    )
    for auth_path in auth_paths:
        if path == auth_path or path.startswith(auth_path + "/"):
            return "auth", _int("RATE_LIMIT_AUTH_REQUESTS", 30)
    return "default", _int("RATE_LIMIT_REQUESTS", 120)


def _exempt(path: str) -> bool:
    exempt = set(
        _csv(
            "RATE_LIMIT_EXEMPT_PATHS",
            "/health,/ready,/docs,/redoc,/openapi.json,/favicon.ico",
        )
    )
    return path in exempt


def _client_ip(request: Request) -> str:
    if _flag("RATE_LIMIT_TRUST_PROXY", False):
        forwarded = request.headers.get("x-forwarded-for", "")
        if forwarded:
            return forwarded.split(",")[0].strip() or "unknown"
    if request.client and request.client.host:
        return request.client.host
    return "unknown"


def _redis():
    global _redis_client
    url = os.getenv("RATE_LIMIT_REDIS_URL", "").strip()
    if not url:
        return None
    with _redis_lock:
        if _redis_client is not None:
            return _redis_client
        import redis

        _redis_client = redis.Redis.from_url(url, socket_timeout=0.2, socket_connect_timeout=0.2)
        return _redis_client


def _warn_redis_once(exc: Exception) -> None:
    global _last_redis_warning
    now = time.time()
    if now - _last_redis_warning < 60:
        return
    _last_redis_warning = now
    logger.warning("redis rate limit unavailable; using memory error=%s", type(exc).__name__)


def _hit(identity: str, rule: str, limit: int, window_seconds: int) -> tuple[bool, int, int]:
    url = os.getenv("RATE_LIMIT_REDIS_URL", "").strip()
    if url:
        try:
            client = _redis()
            key = f"rl:{identity}:{rule}:{int(time.time()) // max(1, window_seconds)}"
            count = int(client.incr(key))
            if count == 1:
                client.expire(key, max(1, window_seconds))
            ttl = int(client.ttl(key))
            retry_after = ttl if ttl > 0 else window_seconds
            return count <= limit, retry_after, max(0, limit - count)
        except Exception as exc:  # noqa: BLE001
            _warn_redis_once(exc)
    return memory_limiter.hit(identity, rule, limit, window_seconds)


def log_external_failure(operation: str, exc: Exception) -> None:
    logger.warning("external api failed operation=%s error=%s", operation, type(exc).__name__)


class SafeFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        return redact(super().format(record))


def _formatter() -> logging.Formatter:
    return SafeFormatter(
        "%(asctime)s %(levelname)s %(name)s request_id=%(request_id)s %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
    )


def reset_logging_for_tests() -> None:
    global _configured
    with _config_lock:
        _configured = False
        for log in (logging.getLogger(), access_logger):
            for handler in list(log.handlers):
                handler.close()
                log.removeHandler(handler)


def configure_logging(service_name: str) -> None:
    global _configured
    with _config_lock:
        if _configured:
            return
        level_name = os.getenv("LOG_LEVEL", "WARNING" if "pytest" in sys.modules else "INFO").upper()
        level = TRACE if level_name == "TRACE" else getattr(logging, level_name, logging.INFO)
        formatter = _formatter()
        redact_filter = RedactFilter()
        root = logging.getLogger()
        root.setLevel(level)
        stream = logging.StreamHandler(sys.stdout)
        stream.setFormatter(formatter)
        stream.addFilter(redact_filter)
        root.addHandler(stream)

        if file_logging_enabled():
            directory = log_directory()
            max_bytes = _int("LOG_MAX_BYTES", 10_485_760)
            backup_count = _int("LOG_BACKUP_COUNT", 14)
            retention_days = _int("LOG_RETENTION_DAYS", 14)
            try:
                application = DailySizeRotatingFileHandler(
                    directory, "application.log", max_bytes, backup_count, retention_days
                )
                application.setLevel(logging.INFO)
                application.setFormatter(formatter)
                application.addFilter(redact_filter)
                error = DailySizeRotatingFileHandler(
                    directory, "error.log", max_bytes, backup_count, retention_days
                )
                error.setLevel(logging.ERROR)
                error.setFormatter(formatter)
                error.addFilter(redact_filter)
                root.addHandler(application)
                root.addHandler(error)
                access_file = DailySizeRotatingFileHandler(
                    directory, "access.log", max_bytes, backup_count, retention_days
                )
                access_file.setFormatter(formatter)
                access_file.addFilter(RedactFilter())
                access_logger.addHandler(access_file)
            except OSError as exc:
                root.warning("file logging disabled error=%s", type(exc).__name__)

        access_stream = logging.StreamHandler(sys.stdout)
        access_stream.setFormatter(formatter)
        access_stream.addFilter(RedactFilter())
        access_logger.setLevel(logging.INFO)
        access_logger.propagate = False
        access_logger.addHandler(access_stream)
        logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
        _configured = True
        root.debug("logging configured service=%s", service_name)


class ObservabilityMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request = Request(scope, receive)
        path = request.url.path
        method = request.method
        request_id = request.headers.get("x-request-id") or str(uuid.uuid4())
        token = request_id_var.set(request_id)
        started = time.perf_counter()
        status_code = 500
        client_ip = _client_ip(request)

        if method != "OPTIONS" and rate_limit_enabled() and not _exempt(path):
            rule, limit = _limit_for(method, path)
            window = _int("RATE_LIMIT_WINDOW_SECONDS", 60)
            allowed, retry_after, _remaining = _hit(client_ip, rule, limit, window)
            if not allowed:
                logger.warning(
                    "rate limit exceeded client_ip=%s method=%s path=%s limit=%s window_seconds=%s",
                    client_ip,
                    method,
                    path,
                    limit,
                    window,
                )
                response = JSONResponse(
                    status_code=429,
                    media_type="application/problem+json",
                    content={
                        "type": "https://mydata.platform/errors/rate-limited",
                        "title": "Too Many Requests",
                        "status": 429,
                        "detail": "Too many requests. Retry after the indicated delay.",
                        "retryAfterSeconds": retry_after,
                    },
                    headers={
                        "Retry-After": str(retry_after),
                        "X-Request-Id": request_id,
                        "X-RateLimit-Limit": str(limit),
                        "X-RateLimit-Remaining": "0",
                        "X-RateLimit-Reset": str(retry_after),
                    },
                )
                try:
                    await response(scope, receive, send)
                finally:
                    _log_access(method, path, 429, started, client_ip)
                    request_id_var.reset(token)
                return

        async def send_wrapper(message):
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = message["status"]
                headers = MutableHeaders(scope=message)
                headers["X-Request-Id"] = request_id
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
            if status_code in {401, 403}:
                logger.warning(
                    "access denied method=%s path=%s status=%s client_ip=%s",
                    method,
                    path,
                    status_code,
                    client_ip,
                )
        finally:
            _log_access(method, path, status_code, started, client_ip)
            request_id_var.reset(token)


def _log_access(method: str, path: str, status_code: int, started: float, client_ip: str) -> None:
    if not _flag("LOG_ACCESS_ENABLED", "pytest" not in sys.modules):
        return
    duration_ms = (time.perf_counter() - started) * 1000
    access_logger.info(
        "method=%s path=%s status=%s duration_ms=%.1f client_ip=%s",
        method,
        path,
        status_code,
        duration_ms,
        client_ip,
    )


async def unhandled_exception(_request: Request, exc: Exception):
    logger.error("unhandled exception error=%s", type(exc).__name__, exc_info=exc)
    return JSONResponse(
        status_code=500,
        media_type="application/problem+json",
        content={
            "type": "https://mydata.platform/errors/internal",
            "title": "Internal Server Error",
            "status": 500,
            "detail": "The request could not be completed.",
            "requestId": request_id_var.get() or "-",
        },
        headers={"X-Request-Id": request_id_var.get() or "-"},
    )


_database_logged: set[int] = set()


def _attach_database_logging(engine) -> None:
    if engine is None or id(engine) in _database_logged:
        return
    from sqlalchemy import event

    _database_logged.add(id(engine))

    @event.listens_for(engine, "handle_error")
    def _on_database_error(context):
        original = getattr(context, "original_exception", None)
        logger.error(
            "database failure error=%s",
            type(original).__name__ if original else "unknown",
        )


def _add_ready_route(app: FastAPI, engine) -> None:
    existing = {getattr(route, "path", None) for route in app.routes}

    if "/ready" in existing:
        return

    @app.get("/ready", include_in_schema=False)
    def ready():
        if engine is None:
            return {"status": "ok"}
        try:
            from sqlalchemy import text

            with engine.connect() as connection:
                connection.execute(text("SELECT 1"))
        except Exception as exc:  # noqa: BLE001
            logger.warning("readiness check failed error=%s", type(exc).__name__)
            return JSONResponse(status_code=503, content={"status": "unavailable"})
        return {"status": "ok"}


def install_observability(app: FastAPI, *, service_name: str, engine=None) -> None:
    if getattr(app.state, "observability_installed", False):
        return
    app.state.observability_installed = True
    load_local_env()
    configure_logging(service_name)
    app.add_middleware(ObservabilityMiddleware)
    app.add_exception_handler(Exception, unhandled_exception)
    _attach_database_logging(engine)
    _add_ready_route(app, engine)

    async def _on_startup() -> None:
        logger.info("application started service=%s", service_name)

    async def _on_shutdown() -> None:
        logger.info("application shutting down service=%s", service_name)

    app.router.add_event_handler("startup", _on_startup)
    app.router.add_event_handler("shutdown", _on_shutdown)
