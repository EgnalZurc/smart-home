FROM python:3.12-slim

WORKDIR /app

# Copy and install requirements
COPY services/valheim-admin/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy shared libraries
COPY libs/async_http_client/ /app/libs/async_http_client/

# Copy service source
COPY services/valheim-admin/src/ .

ENV PYTHONPATH=/app/libs

EXPOSE 8080
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080"]
