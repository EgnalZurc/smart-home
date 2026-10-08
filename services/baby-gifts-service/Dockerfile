# ═══════════════════════════════════════════════════════════════════════════════
# Baby Gifts Service - Production Dockerfile
# Multi-stage build for minimal image size
# Build context must be repo root: docker build -f services/baby-gifts-service/Dockerfile .
# ═══════════════════════════════════════════════════════════════════════════════

FROM python:3.12-slim AS builder
WORKDIR /build
COPY services/baby-gifts-service/requirements.txt .
RUN pip install --user --no-cache-dir --no-compile -r requirements.txt

FROM python:3.12-slim
RUN adduser --disabled-password --gecos '' --uid 1000 appuser
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH=/home/appuser/.local/bin:$PATH \
    PYTHONPATH=/app
WORKDIR /app
COPY --from=builder --chown=appuser:appuser /root/.local /home/appuser/.local
COPY --chown=appuser:appuser services/baby-gifts-service/src/ .
COPY --chown=appuser:appuser libs/notifications/ /app/libs/notifications/
RUN mkdir -p /app/data && chown -R appuser:appuser /app
USER appuser
EXPOSE 8004
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8004"]
