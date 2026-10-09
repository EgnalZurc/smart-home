FROM python:3.12-slim

# Create non-root user
RUN adduser --disabled-password --gecos '' --uid 1000 appuser

WORKDIR /app

# Copy and install requirements (as root, into site-packages)
COPY services/valheim-admin/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy shared libraries
COPY --chown=appuser:appuser libs/async_http_client/ /app/libs/async_http_client/
COPY --chown=appuser:appuser libs/smart_home_common/src/smart_home_common/ /app/libs/smart_home_common/

# Copy service source
COPY --chown=appuser:appuser services/valheim-admin/src/ .

RUN chown -R appuser:appuser /app

ENV PYTHONPATH=/app/libs

USER appuser

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --retries=3 --start-period=20s \
  CMD python3 -c "import urllib.request; urllib.request.urlopen('http://localhost:8080/health', timeout=3)" || exit 1

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080"]
