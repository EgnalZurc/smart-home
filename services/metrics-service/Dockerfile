# ═══════════════════════════════════════════════════════════════════════════════
# Metrics Service - Production Dockerfile
# Multi-stage build for a minimal image.
#
# Build context: repository root (to access libs/)
#   docker build -f services/metrics-service/Dockerfile .
#
# Runtime note: /proc and /sys are bind-mounted read-only by docker-compose so
# the host sampler reads the Pi host, not the container cgroup.
# ═══════════════════════════════════════════════════════════════════════════════

FROM python:3.12-slim AS builder
WORKDIR /build
COPY services/metrics-service/requirements.txt .
RUN pip install --user --no-cache-dir --no-compile -r requirements.txt
# Install the shared library into the same --user prefix so it ships with the app.
COPY libs/smart_home_common/ /build/smart_home_common/
RUN pip install --user --no-cache-dir --no-compile /build/smart_home_common

FROM python:3.12-slim
RUN adduser --disabled-password --gecos '' --uid 1000 appuser
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH=/home/appuser/.local/bin:$PATH \
    LIBS_PATH=/app/libs
WORKDIR /app
COPY --from=builder --chown=appuser:appuser /root/.local /home/appuser/.local
COPY --chown=appuser:appuser services/metrics-service/src/ .
RUN mkdir -p /app/data && chown -R appuser:appuser /app
USER appuser
EXPOSE 8011
HEALTHCHECK --interval=60s --timeout=5s --start-period=20s --retries=3 \
    CMD ["python3", "-c", "import urllib.request; urllib.request.urlopen('http://localhost:8011/health', timeout=3)"]
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8011"]
