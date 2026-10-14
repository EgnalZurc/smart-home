# ═══════════════════════════════════════════════════════════════════════════════
# Energy Monitor - Production Dockerfile
# Multi-stage build for a minimal image.
#
# Build context: repository root (to access libs/)
#   docker build -f services/energy-monitor/Dockerfile .
# ═══════════════════════════════════════════════════════════════════════════════

FROM python:3.12-slim AS builder
WORKDIR /build
COPY services/energy-monitor/requirements.txt .
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
COPY --chown=appuser:appuser services/energy-monitor/src/ .
# Ship the shared notifications package under LIBS_PATH (/app/libs) so the alert
# engine (later task) can `import notifications` (TelegramNotifier) at runtime.
# smart_home_common is pip-installed above; notifications is a bare package.
COPY --chown=appuser:appuser libs/notifications/ /app/libs/notifications/
RUN mkdir -p /app/data && chown -R appuser:appuser /app
USER appuser
EXPOSE 8012
HEALTHCHECK --interval=60s --timeout=5s --start-period=20s --retries=3 \
    CMD ["python3", "-c", "import urllib.request; urllib.request.urlopen('http://localhost:8012/health', timeout=3)"]
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8012"]
