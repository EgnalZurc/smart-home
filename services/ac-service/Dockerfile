# ═══════════════════════════════════════════════════════════════════════════════
# AC Service - Production Dockerfile
# Multi-stage build for minimal image size
#
# Build context: repository root (to access libs/)
# docker build -f services/ac-service/Dockerfile .
# ═══════════════════════════════════════════════════════════════════════════════

FROM python:3.12-slim AS builder
WORKDIR /build
COPY services/ac-service/requirements.txt .
RUN pip install --user --no-cache-dir --no-compile -r requirements.txt
# Install the shared library into the same --user prefix so it ships with the app.
COPY libs/smart_home_common/ /build/smart_home_common/
RUN pip install --user --no-cache-dir --no-compile /build/smart_home_common

FROM python:3.12-slim
RUN adduser --disabled-password --gecos '' --uid 1000 appuser
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH=/home/appuser/.local/bin:$PATH
WORKDIR /app
COPY --from=builder --chown=appuser:appuser /root/.local /home/appuser/.local
COPY --chown=appuser:appuser services/ac-service/src/ .
RUN mkdir -p /app/data && chown -R appuser:appuser /app
USER appuser
EXPOSE 8002
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8002"]
