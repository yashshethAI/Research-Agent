#!/usr/bin/env bash
# Launch FastAPI Backend Service
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(dirname "$SCRIPT_DIR")"

cd "$ROOT_DIR"

if [ -d ".venv" ]; then
    source .venv/bin/activate
fi

echo "🚀 Starting GST Practice Copilot Backend on http://127.0.0.1:8000..."
exec uvicorn backend.app.main:app --host 127.0.0.1 --port 8000 --reload
