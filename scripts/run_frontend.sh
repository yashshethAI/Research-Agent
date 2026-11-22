#!/usr/bin/env bash
# Launch Streamlit Frontend Dashboard
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(dirname "$SCRIPT_DIR")"

cd "$ROOT_DIR"

if [ -d ".venv" ]; then
    source .venv/bin/activate
fi

export PYTHONPATH="${ROOT_DIR}:${PYTHONPATH:-}"

echo "⚖️ Starting GST Practice Copilot Streamlit UI on http://localhost:8501..."
exec streamlit run frontend/app.py --server.port 8501 --server.headless false
