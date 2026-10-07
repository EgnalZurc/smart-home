# ═══════════════════════════════════════════════════════════════════════════════
# Portfolio Monitor Service - Production Dockerfile
# Multi-stage build for minimal image size
#
# Build context: repository root (to access libs/)
# docker build -f services/portfolio-monitor/Dockerfile .
# ═══════════════════════════════════════════════════════════════════════════════

FROM python:3.12-slim AS builder
WORKDIR /build
COPY services/portfolio-monitor/requirements.txt .
RUN pip install --user --no-cache-dir --no-compile -r requirements.txt

FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH=/root/.local/bin:$PATH \
    LIBS_PATH=/app/libs
WORKDIR /app
COPY --from=builder /root/.local /root/.local
COPY services/portfolio-monitor/src/ .
COPY libs/http_client/ /app/libs/http_client/
COPY libs/notifications/ /app/libs/notifications/
EXPOSE 8010
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8010"]
