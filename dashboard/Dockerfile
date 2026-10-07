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

# Prevent Python from writing bytecode and buffering stdout/stderr
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH=/root/.local/bin:$PATH

WORKDIR /app

# Copy installed packages from builder
COPY --from=builder /root/.local /root/.local

# Copy only source code (no tests, no docs)
COPY dashboard/src/ .

EXPOSE 8080

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080"]
