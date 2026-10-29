# ═══════════════════════════════════════════════════════════════════════════════
# Casita Sueños Service - Production Dockerfile
# Multi-stage build for minimal image size
#
# Build context: repository root (to access libs/)
# docker build -f services/casita-suenos/fase3-app/Dockerfile .
# ═══════════════════════════════════════════════════════════════════════════════

# Pin to specific Python version for reproducibility
# Update periodically to latest patch version for security fixes
FROM python:3.12.7-slim AS builder
WORKDIR /build
COPY services/casita-suenos/fase3-app/requirements.txt .
RUN pip install --user --no-cache-dir --no-compile -r requirements.txt
# Install the shared library into the same --user prefix so it ships with the app.
COPY libs/smart_home_common/ /build/smart_home_common/
RUN pip install --user --no-cache-dir --no-compile /build/smart_home_common

FROM python:3.12.7-slim
RUN adduser --disabled-password --gecos '' --uid 1000 appuser
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH=/home/appuser/.local/bin:$PATH
WORKDIR /app
COPY --from=builder --chown=appuser:appuser /root/.local /home/appuser/.local
COPY --chown=appuser:appuser services/casita-suenos/fase3-app/src/ .
# Writable data dir (declared VOLUME + CASITA_DATA_DIR=/app/data)
RUN mkdir -p /app/data && chown -R appuser:appuser /app
USER appuser
VOLUME ["/app/data"]
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8001/health', timeout=5)" || exit 1
CMD ["python", "main.py"]
