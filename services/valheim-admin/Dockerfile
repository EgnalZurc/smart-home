FROM python:3.12-slim

# Create non-root user
RUN adduser --disabled-password --gecos '' --uid 1000 appuser

WORKDIR /app

# Copy and install requirements (as root, into site-packages)
COPY services/valheim-admin/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy shared libraries
COPY --chown=appuser:appuser libs/async_http_client/ /app/libs/async_http_client/

# Copy service source
COPY --chown=appuser:appuser services/valheim-admin/src/ .

RUN chown -R appuser:appuser /app

ENV PYTHONPATH=/app/libs

USER appuser

EXPOSE 8080
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080"]
