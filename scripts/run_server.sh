#!/usr/bin/env bash
# Run CareFlow API on port 3000 (edit PORT below if needed)
cd "$(dirname "$0")/.."
source careflow_env/bin/activate
PORT=3000
echo "Starting CareFlow on http://127.0.0.1:$PORT"
uvicorn app.main:app --reload --host 127.0.0.1 --port "$PORT"
