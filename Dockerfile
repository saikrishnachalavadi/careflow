# CareFlow POC – production image
FROM python:3.12-slim

WORKDIR /app

# Install deps only (no venv needed in container)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# App code (env vars passed at run time)
COPY app/ ./app/

# Run as non-root
RUN useradd -m appuser && chown -R appuser:appuser /app
USER appuser

EXPOSE 8000

# Use env PORT if set (e.g. Cloud Run)
ENV PORT=8000
CMD uvicorn app.main:app --host 0.0.0.0 --port ${PORT}
