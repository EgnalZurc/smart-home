# ═══════════════════════════════════════════════════════════════════════════════
# Smart Home Dashboard - Production Dockerfile
# Multi-stage build for minimal image size
# ═══════════════════════════════════════════════════════════════════════════════

# Stage 1: Build dependencies
FROM python:3.12-slim AS builder

WORKDIR /build

# Copy libs needed for local dependencies
COPY libs/smart_home_common /build/libs/smart_home_common

# Copy requirements and install
COPY dashboard/requirements.txt .
RUN pip install --user --no-cache-dir --no-compile -r requirements.txt && \
    pip install --user --no-cache-dir --no-compile /build/libs/smart_home_common

# Stage 2: Runtime (minimal)
FROM python:3.12-slim

# Create non-root user
RUN adduser --disabled-password --gecos '' --uid 1000 appuser

# Prevent Python from writing bytecode and buffering stdout/stderr.
# PYTHONPATH=/app so the shared libs copied to /app/libs are importable
# (e.g. `from libs.service_proxy.fastapi import ServiceProxy`).
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app \
    PATH=/home/appuser/.local/bin:$PATH

WORKDIR /app

# Copy installed packages from builder into the non-root user's home
COPY --from=builder --chown=appuser:appuser /root/.local /home/appuser/.local

# Copy only source code (no tests, no docs)
COPY --chown=appuser:appuser dashboard/src/ .

# Shared service-proxy library (imported as libs.service_proxy.*).
# Only this lib is needed at runtime; smart_home_common is pip-installed above.
COPY --chown=appuser:appuser libs/service_proxy/ /app/libs/service_proxy/

# Writable data dir for the bind-mounted volume (./data/backend:/app/data)
RUN mkdir -p /app/data && chown -R appuser:appuser /app

USER appuser

EXPOSE 8080

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080"]
