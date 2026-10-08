# ═══════════════════════════════════════════════════════════════════════════════
# Casita Sueños Service - Production Dockerfile
# Multi-stage build for minimal image size
# ═══════════════════════════════════════════════════════════════════════════════

FROM python:3.12-slim AS builder
WORKDIR /build
COPY requirements.txt .
RUN pip install --user --no-cache-dir --no-compile -r requirements.txt

FROM python:3.12-slim
RUN adduser --disabled-password --gecos '' --uid 1000 appuser
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH=/home/appuser/.local/bin:$PATH
WORKDIR /app
COPY --from=builder --chown=appuser:appuser /root/.local /home/appuser/.local
COPY --chown=appuser:appuser src/ .
# Writable data dir (declared VOLUME + CASITA_DATA_DIR=/app/data)
RUN mkdir -p /app/data && chown -R appuser:appuser /app
USER appuser
VOLUME ["/app/data"]
CMD ["python", "main.py"]
