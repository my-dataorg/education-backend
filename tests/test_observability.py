import logging
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.observability import (
    DailySizeRotatingFileHandler,
    configure_logging,
    memory_limiter,
    reset_logging_for_tests,
)


@pytest.fixture(autouse=True)
def reset_rate_limiter():
    memory_limiter.reset()
    yield
    memory_limiter.reset()


def test_health_is_not_rate_limited(monkeypatch):
    monkeypatch.setenv("RATE_LIMIT_ENABLED", "true")
    monkeypatch.setenv("RATE_LIMIT_REQUESTS", "1")
    client = TestClient(app)
    assert client.get("/health").status_code == 200
    assert client.get("/health").status_code == 200


def test_excess_requests_return_429(monkeypatch):
    monkeypatch.setenv("RATE_LIMIT_ENABLED", "true")
    monkeypatch.setenv("RATE_LIMIT_REQUESTS", "2")
    monkeypatch.setenv("RATE_LIMIT_WINDOW_SECONDS", "60")
    client = TestClient(app)

    assert client.get("/v1/rate-limit-probe").status_code != 429
    assert client.get("/v1/rate-limit-probe").status_code != 429
    blocked = client.get("/v1/rate-limit-probe")

    assert blocked.status_code == 429
    assert blocked.headers["content-type"].startswith("application/problem+json")
    body = blocked.json()
    assert body["status"] == 429
    assert body["title"] == "Too Many Requests"
    assert body["retryAfterSeconds"] >= 1
    assert blocked.headers["Retry-After"]
    assert blocked.headers["X-Request-Id"]
    assert "password" not in blocked.text.lower()


def test_log_files_redact_secrets_and_rotate(tmp_path, monkeypatch):
    monkeypatch.setenv("LOG_DIR", str(tmp_path))
    monkeypatch.setenv("LOG_TO_FILE", "true")
    monkeypatch.setenv("LOG_LEVEL", "INFO")
    monkeypatch.setenv("LOG_MAX_BYTES", "250")
    monkeypatch.setenv("LOG_BACKUP_COUNT", "2")
    monkeypatch.setenv("LOG_RETENTION_DAYS", "14")
    reset_logging_for_tests()
    try:
        configure_logging("test-service")
        logging.getLogger("app.security").info("login password=super-secret")
        application = (tmp_path / "application.log").read_text(encoding="utf-8")
        assert "super-secret" not in application
        assert "[redacted]" in application
        assert "request_id=" in application

        logging.getLogger("app.security").error("database failure")
        error_log = (tmp_path / "error.log").read_text(encoding="utf-8")
        assert "database failure" in error_log
        assert "super-secret" not in error_log

        handler = DailySizeRotatingFileHandler(
            tmp_path, "rotate.log", max_bytes=120, backup_count=2, retention_days=14
        )
        rotate_logger = logging.getLogger("rotate-check")
        rotate_logger.handlers.clear()
        rotate_logger.addHandler(handler)
        rotate_logger.propagate = False
        rotate_logger.setLevel(logging.INFO)
        for index in range(8):
            rotate_logger.info("row-%s %s", index, "x" * 80)
        handler.close()
        rotated = list(tmp_path.glob("rotate.log.*"))
        assert (tmp_path / "rotate.log").exists()
        assert 1 <= len(rotated) <= 2
    finally:
        reset_logging_for_tests()
        monkeypatch.setenv("LOG_TO_FILE", "false")
        monkeypatch.setenv("LOG_LEVEL", "WARNING")
        configure_logging("test-service")


def test_limiter_is_thread_safe():
    memory_limiter.reset()

    def hit(_: int):
        return memory_limiter.hit("10.0.0.8", "default", 25, 60)

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(hit, range(40)))
    allowed = [ok for ok, _retry, _remaining in results if ok]
    assert len(allowed) == 25
