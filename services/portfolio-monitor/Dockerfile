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
RUN adduser --disabled-password --gecos '' --uid 1000 appuser
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH=/home/appuser/.local/bin:$PATH \
    LIBS_PATH=/app/libs
WORKDIR /app
COPY --from=builder --chown=appuser:appuser /root/.local /home/appuser/.local
COPY --chown=appuser:appuser services/portfolio-monitor/src/ .
COPY --chown=appuser:appuser services/portfolio-monitor/locales/ /app/locales/
COPY --chown=appuser:appuser libs/http_client/ /app/libs/http_client/
COPY --chown=appuser:appuser libs/notifications/ /app/libs/notifications/
RUN mkdir -p /app/data && chown -R appuser:appuser /app
USER appuser
EXPOSE 8010
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8010"]
