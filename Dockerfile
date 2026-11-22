FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    RUNNING_IN_DOCKER=1 \
    LOG_DIR=/var/log/mydata \
    LOG_TO_FILE=true \
    RATE_LIMIT_ENABLED=true

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt

COPY app ./app
RUN useradd --create-home --shell /usr/sbin/nologin appuser \
    && mkdir -p /var/log/mydata \
    && chown -R appuser:appuser /app /var/log/mydata

USER appuser

VOLUME ["/var/log/mydata"]

EXPOSE 8010

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD ["python", "-c", "from urllib.request import urlopen; urlopen('http://127.0.0.1:8010/health', timeout=3)"]

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8010", "--no-access-log"]
