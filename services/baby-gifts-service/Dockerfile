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
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH=/root/.local/bin:$PATH \
    PYTHONPATH=/app
WORKDIR /app
COPY --from=builder /root/.local /root/.local
COPY services/baby-gifts-service/src/ .
COPY libs/notifications/ /app/libs/notifications/
EXPOSE 8004
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8004"]
